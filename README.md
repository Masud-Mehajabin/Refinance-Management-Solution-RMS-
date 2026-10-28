# Refinance Management

FastAPI application for retrieving branch refinance data, exporting Excel and XML, and submitting a batch through the existing Oracle procedures.

## Run locally

1. Create and activate a Python virtual environment.
2. Install dependencies with `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and set the required Oracle credentials. Keep `.env` out of source control.
4. Start the app from this directory:

```powershell
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. Local dashboard and API access do not require a login. Interactive API documentation is available at `http://127.0.0.1:8000/docs`.

## Configuration

- `ORACLE_USER`, `ORACLE_PASSWORD`, and `ORACLE_DSN` configure the Oracle connection.
- Batch writes remain disabled unless `ALLOW_BATCH_SUBMISSION=true`. The application does not populate maker or authorizer identities from configuration; the submission dialog's optional values are passed as entered, and blank values are sent to Oracle as `NULL`.
- The dashboard's **Tag Reference No.** action requires `ALLOW_BATCH_SUBMISSION=true`. Choose a batch number from the list of existing `MGBL_REFINANCE_MASTER` batches and enter the Bangladesh Bank reference number to update `BB_REFERENCE_ID` for every record in that batch; the dashboard reports the actual number of rows updated.
- The dashboard/API have no login and must remain bound to localhost unless proper network authentication and HTTPS are added. Do not expose the development server directly to a network.
- The refinance table's **Submit** action submits only the selected snapshot records. The dialog displays read-only XML generated from those selected rows, followed by optional maker and authorizer IDs/dates. XML is validated and compared with the selected snapshot before execution; missing optional fields are passed as `NULL`. Successful submissions and submissions with an uncertain commit outcome stay locked to prevent duplicates. A procedure/database error with a confirmed rollback releases the selection so corrected input can be retried; the backend still rejects overlapping or repeated submissions for a successful snapshot.

The Oracle password shared in the setup request should be rotated before use. Configure the replacement only in the ignored local `.env` file or in the deployment secret manager; do not commit it.

## API

- `GET /health` is an unauthenticated process health check.
- `GET /api/health/database` tests Oracle connectivity.
- `GET /api/refinance?branch_id=...` retrieves records, mapping status, and XML generated from the loaded records; omit the filter to retrieve all branches. The response includes an opaque snapshot ID and stable record IDs. If a source column is absent, its XML element is included empty and the dashboard lists those source columns; Oracle determines whether the resulting record satisfies its insert rules.
- `POST /api/refinance/selected/excel` exports only the submitted record IDs from that snapshot.
- `POST /api/refinance/selected/xml` downloads an XML file built only from the selected snapshot rows. Each `<TRANS_DETAILS>` element includes a sequential `record_number` attribute starting at `1`.
- `POST /api/refinance/selected/submit` submits only those selected rows and requires `pxml_data`, enabled write configuration, and explicit confirmation. The XML must be well-formed and match the selected snapshot. `pmake_by`, `pmake_date`, `pauthorize_by`, and `pauthorize_date` are optional; omitted values are bound as `NULL`.
- `POST /api/refinance/tag-reference` updates only `MGBL_REFINANCE_MASTER.BB_REFERENCE_ID` for the supplied `batch_no`, using the supplied `reference_no`. Both values are required; a zero-row update returns `404`.
- `GET /api/refinance/tag-reference/batches` returns distinct non-null batch numbers currently present in `MGBL_REFINANCE_MASTER` for the reference-tagging dropdown.
- `POST /api/refinance/tag-batch` remains available for batch-number generation when `ALLOW_BATCH_SUBMISSION=true`; approver credentials are not required for this procedure call.
- `POST /api/refinance/pending-batches` calls `PKG_MGBL_REFINANCE.GET_UPAPPROVED_BATCH` with an optional `batch_no` filter and returns the procedure's cursor columns and rows.
- `POST /api/refinance/batch-details` calls `PKG_MGBL_REFINANCE.GET_DETAILS_BY_BATCH` with an optional `batch_no` filter and returns the procedure's cursor columns and rows.

Snapshots are held in process memory for up to one hour. Reloading records creates a new snapshot and the dashboard resets the selection. Only bind the service to localhost unless appropriate authentication and network controls are added.

The Oracle `GENERATE_BATCH_NUMBER` procedure uses `NVARCHAR2` for both optional inputs and the output. The application commits after a non-empty output is returned and rolls back if the output is missing or the call fails. The current procedure implementation derives the number using `MAX(batch_id) + 1`; confirm the database prevents collisions from concurrent calls before enabling this write in production.

The current `GET_UPAPPROVED_BATCH` signature uses `NVARCHAR2` for `pbatch_no` and `SYS_REFCURSOR` for its output. Its current package-body query groups rows from `MGBL_REFINANCE_MASTER` and does not include an explicit approval-status predicate; verify that this database procedure returns only the batches intended for the Pending Batches view.

The current `GET_DETAILS_BY_BATCH` signature uses `NVARCHAR2` for `Pbatch_no` and `SYS_REFCURSOR` for `Presult_set_cur`. The detail table displays the actual columns returned by that cursor.

The installed `ULTIMUS.PKG_MGBL_REFINANCE` package body is available in the configured Oracle database, not as a checked-in SQL file. Its `REFINANCE_MASTER_INFO_I` procedure generates a batch before parsing/inserting rows, but passes the hard-coded total `'1'` to `GENERATE_BATCH_NUMBER`; it only updates `TOTAL_LOAN_NO` to the actual count after inserts. The batch-before-insert order is present, but the generated batch reference may use an incorrect total. The `MGBL_REFINANCE_MASTER` insert uses the column/value order listed in the submission workflow. To avoid `ORA-01861` under differing Oracle NLS date formats, the installed package body was updated to read the four XML date fields as strings and explicitly convert `YYYY-MM-DD` with `TO_DATE`; the body was verified `VALID` after compilation. `GET_REFINANCE_DETAILS` was also updated to return branch ID, account number, an Oracle DATE for open/disbursement dates, and the latest account-level `FINAL_CL_STATUS` from `LOAN_MASTER_DATA`. Python XML mapping recognizes the source query's `ENTERPRISE_NAME`, `BORROWER_FULL_NAME`, `ESTABLISHED_OWNERSHIP_STRUCTURE`, and `SANCTION_AMOUNT` aliases. The API validates values required by `MGBL_REFINANCE_MASTER` before calling the insert procedure. The generator uses `MAX(TO_NUMBER(batch_id)) + 1` and has no visible concurrency serialization, so concurrent calls may contend or generate a duplicate. The procedure does not issue a commit, and its exception handler sets `Pmessage` then re-raises. The API commits only when `PBatch_NO` is present and the returned success message confirms the selected record count; otherwise it rolls back. Confirmed rollback errors release the selected IDs for retry; commit failures remain locked until the batch status is verified. Oracle submission errors return the ORA error code in the API response; full Oracle details remain in the application log. The master table audit columns are `NOT NULL`, so blank optional maker/authorizer values are passed through as `NULL` and may be rejected by Oracle. The package assigns `BB_APPROVAL_STATUS = 1`; confirm its meaning and maker-checker implications with the database owner. A package-body correction is still needed to count XML records before calling the generator and pass the actual total. Verify batch-number concurrency and maker-checker rules before enabling submissions.

Run tests from the workspace root with `pytest -q refinance_app/tests`.