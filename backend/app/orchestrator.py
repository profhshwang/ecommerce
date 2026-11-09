"""검색 오케스트레이터 (계획서 6, 39, 40, 41절).

- 사이트별 병렬 검색, 결과 도착 즉시 이벤트 전송 (SSE)
- 사이트별 독립 장애 처리: 한 사이트 실패가 전체를 멈추지 않음 (TC-02)
- 메모리 TTL 캐시 (사이트+검색어 단위)
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import AsyncIterator

import httpx

from .connectors import ConnectorError, ShoppingConnector, build_connectors
from .matching import expand_query
from .models import (
    Product,
    SearchRequest,
    SearchResponse,
    SearchStatus,
    SiteResult,
    SourceKind,
    now_utc,
)
from .ranking import dedupe, market_stats, score_and_rank

log = logging.getLogger("search")

USER_MESSAGES = {
    SearchStatus.SEARCH_TIMEOUT: "응답 시간이 초과되었습니다.",
    SearchStatus.API_LIMIT: "API 요청 한도를 초과했습니다. 잠시 후 다시 시도하세요.",
    SearchStatus.AUTH_REQUIRED: "API 인증이 필요하거나 실패했습니다.",
    SearchStatus.BLOCKED: "사이트에서 접근을 제한했습니다.",
    SearchStatus.PARSER_ERROR: "검색 결과를 해석하지 못했습니다.",
    SearchStatus.UNAVAILABLE: "현재 검색 결과를 가져오지 못했습니다.",
}


class TTLCache:
    def __init__(self, ttl_sec: int):
        self.ttl = ttl_sec
        self._data: dict[tuple, tuple[float, list[Product]]] = {}

    def get(self, key: tuple) -> list[Product] | None:
        hit = self._data.get(key)
        if hit and time.monotonic() - hit[0] < self.ttl:
            return [p.model_copy(deep=True) for p in hit[1]]
        return None

    def set(self, key: tuple, value: list[Product]) -> None:
        self._data[key] = (time.monotonic(), [p.model_copy(deep=True) for p in value])


class SearchOrchestrator:
    def __init__(self, connectors: dict[str, ShoppingConnector] | None = None):
        self.connectors = connectors if connectors is not None else build_connectors()
        self.cache = TTLCache(int(os.getenv("CACHE_TTL_SEC", "1800")))
        self.site_timeout = float(os.getenv("SITE_TIMEOUT_SEC", "25"))

    def sources_info(self) -> list[dict]:
        info = []
        for c in self.connectors.values():
            info.append(
                {
                    "id": c.id,
                    "name": c.name,
                    "kind": c.kind.value,
                    "configured": c.is_configured(),
                    "note": c.note,
                    "reason": "" if c.is_configured() else (c.unavailable_reason() or c.note),
                }
            )
        return info

    async def _search_site(
        self, c: ShoppingConnector, queries: list[str], client: httpx.AsyncClient
    ) -> tuple[SiteResult, list[Product]]:
        started = time.monotonic()
        res = SiteResult(
            source=c.id,
            source_name=c.name,
            kind=c.kind,
            status=SearchStatus.PENDING,
            manual_url=c.manual_url(queries[0]) if queries else "",
        )
        if not c.is_configured():
            res.status = SearchStatus.UNAVAILABLE
            res.message = c.unavailable_reason() or c.note
            return res, []
        products: list[Product] = []
        errors: list[ConnectorError] = []
        all_cached = True
        for q in queries[: max(1, c.max_queries)]:
            key = (c.id, q)
            cached = self.cache.get(key)
            if cached is not None:
                products.extend(cached)
                continue
            all_cached = False
            try:
                found = await asyncio.wait_for(c.search(q, client), timeout=self.site_timeout)
                self.cache.set(key, found)
                products.extend(found)
            except asyncio.TimeoutError:
                errors.append(ConnectorError(SearchStatus.SEARCH_TIMEOUT))
            except ConnectorError as e:
                errors.append(e)
            except httpx.HTTPError as e:
                errors.append(ConnectorError(SearchStatus.UNAVAILABLE, f"{type(e).__name__}: {e}"))
            except Exception as e:  # 파서 버그 등도 사이트 단위로 격리
                log.exception("connector %s failed", c.id)
                errors.append(ConnectorError(SearchStatus.PARSER_ERROR, f"{type(e).__name__}: {e}"))
            if errors and errors[-1].status in (SearchStatus.AUTH_REQUIRED, SearchStatus.API_LIMIT):
                break  # 같은 오류가 반복될 확장 검색어는 건너뜀
        res.elapsed_sec = round(time.monotonic() - started, 2)
        res.from_cache = all_cached and bool(products)
        if products:
            res.status = SearchStatus.SEARCH_SUCCESS
            res.count = len(products)
            if errors:
                res.message = f"일부 검색어 실패: {errors[0].status.value}"
        elif errors:
            res.status = errors[0].status
            res.message = USER_MESSAGES.get(errors[0].status, "")
            log.warning("site %s failed: %s", c.id, [str(e) for e in errors])  # 관리자용 상세 로그
        else:
            res.status = SearchStatus.SEARCH_SUCCESS
        return res, products

    async def stream(self, req: SearchRequest) -> AsyncIterator[dict]:
        """이벤트를 차례로 yield 한다: start → site(n회) → result."""
        started_at = now_utc()
        queries = expand_query(req.query) if req.expand else [req.query.strip()]
        selected = [s for s in (req.sources or self.connectors.keys()) if s in self.connectors]
        yield {
            "type": "start",
            "query": req.query,
            "expanded_queries": queries,
            "sources": [{"id": s, "name": self.connectors[s].name} for s in selected],
        }

        all_products: list[Product] = []
        sites: list[SiteResult] = []
        async with httpx.AsyncClient(follow_redirects=True, headers={"User-Agent": "price-sourcing-app/0.1"}) as client:
            tasks = [asyncio.create_task(self._search_site(self.connectors[s], queries, client)) for s in selected]
            for fut in asyncio.as_completed(tasks):
                site_res, products = await fut
                sites.append(site_res)
                all_products.extend(products)
                yield {"type": "site", "site": site_res.model_dump(mode="json")}

        products = dedupe(all_products)
        retail = [p for p in products if p.kind == SourceKind.RETAIL]
        wholesale = [p for p in products if p.kind == SourceKind.WHOLESALE]
        retail_top, retail_all = score_and_rank(
            req.query, retail, quantity=1, min_match_score=req.min_match_score, top_n=req.top_n
        )
        wholesale_top, wholesale_all = score_and_rank(
            req.query, wholesale, quantity=req.quantity, min_match_score=req.min_match_score, top_n=req.top_n
        )
        order = {s: i for i, s in enumerate(selected)}
        sites.sort(key=lambda r: order.get(r.source, 99))
        resp = SearchResponse(
            query=req.query,
            expanded_queries=queries,
            sites=sites,
            retail_top=retail_top,
            wholesale_top=wholesale_top,
            retail_stats=market_stats(retail_all),
            wholesale_stats=market_stats(wholesale_all),
            started_at=started_at,
            completed_at=now_utc(),
        )
        yield {"type": "result", "result": resp.model_dump(mode="json", exclude={"retail_top": {"__all__": {"raw"}}, "wholesale_top": {"__all__": {"raw"}}})}

    async def run(self, req: SearchRequest) -> SearchResponse:
        result = None
        async for ev in self.stream(req):
            if ev["type"] == "result":
                result = ev["result"]
        return SearchResponse.model_validate(result)
