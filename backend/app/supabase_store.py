"""Supabase 연동 (선택 사항).

환경변수
  SUPABASE_URL               예: https://xxxx.supabase.co
  SUPABASE_ANON_KEY          프런트엔드 로그인용 공개 키 (/api/config 로 전달)
  SUPABASE_SERVICE_ROLE_KEY  백엔드 전용 비밀 키 (검색·가격 이력 저장). 절대 프런트엔드에 노출하지 않는다.
  REQUIRE_AUTH=1             로그인한 사용자만 검색 가능 (계획서 2.1, 37절)

설정이 없으면 저장/인증 없이 동작한다.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

log = logging.getLogger("supabase")


def url() -> str:
    return os.getenv("SUPABASE_URL", "").rstrip("/")


def anon_key() -> str:
    return os.getenv("SUPABASE_ANON_KEY", "")


def service_key() -> str:
    return os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


def auth_enabled() -> bool:
    return bool(url() and anon_key()) and os.getenv("REQUIRE_AUTH", "0").lower() in ("1", "true", "yes", "on")


def storage_enabled() -> bool:
    return bool(url() and service_key())


async def verify_user(token: Optional[str]) -> Optional[dict]:
    """Supabase Auth 에 토큰을 확인하고 사용자 정보를 돌려준다. 실패하면 None."""
    if not token:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{url()}/auth/v1/user", headers={"apikey": anon_key(), "Authorization": f"Bearer {token}"})
        return r.json() if r.status_code == 200 else None
    except httpx.HTTPError:
        log.exception("supabase auth check failed")
        return None


async def save_search(result: dict, *, user_id: Optional[str], sources: list[str], quantity: int) -> None:
    """검색 결과와 TOP 가격을 저장한다. 실패해도 검색 응답에는 영향을 주지 않는다."""
    if not storage_enabled():
        return
    headers = {
        "apikey": service_key(),
        "Authorization": f"Bearer {service_key()}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    sites = result.get("sites", [])
    search_row = {
        "user_id": user_id,
        "query": result["query"],
        "expanded_queries": result.get("expanded_queries", []),
        "selected_sources": sources,
        "quantity": quantity,
        "search_started_at": result["started_at"],
        "search_completed_at": result["completed_at"],
        "result_count": len(result.get("retail_top", [])) + len(result.get("wholesale_top", [])),
        "error_sources": [
            {"source": s["source"], "status": s["status"], "message": s.get("message", "")}
            for s in sites
            if s["status"] != "SEARCH_SUCCESS"
        ],
        "retail_stats": result.get("retail_stats"),
        "wholesale_stats": result.get("wholesale_stats"),
    }
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{url()}/rest/v1/searches", headers=headers, json=search_row)
            r.raise_for_status()
            search_id = r.json()[0]["id"]
            rows = []
            for kind_key in ("retail_top", "wholesale_top"):
                for p in result.get(kind_key, []):
                    rows.append(
                        {
                            "search_id": search_id,
                            "query": result["query"],
                            "kind": p["kind"],
                            "source": p["source"],
                            "external_id": p.get("external_id") or None,
                            "product_name": p["name"],
                            "product_url": p["url"],
                            "seller": p.get("seller") or None,
                            "rank": p.get("rank"),
                            "price": p["price"],
                            "shipping_fee": p.get("shipping_fee"),
                            "shipping_fee_known": p["shipping"]["fee_known"],
                            "shipping_condition": p.get("shipping_condition"),
                            "min_order_quantity": p.get("min_order_quantity", 1),
                            "effective_price": p["effective_price"],
                            "match_score": p.get("match_score"),
                            "price_confidence": p.get("price_confidence"),
                            "captured_at": p.get("checked_at"),
                        }
                    )
            if rows:
                headers["Prefer"] = "return=minimal"
                r = await c.post(f"{url()}/rest/v1/price_history", headers=headers, json=rows)
                r.raise_for_status()
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        log.exception("failed to save search to supabase")


async def recent_searches(limit: int = 20) -> list[dict]:
    if not storage_enabled():
        return []
    headers = {"apikey": service_key(), "Authorization": f"Bearer {service_key()}"}
    params = {"select": "id,query,created_at,result_count,retail_stats,wholesale_stats", "order": "created_at.desc", "limit": str(limit)}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{url()}/rest/v1/searches", headers=headers, params=params)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError:
        log.exception("failed to load recent searches")
        return []
