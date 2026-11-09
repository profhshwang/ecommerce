"""사이트 장애 격리 테스트 (TC-01, TC-02)."""
import asyncio

from app.connectors.base import ConnectorError, ShoppingConnector
from app.models import Product, SearchRequest, SearchStatus, ShippingRule, SourceKind
from app.orchestrator import SearchOrchestrator


class Ok(ShoppingConnector):
    id, name, kind = "ok", "정상몰", SourceKind.RETAIL

    async def search(self, query, client):
        return [Product(source=self.id, source_name=self.name, kind=self.kind, name=query, url="https://ok/1",
                        external_id="1", price=1000, shipping=ShippingRule(shipping_fee=2500))]


class Broken(ShoppingConnector):
    id, name, kind = "broken", "장애몰", SourceKind.RETAIL

    async def search(self, query, client):
        raise ConnectorError(SearchStatus.BLOCKED, "blocked")


class Crashing(ShoppingConnector):
    id, name, kind = "crash", "버그몰", SourceKind.WHOLESALE

    async def search(self, query, client):
        raise KeyError("unexpected field")


class Slow(ShoppingConnector):
    id, name, kind = "slow", "느린몰", SourceKind.RETAIL

    async def search(self, query, client):
        await asyncio.sleep(5)
        return []


class NeedsKey(ShoppingConnector):
    id, name, kind = "nokey", "키없음", SourceKind.RETAIL
    required_env = ("SURELY_NOT_SET_ENV_123",)


async def test_one_site_failure_does_not_break_search():
    orch = SearchOrchestrator({c.id: c() for c in (Ok, Broken, Crashing, Slow, NeedsKey)})
    orch.site_timeout = 0.2
    res = await orch.run(SearchRequest(query="텀블러", expand=False))
    st = {s.source: s.status for s in res.sites}
    assert st == {
        "ok": SearchStatus.SEARCH_SUCCESS,
        "broken": SearchStatus.BLOCKED,
        "crash": SearchStatus.PARSER_ERROR,
        "slow": SearchStatus.SEARCH_TIMEOUT,
        "nokey": SearchStatus.UNAVAILABLE,
    }
    assert len(res.retail_top) == 1 and res.retail_top[0].effective_price == 3500


async def test_stream_emits_site_events_then_result():
    orch = SearchOrchestrator({c.id: c() for c in (Ok, Broken)})
    types = [ev["type"] async for ev in orch.stream(SearchRequest(query="텀블러", expand=False))]
    assert types[0] == "start" and types[-1] == "result" and types.count("site") == 2


async def test_cache_hit_second_time():
    orch = SearchOrchestrator({"ok": Ok()})
    await orch.run(SearchRequest(query="텀블러", expand=False))
    res = await orch.run(SearchRequest(query="텀블러", expand=False))
    assert res.sites[0].from_cache
