"""FastAPI 진입점.

실행:  uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import config  # noqa: F401  (.env.local 을 가장 먼저 읽는다)
from . import supabase_store as sb
from .connectors import connector_mode, demo_mode
from .models import SearchRequest, SearchResponse
from .orchestrator import SearchOrchestrator


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="상품 소싱·가격비교 API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator = SearchOrchestrator()


async def current_user(request: Request, token: Optional[str] = None) -> Optional[dict]:
    """REQUIRE_AUTH=1 이면 Supabase 로그인 토큰을 확인한다.

    EventSource(SSE)는 헤더를 보낼 수 없어 ?token= 쿼리도 허용한다.
    """
    if not sb.auth_enabled():
        return None
    auth = request.headers.get("authorization", "")
    tok = auth[7:] if auth.lower().startswith("bearer ") else token
    user = await sb.verify_user(tok)
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return user


@app.get("/api/config")
def public_config():
    """프런트엔드가 실행 시점에 읽는 공개 설정 (비밀 키는 포함하지 않는다)."""
    return {
        "auth_required": sb.auth_enabled(),
        "supabase_url": sb.url() if sb.auth_enabled() else "",
        "supabase_anon_key": sb.anon_key() if sb.auth_enabled() else "",
        "history_enabled": sb.storage_enabled(),
        "demo_mode": demo_mode(),
        "connector_mode": connector_mode(),
    }


@app.get("/api/history")
async def history(limit: int = 20, user: Optional[dict] = Depends(current_user)):
    return {"items": await sb.recent_searches(min(max(limit, 1), 100))}


@app.get("/api/health")
def health():
    return {"ok": True, "demo_mode": demo_mode(), "connector_mode": connector_mode()}


@app.get("/api/sources")
def sources(user: Optional[dict] = Depends(current_user)):
    return {"demo_mode": demo_mode(), "connector_mode": connector_mode(), "sources": orchestrator.sources_info()}


@app.post("/api/search", response_model=SearchResponse)
async def search(req: SearchRequest, user: Optional[dict] = Depends(current_user)):
    res = await orchestrator.run(req)
    await sb.save_search(
        res.model_dump(mode="json"), user_id=(user or {}).get("id"),
        sources=req.sources or list(orchestrator.connectors), quantity=req.quantity,
    )
    return res


@app.get("/api/search/stream")
async def search_stream(
    q: str = Query(min_length=1, max_length=100),
    sources: Optional[str] = None,
    top_n: int = 20,
    quantity: int = 1,
    expand: bool = True,
    min_match_score: int = 40,
    user: Optional[dict] = Depends(current_user),
):
    """Server-Sent Events: 사이트별 결과가 도착하는 즉시 전송 (계획서 6, 41절)."""
    req = SearchRequest(
        query=q,
        sources=[s for s in sources.split(",") if s] if sources else None,
        top_n=top_n,
        quantity=quantity,
        expand=expand,
        min_match_score=min_match_score,
    )

    async def gen():
        async for ev in orchestrator.stream(req):
            yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
            if ev["type"] == "result":
                await sb.save_search(
                    ev["result"], user_id=(user or {}).get("id"),
                    sources=req.sources or list(orchestrator.connectors), quantity=req.quantity,
                )
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# 프런트엔드 빌드(frontend/dist)가 있으면 같은 서버에서 제공한다 (단일 서비스 배포용).
_dist = Path(os.getenv("FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
if _dist.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
