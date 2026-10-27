"""FastAPI application for the Refinance Management service.

Run with ``uvicorn app:app --host 127.0.0.1 --port 8000`` from this directory.
"""

from __future__ import annotations

import json
import hashlib
import secrets
import threading
import time
import uuid
from datetime import datetime
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
    APPROVER_PASSWORD,
    APPROVER_USERNAME,
    APP_USER,
    logger,
)
from database import DatabaseError, test_connection
from services.excel_service import generate_excel, get_excel_filename
from services.refinance_service import (
    BatchNumberMissingError,
    SubmissionResult,
    generate_batch_number,
    get_batch_details,
    get_pending_batches,
    get_refinance_details,
    submit_refinance_batch,
    validate_column_mapping,
)
from services.xml_service import generate_xml, validate_xml

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
_submission_states: dict[str, str] = {}
_tag_batch_lock = threading.Lock()


class BatchSubmissionRequest(BaseModel):
    confirmed: bool = False
    authorizer_username: str = Field(min_length=1, max_length=128)
    authorizer_password: str = Field(min_length=1, max_length=256)


class ExcelExportRequest(BaseModel):
    columns: list[str] = Field(min_length=1, max_length=200)
    records: list[dict[str, Any]] = Field(min_length=1, max_length=50000)
    branch_id: str = Field(default="ALL", max_length=128)


class SelectionRequest(BaseModel):
    snapshot_id: str = Field(min_length=1, max_length=64)
    selected_ids: list[str] = Field(min_length=1, max_length=50000)


class SelectedBatchRequest(SelectionRequest):
    confirmed: bool = False
    authorizer_username: str = Field(min_length=1, max_length=128)
    authorizer_password: str = Field(min_length=1, max_length=256)


class TagBatchRequest(BaseModel):
    total_loan_no: str | None = Field(default=None, max_length=4000)
    create_by: str | None = Field(default=None, max_length=4000)


class PendingBatchesRequest(BaseModel):
    batch_no: str | None = None


class BatchDetailsRequest(BaseModel):
    batch_no: str | None = None


def _selected_xml(request: SelectionRequest) -> tuple[pd.DataFrame, str, dict[str, Any]]:
    selected_df, snapshot = _selected_dataframe(request)
    xml_data = generate_xml(selected_df)
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


def _validate_batch_authorization(confirmed: bool, username: str, password: str) -> str:
    if not ALLOW_BATCH_SUBMISSION or not APPROVER_USERNAME or not APPROVER_PASSWORD:
        raise HTTPException(
            status_code=403,
            detail="Batch submission is disabled. Enable it only after the bank's authorization workflow is configured.",
        )
    if not confirmed:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required before submission.")
    authorizer = username.strip()
    if not (
        secrets.compare_digest(authorizer, APPROVER_USERNAME)
        and secrets.compare_digest(password, APPROVER_PASSWORD)
    ):
        raise HTTPException(status_code=401, detail="Invalid authorizer credentials.")
    if secrets.compare_digest(authorizer.casefold(), APP_USER.casefold()):
        raise HTTPException(status_code=400, detail="Maker and authorizer must be different users.")
    return authorizer


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
    return {
        "branch_id": _branch_label(branch_id),
        "snapshot_id": snapshot_id,
        "retrieved_at": datetime.now().astimezone().isoformat(),
        "record_count": len(df),
        "columns": list(df.columns),
        "missing_xml_columns": missing_columns,
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
    authorizer = _validate_batch_authorization(
        request.confirmed,
        request.authorizer_username,
        request.authorizer_password,
    )
    maker = APP_USER

    selected_df, xml_data, snapshot = _selected_xml(request)
    fingerprint = hashlib.sha256(
        (request.snapshot_id + "\0" + "\0".join(sorted(request.selected_ids))).encode("utf-8")
    ).hexdigest()
    with _submission_lock:
        submission_state = _submission_states.get(fingerprint)
        if submission_state:
            raise HTTPException(
                status_code=409,
                detail="This exact selection has already been submitted or is in progress. Reload records before retrying.",
            )
        _submission_states[fingerprint] = "in_progress"

    now = datetime.now()
    try:
        result: SubmissionResult = submit_refinance_batch(
            xml_data=xml_data,
            make_by=maker,
            make_date=now,
            authorize_by=authorizer,
            authorize_date=now,
            record_count=len(selected_df),
        )
    except DatabaseError as exc:
        with _submission_lock:
            _submission_states[fingerprint] = "uncertain"
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Selected batch submission failed: %s", exc, exc_info=True)
        with _submission_lock:
            _submission_states[fingerprint] = "uncertain"
        raise HTTPException(status_code=500, detail="Submission outcome is uncertain; reload and verify before retrying.") from exc

    with _submission_lock:
        _submission_states[fingerprint] = "submitted" if result.success else "uncertain"
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