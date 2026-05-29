"""Shared user-facing language guardrails for CANSLIM screening surfaces."""
from __future__ import annotations

import re
from typing import Any, Iterable

FORBIDDEN_TERMS = re.compile(
    r"\b(buy|sell|hold|target[\s_-]*price|price[\s_-]*target|guaranteed|will rise)\b"
    r"|買|賣|持有|進場|出場|上車|下車|目標價|目標價格|保證|必漲",
    re.IGNORECASE,
)


def clean_user_facing_text(value: str) -> str:
    english_replacements = {
        "buy": "watchlist",
        "sell": "exit-pressure",
        "hold": "carry",
        "target price": "valuation reference",
        "price target": "valuation reference",
        "will rise": "positive setup",
        "guaranteed": "high-certainty wording",
    }
    cjk_replacements = {
        "買": "觀察",
        "賣": "壓力",
        "持有": "續留",
        "進場": "條件觀察",
        "出場": "風險觀察",
        "上車": "條件觀察",
        "下車": "風險觀察",
        "目標價": "估值參考",
        "目標價格": "估值參考",
        "保證": "高確定性字眼",
        "必漲": "正向型態",
    }
    text = str(value)
    for old, new in english_replacements.items():
        text = re.sub(rf"\b{re.escape(old)}\b", new, text, flags=re.IGNORECASE)
    for old, new in cjk_replacements.items():
        text = re.sub(re.escape(old), new, text, flags=re.IGNORECASE)
    return text


def clean_string_list(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        safe = clean_user_facing_text(str(value))
        if safe and safe not in seen:
            seen.add(safe)
            out.append(safe)
    return out


def contains_forbidden_action_language(value: Any) -> bool:
    if isinstance(value, str):
        return bool(FORBIDDEN_TERMS.search(value))
    if isinstance(value, dict):
        return any(contains_forbidden_action_language(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(contains_forbidden_action_language(item) for item in value)
    return False
