"""Application configuration from environment."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

APP_VERSION = "1.0.0"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
DUCKDB_PATH = Path(os.getenv("DUCKDB_PATH", "./data/inventory.duckdb")).resolve()
DATA_DIR = DUCKDB_PATH.parent
EXCEL_PATH = DATA_DIR / "all_tables_combined.xlsx"

# KPI / rule engine versions (must match audit logs)
KPI_VERSION = "v2.1"
SQL_TEMPLATE_VERSION = "v1.0"
RULE_ENGINE_VERSION = "v1.0"

EPSILON = 0.001

VALID_SCOPES = frozenset(
    {
        "all",
        "DC-004",
        "DC-006",
        "Store-001",
        "Store-002",
        "Store-003",
        "Store-005",
    }
)

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# JWT auth (set JWT_SECRET in production)
JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-change-me-use-a-long-random-secret").strip()
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))

VALID_APP_ROLES = frozenset({"Analyst", "Supervisor", "Auditor", "Admin"})
