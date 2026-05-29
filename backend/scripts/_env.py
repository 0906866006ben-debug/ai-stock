"""Shared .env loading for standalone data-fetch scripts.

`python -m backend.scripts...` does not go through the FastAPI import path that
loads backend/.env, so any script that fetches external data (FinMind, etc.)
must load it explicitly. Centralized here so every fetch script behaves the same
and picks up FINMIND_API_KEY / other keys from backend/.env.
"""
from __future__ import annotations

from pathlib import Path


def load_backend_env() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    backend_dir = Path(__file__).resolve().parent.parent
    for env_path in (backend_dir / ".env", backend_dir.parent / ".env"):
        if env_path.exists():
            load_dotenv(env_path)
