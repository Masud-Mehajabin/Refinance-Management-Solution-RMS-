# Refinance Management

FastAPI application for retrieving branch refinance data, exporting Excel, previewing XML, and submitting a batch through the existing Oracle procedures.

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
- Batch writes remain disabled unless `ALLOW_BATCH_SUBMISSION=true` and separate `APPROVER_USERNAME` / `APPROVER_PASSWORD` values are configured.
- The current Oracle procedure interface accepts maker and authorizer values, but this app's separate approver credential check is not a replacement for the bank's identity provider, authorization policy, or audit trail. Keep batch submission disabled until those requirements have been approved and tested.
- The dashboard/API have no login and must remain bound to localhost unless proper network authentication and HTTPS are added. Do not expose the development server directly to a network.

The Oracle password shared in the setup request should be rotated before use. Configure the replacement only in the ignored local `.env` file or in the deployment secret manager; do not commit it.

## API

- `GET /health` is an unauthenticated process health check.
- `GET /api/health/database` tests Oracle connectivity.
- `GET /api/refinance?branch_id=...` retrieves records and mapping status; omit the filter to retrieve all branches. The response includes an opaque snapshot ID and stable record IDs.
- `POST /api/refinance/selected/excel` exports only the submitted record IDs from that snapshot.
- `POST /api/refinance/selected/xml` previews XML built only from the selected snapshot rows.
- `POST /api/refinance/selected/submit` submits only those selected rows and requires enabled write configuration, separate approver credentials, and explicit confirmation.

Snapshots are held in process memory for up to one hour. Reloading records creates a new snapshot and the dashboard resets the selection. Only bind the service to localhost unless appropriate authentication and network controls are added.

Run tests from the workspace root with `pytest -q refinance_app/tests`.