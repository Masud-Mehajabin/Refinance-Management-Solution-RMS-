"""HTTP contract tests for the FastAPI application."""

from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock
from xml.etree.ElementTree import fromstring

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as app_module
from services.refinance_service import SubmissionResult


@pytest.fixture
def api_client():
    with TestClient(app_module.app) as client:
        yield client


def test_health_is_available_without_database():
    with TestClient(app_module.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_dashboard_is_available_without_login():
    with TestClient(app_module.app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Refinance records" in response.text


def test_retrieve_branch_returns_records(api_client, sample_df, monkeypatch):
    monkeypatch.setattr(app_module, "get_refinance_details", lambda branch: sample_df)

    response = api_client.get("/api/refinance/0101")

    assert response.status_code == 200
    payload = response.json()
    assert payload["branch_id"] == "0101"
    assert payload["record_count"] == 1
    assert payload["records"][0]["ACCOUNT_NUMBER"] == "0101000001"
    assert payload["missing_xml_columns"] == []


def test_retrieve_all_branches_when_filter_is_omitted(api_client, sample_df, monkeypatch):
    retrieve = Mock(return_value=sample_df)
    monkeypatch.setattr(app_module, "get_refinance_details", retrieve)

    response = api_client.get("/api/refinance")

    assert response.status_code == 200
    assert response.json()["branch_id"] == "ALL BRANCHES"
    retrieve.assert_called_once_with(None)


def _load_snapshot(client, monkeypatch, dataframe):
    monkeypatch.setattr(app_module, "get_refinance_details", lambda branch: dataframe)
    response = client.get("/api/refinance?branch_id=0101")
    assert response.status_code == 200
    return response.json()


def test_selected_excel_contains_only_original_selected_rows(api_client, multi_row_df, monkeypatch):
    snapshot = _load_snapshot(api_client, monkeypatch, multi_row_df)
    selected = [snapshot["records"][0]["record_id"], snapshot["records"][2]["record_id"]]
    retrieve = Mock(side_effect=AssertionError("selection export must not query Oracle"))
    monkeypatch.setattr(app_module, "get_refinance_details", retrieve)

    response = api_client.post(
        "/api/refinance/selected/excel",
        json={"snapshot_id": snapshot["snapshot_id"], "selected_ids": selected},
    )

    assert response.status_code == 200
    workbook = load_workbook(BytesIO(response.content), read_only=True)
    sheet = workbook.active
    assert sheet.max_row == 3
    headers = [cell.value for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
    assert "record_id" not in headers
    account_col = headers.index("ACCOUNT_NUMBER")
    accounts = [row[account_col] for row in sheet.iter_rows(min_row=2, values_only=True)]
    assert accounts == [multi_row_df.iloc[0]["ACCOUNT_NUMBER"], multi_row_df.iloc[2]["ACCOUNT_NUMBER"]]
    assert "Refinance_Selected_Records_" in response.headers["content-disposition"]
    retrieve.assert_not_called()


def test_selected_xml_contains_only_original_selected_rows(api_client, multi_row_df, monkeypatch):
    snapshot = _load_snapshot(api_client, monkeypatch, multi_row_df)
    selected = [snapshot["records"][1]["record_id"]]

    response = api_client.post(
        "/api/refinance/selected/xml",
        json={"snapshot_id": snapshot["snapshot_id"], "selected_ids": selected},
    )

    assert response.status_code == 200
    root = fromstring(response.text)
    details = root.findall("TRANS_DETAILS")
    assert len(details) == 1
    assert details[0].findtext("Paccount_number") == multi_row_df.iloc[1]["ACCOUNT_NUMBER"]
    assert all(child.tag != "record_id" for child in details[0])


def test_selected_operations_reject_ids_outside_snapshot(api_client, sample_df, monkeypatch):
    snapshot = _load_snapshot(api_client, monkeypatch, sample_df)

    response = api_client.post(
        "/api/refinance/selected/excel",
        json={"snapshot_id": snapshot["snapshot_id"], "selected_ids": ["not-in-this-snapshot"]},
    )

    assert response.status_code == 422


def test_empty_selection_is_rejected_before_submission(api_client, monkeypatch):
    submission = Mock()
    monkeypatch.setattr(app_module, "submit_refinance_batch", submission)

    response = api_client.post(
        "/api/refinance/selected/submit",
        json={
            "snapshot_id": "snapshot",
            "selected_ids": [],
            "confirmed": True,
            "authorizer_username": "approver",
            "authorizer_password": "secret",
        },
    )

    assert response.status_code == 422
    submission.assert_not_called()


def test_selected_batch_submission_requires_enablement_and_approver(api_client, monkeypatch):
    submission = Mock()
    monkeypatch.setattr(app_module, "submit_refinance_batch", submission)
    monkeypatch.setattr(app_module, "ALLOW_BATCH_SUBMISSION", True)
    monkeypatch.setattr(app_module, "APPROVER_USERNAME", "")
    monkeypatch.setattr(app_module, "APPROVER_PASSWORD", "")

    response = api_client.post(
        "/api/refinance/selected/submit",
        json={
            "snapshot_id": "snapshot",
            "selected_ids": ["row-id"],
            "confirmed": True,
            "authorizer_username": "approver",
            "authorizer_password": "secret",
        },
    )

    assert response.status_code == 403
    submission.assert_not_called()


def test_selected_batch_submission_validates_approver(api_client, sample_df, monkeypatch):
    snapshot = _load_snapshot(api_client, monkeypatch, sample_df)
    monkeypatch.setattr(app_module, "ALLOW_BATCH_SUBMISSION", True)
    monkeypatch.setattr(app_module, "APPROVER_USERNAME", "approver")
    monkeypatch.setattr(app_module, "APPROVER_PASSWORD", "approver-secret")
    submission = Mock()
    monkeypatch.setattr(app_module, "submit_refinance_batch", submission)

    response = api_client.post(
        "/api/refinance/selected/submit",
        json={
            "snapshot_id": snapshot["snapshot_id"],
            "selected_ids": [snapshot["records"][0]["record_id"]],
            "confirmed": True,
            "authorizer_username": "someone-else",
            "authorizer_password": "wrong-secret",
        },
    )

    assert response.status_code == 401
    submission.assert_not_called()


def test_selected_batch_submission_requires_explicit_confirmation(api_client, sample_df, monkeypatch):
    snapshot = _load_snapshot(api_client, monkeypatch, sample_df)
    monkeypatch.setattr(app_module, "ALLOW_BATCH_SUBMISSION", True)
    monkeypatch.setattr(app_module, "APPROVER_USERNAME", "approver")
    monkeypatch.setattr(app_module, "APPROVER_PASSWORD", "approver-secret")
    submission = Mock()
    monkeypatch.setattr(app_module, "submit_refinance_batch", submission)

    response = api_client.post(
        "/api/refinance/selected/submit",
        json={
            "snapshot_id": snapshot["snapshot_id"],
            "selected_ids": [snapshot["records"][0]["record_id"]],
            "confirmed": False,
            "authorizer_username": "approver",
            "authorizer_password": "approver-secret",
        },
    )

    assert response.status_code == 400
    submission.assert_not_called()


def test_selected_batch_submission_uses_only_selected_original_rows(api_client, multi_row_df, monkeypatch):
    snapshot = _load_snapshot(api_client, monkeypatch, multi_row_df)
    monkeypatch.setattr(app_module, "ALLOW_BATCH_SUBMISSION", True)
    monkeypatch.setattr(app_module, "APPROVER_USERNAME", "approver")
    monkeypatch.setattr(app_module, "APPROVER_PASSWORD", "approver-secret")
    monkeypatch.setattr(app_module, "APP_USER", "maker-user")
    result = SubmissionResult(
        success=True,
        message="Batch created",
        batch_number="BATCH-001",
        record_count=2,
    )
    submission = Mock(return_value=result)
    monkeypatch.setattr(app_module, "submit_refinance_batch", submission)

    response = api_client.post(
        "/api/refinance/selected/submit",
        json={
            "snapshot_id": snapshot["snapshot_id"],
            "selected_ids": [snapshot["records"][0]["record_id"], snapshot["records"][2]["record_id"]],
            "confirmed": True,
            "authorizer_username": "approver",
            "authorizer_password": "approver-secret",
        },
    )

    assert response.status_code == 200
    assert response.json()["batch_number"] == "BATCH-001"
    assert response.json()["record_count"] == 2
    assert submission.call_args.kwargs["make_by"] == "maker-user"
    assert submission.call_args.kwargs["authorize_by"] == "approver"
    xml_root = fromstring(submission.call_args.kwargs["xml_data"])
    assert len(xml_root.findall("TRANS_DETAILS")) == 2
    assert [detail.findtext("Paccount_number") for detail in xml_root.findall("TRANS_DETAILS")] == [
        multi_row_df.iloc[0]["ACCOUNT_NUMBER"],
        multi_row_df.iloc[2]["ACCOUNT_NUMBER"],
    ]


def test_selected_batch_rejects_duplicate_submission(api_client, sample_df, monkeypatch):
    snapshot = _load_snapshot(api_client, monkeypatch, sample_df)
    monkeypatch.setattr(app_module, "ALLOW_BATCH_SUBMISSION", True)
    monkeypatch.setattr(app_module, "APPROVER_USERNAME", "approver")
    monkeypatch.setattr(app_module, "APPROVER_PASSWORD", "approver-secret")
    monkeypatch.setattr(app_module, "APP_USER", "maker-user")
    submission = Mock(return_value=SubmissionResult(success=True, message="ok", batch_number="B-1", record_count=1))
    monkeypatch.setattr(app_module, "submit_refinance_batch", submission)
    payload = {
        "snapshot_id": snapshot["snapshot_id"],
        "selected_ids": [snapshot["records"][0]["record_id"]],
        "confirmed": True,
        "authorizer_username": "approver",
        "authorizer_password": "approver-secret",
    }

    first = api_client.post("/api/refinance/selected/submit", json=payload)
    second = api_client.post("/api/refinance/selected/submit", json=payload)

    assert first.status_code == 200
    assert second.status_code == 409
    submission.assert_called_once()