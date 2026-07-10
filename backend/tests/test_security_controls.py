from fastapi.testclient import TestClient


def test_cors_allows_production_frontend_and_rejects_unknown_origin() -> None:
    from backend.app.main import app

    client = TestClient(app)
    allowed = client.options(
        "/health",
        headers={
            "Origin": "https://ai-stock-rosy-eight.vercel.app",
            "Access-Control-Request-Method": "GET",
        },
    )
    rejected = client.options(
        "/health",
        headers={
            "Origin": "https://example.invalid",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://ai-stock-rosy-eight.vercel.app"
    assert "access-control-allow-origin" not in rejected.headers


def test_telegram_watchlist_sync_requires_admin_secret(monkeypatch) -> None:
    import backend.app.main as main

    monkeypatch.setattr(main, "TELEGRAM_ADMIN_SECRET", "admin-test-secret")
    monkeypatch.setattr(main, "sync_watchlist", lambda **kwargs: {"status": "ok", "message": "updated"})
    client = TestClient(main.app)
    payload = {"action": "add", "stock_code": "2330", "stock_name": "TSMC"}

    assert client.post("/tw/telegram/watchlist/sync", json=payload).status_code == 401
    response = client.post(
        "/tw/telegram/watchlist/sync",
        json=payload,
        headers={"X-AI-Stock-Admin-Token": "admin-test-secret"},
    )

    assert response.status_code == 200


def test_telegram_webhook_is_closed_when_secret_is_missing(monkeypatch) -> None:
    import backend.app.main as main

    monkeypatch.setattr(main, "TELEGRAM_WEBHOOK_SECRET", "")
    client = TestClient(main.app)

    response = client.post("/tw/telegram/webhook", json={"update_id": 1})

    assert response.status_code == 503


def test_telegram_webhook_accepts_configured_secret(monkeypatch) -> None:
    import backend.app.main as main

    monkeypatch.setattr(main, "TELEGRAM_WEBHOOK_SECRET", "webhook-test-secret")
    monkeypatch.setattr(main, "handle_webhook", lambda body: None)
    client = TestClient(main.app)

    response = client.post(
        "/tw/telegram/webhook",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "webhook-test-secret"},
    )

    assert response.status_code == 200
