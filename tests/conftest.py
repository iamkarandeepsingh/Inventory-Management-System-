"""Pytest configuration — isolated DB + JWT secret before any app import."""

from __future__ import annotations

import atexit
import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "inv-pytest-jwt-secret-key-at-least-32-chars!!")

_fd, _pytest_duckdb = tempfile.mkstemp(prefix="inv_pytest_", suffix=".duckdb")
os.close(_fd)
try:
    os.unlink(_pytest_duckdb)
except OSError:
    pass
os.environ["DUCKDB_PATH"] = _pytest_duckdb


def _cleanup_duckdb() -> None:
    try:
        if os.path.isfile(_pytest_duckdb):
            os.unlink(_pytest_duckdb)
    except OSError:
        pass


atexit.register(_cleanup_duckdb)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def client() -> TestClient:
    import main

    with TestClient(main.app) as c:
        yield c
