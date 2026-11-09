"""API 인증·이력 저장 테스트 (Supabase 는 MockTransport 로 흉내)."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main, supabase_store as sb
from app.connectors.demo import DemoConnector
from app.connectors.scrapers import CoupangScraper


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main.orchestrator, "connectors", {"coupang": DemoConnector(CoupangScraper)})
    return TestClient(main.app)


def test_config_hides_service_key(client, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "SECRET")
    monkeypatch.setenv("REQUIRE_AUTH", "1")
    body = client.get("/api/config").json()
    assert body["auth_required"] and body["supabase_anon_key"] == "anon"
    assert "SECRET" not in json.dumps(body)


def test_auth_required_blocks_without_token(client, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("REQUIRE_AUTH", "1")

    async def fake_verify(tok):
        return {"id": "u1"} if tok == "good" else None

    monkeypatch.setattr(sb, "verify_user", fake_verify)
    assert client.get("/api/sources").status_code == 401
    assert client.get("/api/sources", headers={"Authorization": "Bearer good"}).status_code == 200
    assert client.post("/api/search", json={"query": "텀블러"}).status_code == 401


def test_search_saved_to_supabase(client, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "SECRET")
    monkeypatch.delenv("REQUIRE_AUTH", raising=False)
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.url.path, json.loads(req.content)))
        if req.url.path.endswith("/searches"):
            return httpx.Response(201, json=[{"id": "s1"}])
        return httpx.Response(201)

    real = httpx.AsyncClient
    monkeypatch.setattr(sb.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler)))
    r = client.post("/api/search", json={"query": "텀블러", "expand": False})
    assert r.status_code == 200
    paths = [p for p, _ in calls]
    assert paths == ["/rest/v1/searches", "/rest/v1/price_history"]
    rows = calls[1][1]
    assert rows and rows[0]["search_id"] == "s1" and "effective_price" in rows[0]
