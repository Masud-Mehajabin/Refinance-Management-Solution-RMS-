"""
Oracle Database connectivity module.

Provides a reusable connection factory, connection testing, and context-managed
connections. All credentials are sourced from config.py (never hardcoded).
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

import oracledb

from config import ORACLE_USER, ORACLE_PASSWORD, ORACLE_DSN, validate_db_config

logger = logging.getLogger("refinance_app.database")


class DatabaseError(Exception):
    """Application-level wrapper for database connectivity problems."""


def _get_connection_params() -> dict:
    """Build connection keyword arguments from environment config."""
    missing = validate_db_config()
    if missing:
        raise DatabaseError(
            f"Database configuration incomplete. Missing: {', '.join(missing)}. "
            "Please set the required environment variables in your .env file."
        )
    return {
        "user": ORACLE_USER,
        "password": ORACLE_PASSWORD,
        "dsn": ORACLE_DSN,
    }


def get_connection() -> oracledb.Connection:
    """
    Create and return a new Oracle database connection.

    Raises DatabaseError with a user-safe message on failure.
    """
    try:
        params = _get_connection_params()
        conn = oracledb.connect(**params)
        logger.info("Oracle connection established successfully.")
        return conn
    except DatabaseError:
        raise
    except oracledb.Error as exc:
        logger.error("Oracle connection failed: %s", exc, exc_info=True)
        if "ORA-01017" in str(exc):
            raise DatabaseError(
                "Oracle rejected the configured username or password (ORA-01017). "
                "Verify the credentials with your database administrator."
            ) from exc
        raise DatabaseError(
            "Unable to connect to the Oracle database. "
            "Please verify the database is available and your credentials are correct."
        ) from exc
    except Exception as exc:
        logger.error("Unexpected connection error: %s", exc, exc_info=True)
        raise DatabaseError(
            "An unexpected error occurred while connecting to the database."
        ) from exc


@contextmanager
def managed_connection() -> Generator[oracledb.Connection, None, None]:
    """Context manager that yields a connection and closes it on exit."""
    conn = get_connection()
    try:
        yield conn
    finally:
        try:
            conn.close()
            logger.debug("Oracle connection closed.")
        except oracledb.Error as exc:
            logger.warning("Error while closing connection: %s", exc)


def test_connection() -> tuple[bool, str]:
    """
    Test database connectivity.

    Returns (True, info_message) on success, (False, safe_error_message) on failure.
    """
    try:
        with managed_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT SYSDATE FROM DUAL")
                row = cur.fetchone()
                db_time = row[0] if row else "unknown"
        return True, f"Connected successfully. Database time: {db_time}"
    except DatabaseError as exc:
        return False, str(exc)
    except Exception as exc:
        logger.error("Connection test failed unexpectedly: %s", exc, exc_info=True)
        return False, "Connection test failed due to an unexpected error."
