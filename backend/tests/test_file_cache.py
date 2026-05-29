from __future__ import annotations

from backend.app.services import file_cache


def test_save_load_roundtrip():
    file_cache.clear("unit_ns")
    assert file_cache.load("unit_ns", "k1") is None
    file_cache.save("unit_ns", "k1", {"a": 1, "title": "新訂單放量"})
    assert file_cache.load("unit_ns", "k1") == {"a": 1, "title": "新訂單放量"}


def test_clear_namespace_removes_entries():
    file_cache.save("unit_ns2", "k", {"x": 1})
    assert file_cache.load("unit_ns2", "k") == {"x": 1}
    file_cache.clear("unit_ns2")
    assert file_cache.load("unit_ns2", "k") is None


def test_key_with_unsafe_chars_is_sanitized():
    file_cache.clear("unit_ns3")
    file_cache.save("unit_ns3", "2330/2026-05-24", {"ok": True})
    assert file_cache.load("unit_ns3", "2330/2026-05-24") == {"ok": True}
