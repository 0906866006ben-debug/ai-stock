"""Sector classification service — 6-Layer AI Industry Framework lookup."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional


_DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "sectors" / "ai_tech_tw.json"


@lru_cache(maxsize=1)
def _load_ai_tech_framework() -> dict[str, Any]:
    if not _DATA_PATH.exists():
        return {"categories": {}}
    with _DATA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _build_code_index() -> dict[str, dict[str, str]]:
    """{ '3661': {'category': 'cat_1_silicon_ip', 'label': 'IC設計/IP', 'name': '世芯-KY'} }"""
    framework = _load_ai_tech_framework()
    idx: dict[str, dict[str, str]] = {}
    for cat_key, cat in framework.get("categories", {}).items():
        label = cat.get("label", cat_key)
        for stock in cat.get("stocks", []):
            code = str(stock.get("code", "")).strip()
            if code:
                idx[code] = {
                    "category": cat_key,
                    "label": label,
                    "name": stock.get("name", ""),
                }
    return idx


def is_ai_tech_stock(stock_id: str) -> bool:
    return stock_id.strip() in _build_code_index()


def get_sector_info(stock_id: str) -> Optional[dict[str, str]]:
    return _build_code_index().get(stock_id.strip())


def get_sector_category(stock_id: str) -> Optional[str]:
    info = get_sector_info(stock_id)
    return info["category"] if info else None


def get_sector_label(stock_id: str) -> Optional[str]:
    info = get_sector_info(stock_id)
    return info["label"] if info else None


def list_ai_tech_codes() -> set[str]:
    return set(_build_code_index().keys())


def list_codes_by_category(category_key: str) -> set[str]:
    """Return stock codes belonging to one AI tech category (e.g. 'cat_3_packaging')."""
    return {
        code for code, info in _build_code_index().items()
        if info.get("category") == category_key
    }


def list_categories() -> dict[str, dict[str, Any]]:
    """Returns full categories dict for UI rendering."""
    return _load_ai_tech_framework().get("categories", {})


def _reset_caches() -> None:
    """Test helper — clear caches so a modified JSON is re-read."""
    _load_ai_tech_framework.cache_clear()
    _build_code_index.cache_clear()
