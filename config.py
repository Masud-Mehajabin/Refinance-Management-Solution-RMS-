"""
Configuration module for the Refinance Management application.

Loads environment variables from a .env file and provides validated
configuration values. Database credentials are never logged or displayed.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root (refinance_app directory)
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_env_path)

# ---------------------------------------------------------------------------
# Logging — configured early so every other module inherits the level.
# ---------------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("refinance_app")

# ---------------------------------------------------------------------------
# Oracle Database
# ---------------------------------------------------------------------------
ORACLE_USER: str = os.getenv("ORACLE_USER", "")
ORACLE_PASSWORD: str = os.getenv("ORACLE_PASSWORD", "")
ORACLE_DSN: str = os.getenv("ORACLE_DSN", "")

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
APP_USER: str = os.getenv("APP_USER", "SYSTEM")
APP_ENV: str = os.getenv("APP_ENV", "development")
ALLOW_BATCH_SUBMISSION: bool = os.getenv("ALLOW_BATCH_SUBMISSION", "false").lower() == "true"


def validate_db_config() -> list[str]:
    """Return a list of missing-but-required database configuration keys."""
    missing: list[str] = []
    if not ORACLE_USER:
        missing.append("ORACLE_USER")
    if not ORACLE_PASSWORD:
        missing.append("ORACLE_PASSWORD")
    if not ORACLE_DSN:
        missing.append("ORACLE_DSN")
    return missing
