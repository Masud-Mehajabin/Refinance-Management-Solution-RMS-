"""FastAPI application for the Refinance Management service.

Run with ``uvicorn app:app --host 127.0.0.1 --port 8000`` from this directory.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import date, datetime, time as datetime_time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import pandas as pd
from pydantic import BaseModel, Field

from config import (
    ALLOW_BATCH_SUBMISSION,
    APP_ENV,
    logger,
)
from database import DatabaseError, test_connection
from services.excel_service import generate_excel, get_excel_filename
from services.refinance_service import (
    BatchNumberMissingError,
    SubmissionOutcomeUncertainError,
    SubmissionResult,
    generate_batch_number,
    get_batch_details,
    get_pending_batches,
    get_refinance_batch_numbers,
    get_refinance_details,
    submit_refinance_batch,
    tag_batch_reference,
    validate_column_mapping,
)
from services.xml_service import generate_xml, missing_required_xml_values, validate_xml

app = FastAPI(
    title="Refinance Management API",
    version="1.0.0",
    description="Branch refinance retrieval, export, XML preview, and controlled batch submission.",
)
STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.middleware("http")
async def disable_response_caching(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
EXCEL_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SNAPSHOT_TTL_SECONDS = 3600
MAX_SNAPSHOTS = 100
_snapshot_lock = threading.Lock()
_snapshots: dict[str, dict[str, Any]] = {}
_submission_lock = threading.Lock()
_submission_record_states: dict[tuple[str, str], tuple[str, float]] = {}
_tag_batch_lock = threading.Lock()
_tag_reference_lock = threading.Lock()


class ExcelExportRequest(BaseModel):
    columns: list[str] = Field(min_length=1, max_length=200)
    records: list[dict[str, Any]] = Field(min_length=1, max_length=50000)
    branch_id: str = Field(default="ALL", max_length=128)


class SelectionRequest(BaseModel):
    snapshot_id: str = Field(min_length=1, max_length=64)
    selected_ids: list[str] = Field(min_length=1, max_length=50000)


class SelectedBatchRequest(SelectionRequest):
    confirmed: bool = False
    pxml_data: str = Field(min_length=1)
    pmake_by: str | None = Field(default=None, max_length=128)
    pmake_date: date | None = None
    pauthorize_by: str | None = Field(default=None, max_length=128)
    pauthorize_date: date | None = None


class TagBatchRequest(BaseModel):
    total_loan_no: str | None = Field(default=None, max_length=4000)
    create_by: str | None = Field(default=None, max_length=4000)


class TagReferenceRequest(BaseModel):
    batch_no: str = Field(min_length=1, max_length=128)
    reference_no: str = Field(min_length=1, max_length=128)


class PendingBatchesRequest(BaseModel):
    batch_no: str | None = None


class BatchDetailsRequest(BaseModel):
    batch_no: str | None = None


def _selected_xml(
    request: SelectionRequest,
) -> tuple[pd.DataFrame, str, dict[str, Any]]:
    selected_df, snapshot = _selected_dataframe(request)
    try:
        xml_data = generate_xml(selected_df)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Unable to generate submission XML: {exc}") from exc
    is_valid, message = validate_xml(xml_data)
    if not is_valid:
        raise HTTPException(status_code=422, detail=f"XML validation failed: {message}")
    return selected_df, xml_data, snapshot


def _load_branch(branch_id: str | None):
    try:
        return get_refinance_details(branch_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Refinance retrieval failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Unable to retrieve refinance data.") from exc


def _branch_label(branch_id: str | None) -> str:
    return branch_id.strip() if branch_id and branch_id.strip() else "ALL BRANCHES"


def _validate_batch_submission(confirmed: bool) -> None:
    if not ALLOW_BATCH_SUBMISSION:
        raise HTTPException(
            status_code=403,
            detail="Batch submission is disabled.",
        )
    if not confirmed:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required before submission.")


def _new_snapshot(df: pd.DataFrame, branch_id: str | None) -> tuple[str, list[dict[str, Any]]]:
    snapshot_id = uuid.uuid4().hex
    positions: dict[str, int] = {}
    output_records: list[dict[str, Any]] = []
    business_json = df.to_json(orient="records", date_format="iso", default_handler=str)
    records = json.loads(business_json)

    for position, record in enumerate(records):
        selection_id = uuid.uuid4().hex
        positions[selection_id] = position
        record["record_id"] = selection_id
        output_records.append(record)

    now = time.monotonic()
    with _snapshot_lock:
        expired = [key for key, value in _snapshots.items() if now - value["created"] > SNAPSHOT_TTL_SECONDS]
        for key in expired:
            _snapshots.pop(key, None)
        while len(_snapshots) >= MAX_SNAPSHOTS:
            oldest = min(_snapshots, key=lambda key: _snapshots[key]["created"])
            _snapshots.pop(oldest, None)
        _snapshots[snapshot_id] = {
            "created": now,
            "branch_id": branch_id.strip() if branch_id and branch_id.strip() else None,
            "data": df.copy(deep=True),
            "positions": positions,
        }
    return snapshot_id, output_records


def _get_snapshot(snapshot_id: str) -> dict[str, Any]:
    now = time.monotonic()
    with _snapshot_lock:
        snapshot = _snapshots.get(snapshot_id)
        if snapshot is None or now - snapshot["created"] > SNAPSHOT_TTL_SECONDS:
            _snapshots.pop(snapshot_id, None)
            raise HTTPException(status_code=410, detail="This retrieved dataset expired. Load the records again.")
        return snapshot


def _selected_dataframe(request: SelectionRequest) -> tuple[pd.DataFrame, dict[str, Any]]:
    snapshot = _get_snapshot(request.snapshot_id)
    positions = snapshot["positions"]
    if len(set(request.selected_ids)) != len(request.selected_ids):
        raise HTTPException(status_code=422, detail="Selection contains duplicate record identifiers.")
    unknown_ids = [record_id for record_id in request.selected_ids if record_id not in positions]
    if unknown_ids:
        raise HTTPException(status_code=422, detail="Selection includes records outside the loaded dataset.")
    selected_positions = [positions[record_id] for record_id in request.selected_ids]
    if not selected_positions:
        raise HTTPException(status_code=422, detail="Please select at least one refinance record before continuing.")
    return snapshot["data"].iloc[selected_positions].copy(deep=True), snapshot


def _records_response(branch_id: str | None) -> dict:
    df = _load_branch(branch_id)
    _, missing_columns = validate_column_mapping(df)
    snapshot_id, records = _new_snapshot(df, branch_id)
    xml_error = None
    try:
        loaded_xml = generate_xml(df) if not df.empty else ""
        if loaded_xml:
            is_valid, validation_message = validate_xml(loaded_xml)
            if not is_valid:
                logger.error(
                    "Generated loaded-record XML failed validation for snapshot %s: %s",
                    snapshot_id,
                    validation_message,
                )
                loaded_xml = ""
                xml_error = "Unable to validate XML for the loaded refinance data."
    except ValueError:
        logger.warning(
            "Unable to generate XML for loaded refinance data (snapshot %s).",
            snapshot_id,
            exc_info=True,
        )
        loaded_xml = ""
        xml_error = "Unable to generate XML for the loaded refinance data."
    return {
        "branch_id": _branch_label(branch_id),
        "snapshot_id": snapshot_id,
        "retrieved_at": datetime.now().astimezone().isoformat(),
        "record_count": len(df),
        "columns": list(df.columns),
        "missing_xml_columns": missing_columns,
        "xml_data": loaded_xml,
        "xml_error": xml_error,
        "records": records,
    }


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "environment": APP_ENV}


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


@app.get("/api/health/database", tags=["system"])
def database_health() -> dict[str, str]:
    connected, message = test_connection()
    if not connected:
        raise HTTPException(status_code=503, detail=message)
    return {"status": "connected", "message": message}


@app.get("/api/refinance/{branch_id}", tags=["refinance"])
def refinance_records(branch_id: str) -> dict:
    return _records_response(branch_id)


@app.get("/api/refinance", tags=["refinance"])
def all_or_branch_records(branch_id: str | None = None) -> dict:
    return _records_response(branch_id)


@app.post("/api/refinance/selected/excel", tags=["refinance"])
def export_selected_excel(request: SelectionRequest) -> Response:
    selected_df, snapshot = _selected_dataframe(request)
    try:
        content = generate_excel(selected_df, snapshot["branch_id"] or "ALL")
    except Exception as exc:
        logger.error("Selected Excel generation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Unable to generate the selected-record Excel file.") from exc
    filename = f"Refinance_Selected_Records_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    return Response(
        content=content,
        media_type=EXCEL_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/refinance/selected/xml", tags=["refinance"])
def download_selected_xml(request: SelectionRequest) -> Response:
    _, xml_data, _ = _selected_xml(request)
    filename = f"Refinance_Selected_Records_{datetime.now():%Y%m%d_%H%M%S}.xml"
    return Response(
        content=xml_data,
        media_type="application/xml; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _submit_selected_batch(request: SelectedBatchRequest) -> dict:
    _validate_batch_submission(request.confirmed)

    if not request.pxml_data.strip():
        raise HTTPException(status_code=422, detail="XML Data is required.")
    is_valid, validation_message = validate_xml(request.pxml_data)
    if not is_valid:
        raise HTTPException(
            status_code=422,
            detail=f"XML Data is invalid: {validation_message}",
        )
    selected_df, xml_data, snapshot = _selected_xml(request)
    if request.pxml_data != xml_data:
        raise HTTPException(
            status_code=422,
            detail="XML Data does not match the selected records. Close the dialog and prepare it again.",
        )
    missing_required_values = missing_required_xml_values(selected_df)
    if missing_required_values:
        raise HTTPException(
            status_code=422,
            detail=(
                "Selected records have empty values for required database fields: "
                f"{', '.join(missing_required_values)}. Correct the source data and reload."
            ),
        )
    submission_keys = [(request.snapshot_id, record_id) for record_id in request.selected_ids]
    with _submission_lock:
        now_monotonic = time.monotonic()
        expired_keys = [
            key
            for key, (state, updated_at) in _submission_record_states.items()
            if state != "in_progress" and now_monotonic - updated_at > SNAPSHOT_TTL_SECONDS
        ]
        for key in expired_keys:
            _submission_record_states.pop(key, None)
        if any(key in _submission_record_states for key in submission_keys):
            raise HTTPException(
                status_code=409,
                detail="One or more selected records have already been submitted or are in progress. Reload records before retrying.",
            )
        for key in submission_keys:
            _submission_record_states[key] = ("in_progress", now_monotonic)

    make_date = datetime.combine(request.pmake_date, datetime_time.min) if request.pmake_date else None
    authorize_date = (
        datetime.combine(request.pauthorize_date, datetime_time.min)
        if request.pauthorize_date
        else None
    )
    try:
        result: SubmissionResult = submit_refinance_batch(
            xml_data=request.pxml_data,
            make_by=request.pmake_by.strip() or None if request.pmake_by else None,
            make_date=make_date,
            authorize_by=request.pauthorize_by.strip() or None if request.pauthorize_by else None,
            authorize_date=authorize_date,
            record_count=len(selected_df),
        )
    except SubmissionOutcomeUncertainError as exc:
        with _submission_lock:
            for key in submission_keys:
                _submission_record_states[key] = ("uncertain", time.monotonic())
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        with _submission_lock:
            for key in submission_keys:
                _submission_record_states.pop(key, None)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Selected batch submission failed: %s", exc, exc_info=True)
        with _submission_lock:
            for key in submission_keys:
                _submission_record_states[key] = ("uncertain", time.monotonic())
        raise HTTPException(status_code=500, detail="Submission outcome is uncertain; reload and verify before retrying.") from exc

    with _submission_lock:
        for key in submission_keys:
            if result.success:
                _submission_record_states[key] = ("submitted", time.monotonic())
            else:
                _submission_record_states.pop(key, None)
    if not result.success:
        raise HTTPException(
            status_code=502,
            detail=result.message or "The Oracle procedure did not confirm a successful submission.",
        )
    return {
        "success": result.success,
        "message": result.message,
        "batch_number": result.batch_number,
        "timestamp": result.timestamp.isoformat() if result.timestamp else None,
        "record_count": result.record_count,
        "branch_id": _branch_label(snapshot["branch_id"]),
    }


@app.post("/api/refinance/selected/submit", tags=["refinance"])
def submit_selected_batch(request: SelectedBatchRequest) -> dict:
    return _submit_selected_batch(request)


@app.post("/api/refinance/tag-batch", tags=["refinance"])
def tag_refinance_batch(request: TagBatchRequest) -> dict[str, str | bool]:
    if not ALLOW_BATCH_SUBMISSION:
        raise HTTPException(
            status_code=403,
            detail="Batch generation is disabled. Enable it only after the bank's authorization workflow is configured.",
        )
    if not _tag_batch_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Batch generation is already in progress. Please wait.")

    try:
        try:
            batch_number = generate_batch_number(
                total_loan_no=request.total_loan_no,
                create_by=request.create_by,
            )
        except BatchNumberMissingError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except DatabaseError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("Tag Batch request failed: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Unable to generate the batch. Please contact the system administrator if the problem persists.",
            ) from exc
        return {
            "success": True,
            "batch_number": batch_number,
            "message": f"Batch {batch_number} has been generated successfully.",
        }
    finally:
        _tag_batch_lock.release()


@app.post("/api/refinance/tag-reference", tags=["refinance"])
def tag_refinance_reference(request: TagReferenceRequest) -> dict[str, str | int | bool]:
    batch_no = request.batch_no.strip()
    reference_no = request.reference_no.strip()
    if not batch_no:
        raise HTTPException(status_code=422, detail="Batch No. is required.")
    if not reference_no:
        raise HTTPException(status_code=422, detail="Reference No. is required.")
    if not ALLOW_BATCH_SUBMISSION:
        raise HTTPException(
            status_code=403,
            detail="Reference number updates are disabled.",
        )
    if not _tag_reference_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="A reference number update is already in progress. Please wait.",
        )

    try:
        try:
            rows_updated = tag_batch_reference(batch_no, reference_no)
        except DatabaseError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("Reference number update failed: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Unable to assign the reference number. Please contact the system administrator.",
            ) from exc

        if rows_updated <= 0:
            raise HTTPException(
                status_code=404,
                detail="No records found for the specified Batch No. Please verify the batch number and try again.",
            )
        return {
            "success": True,
            "batch_no": batch_no,
            "reference_no": reference_no,
            "records_updated": rows_updated,
            "message": (
                f"Reference No. {reference_no} has been successfully assigned to "
                f"Batch No. {batch_no}. Total records updated: {rows_updated}."
            ),
        }
    finally:
        _tag_reference_lock.release()


@app.get("/api/refinance/tag-reference/batches", tags=["refinance"])
def refinance_reference_batches() -> dict[str, list[str]]:
    try:
        batch_numbers = get_refinance_batch_numbers()
    except DatabaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Reference-tagging batch list retrieval failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve batch numbers. Please try again or contact the system administrator.",
        ) from exc

    return {"batch_numbers": batch_numbers}


@app.post("/api/refinance/pending-batches", tags=["refinance"])
def pending_batches(request: PendingBatchesRequest) -> dict[str, Any]:
    batch_no = request.batch_no.strip() if request.batch_no and request.batch_no.strip() else None
    try:
        dataframe = get_pending_batches(batch_no)
    except DatabaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Pending batch retrieval failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve pending batches. Please try again or contact the system administrator.",
        ) from exc

    return {
        "batch_no": batch_no,
        "columns": list(dataframe.columns),
        "records": json.loads(
            dataframe.to_json(orient="records", date_format="iso", default_handler=str)
        ),
        "record_count": len(dataframe),
    }


@app.post("/api/refinance/batch-details", tags=["refinance"])
def batch_details(request: BatchDetailsRequest) -> dict[str, Any]:
    batch_no = request.batch_no.strip() if request.batch_no and request.batch_no.strip() else None
    try:
        dataframe = get_batch_details(batch_no)
    except DatabaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Batch detail retrieval failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve batch details. Please try again or contact the system administrator.",
        ) from exc

    return {
        "batch_no": batch_no,
        "columns": list(dataframe.columns),
        "records": json.loads(
            dataframe.to_json(orient="records", date_format="iso", default_handler=str)
        ),
        "record_count": len(dataframe),
    }


@app.get("/api/info", tags=["system"])
def application_info() -> dict[str, str]:
    return {"application": "Refinance Management", "user": APP_USER, "environment": APP_ENV}