# 상품 소싱 가격비교 웹앱 (MVP-1)

구현 계획서(`online_product_sourcing_margin_webapp_implementation_plan.md`)의 **MVP-1** 범위 중
검색 · 사이트별 수집기(스크래핑/공식 API) · 배송비 엔진 · 실질가격 TOP 20 · 시장가격 통계 · 실시간(SSE) 표시를 구현했습니다.

## 실행 (Windows, 내 PC)

준비물: Python 3.10 이상, Node.js 20 이상

1. `run_backend.bat` 실행 → http://localhost:8000/docs 에서 API 확인
2. `run_frontend.bat` 실행 → 브라우저에서 http://localhost:5173 접속

기본값은 **스크래핑 모드**(`CONNECTOR_MODE=scrape`)입니다. 가상 데이터로 화면만 보려면
`backend/.env.local` 에서 `DEMO_MODE=1` 로 바꾸세요.

### 스크래핑 진단 (처음 한 번 꼭 실행)

```
cd backend
.venv\Scripts\python -m app.tools.probe "삼성 USB-C 케이블"
```

사이트별 성공/실패와 첫 상품을 출력하고, 받은 HTML을 `backend/probe/` 에 저장합니다.
실패한 사이트는 이 HTML로 선택자를 보정합니다.

## 사이트별 수집 방식

| 사이트 | 구분 | 기본(스크래핑) | 예상 위험 |
|---|---|---|---|
| 쿠팡 | 소매 | 검색 페이지 HTML 카드 | 자동요청 차단 매우 강함 (특히 클라우드 서버 IP) |
| 네이버쇼핑 | 소매 | 검색 페이지 `__NEXT_DATA__` JSON | 자동요청 제한 강함 (캡차/418) |
| G마켓 | 소매 | 검색 페이지 HTML 카드 | 보통 |
| 11번가 | 소매 | 검색 페이지 HTML 카드 | 보통 |
| 도매꾹 / 도매매 | 도매 | 상품목록 HTML | 일부 가격 회원 전용 |
| 오너클랜 | 도매 | 검색 페이지 HTML | 공급가 회원 전용일 가능성 높음 |

- 각 사이트 검색 페이지를 **1회만** 요청하고, 같은 사이트 요청 사이 최소 3초 간격, 30분 캐시를 둡니다.
- 차단·캡차·로그인 요구가 감지되면 **우회하지 않고** "접근 제한/인증 필요"로 표시하고 "직접 확인" 링크를 줍니다.
  (IP 우회, 캡차 풀이, 봇 탐지 회피 기능은 넣지 않았습니다 — 계획서 38절)
- 공식 API 코드도 남아 있어 `CONNECTOR_MODE=api` 또는 `auto` 로 전환할 수 있습니다.

## 배포

### 권장: Render 하나로 배포 (프런트+백엔드 한 서비스, 무료 플랜 가능)
1. GitHub에 새 저장소를 만들고 이 폴더(`price-sourcing-app`) 내용을 올립니다.
2. https://render.com 가입 → New → **Blueprint** → 저장소 선택 → `render.yaml` 자동 인식 → Apply
3. 몇 분 뒤 `https://price-sourcing-app-xxxx.onrender.com` 주소로 접속합니다.
   (무료 플랜은 15분 미사용 시 잠들었다가 첫 접속 때 30초~1분 깨어나는 시간이 있습니다)

### 선택: Vercel(프런트) + Render(백엔드)
- Render는 위와 같이 배포 → 주소 확인
- Vercel → Add New Project → 같은 저장소, **Root Directory = `frontend`**,
  Environment Variable `VITE_API_BASE = https://<render 주소>` → Deploy
- Render 환경변수 `CORS_ORIGINS` 에 Vercel 주소를 넣습니다.

### Supabase (로그인 + 검색·가격 이력 저장)
1. Supabase 대시보드 → SQL Editor 에서 `supabase/migrations/20261109000000_init.sql` 실행
   (GitHub 연동으로 마이그레이션 자동 적용을 켰다면 생략)
2. Authentication → Users → **Add user** 로 관리자 계정 생성 (이메일/비밀번호).
   Authentication → Sign In / Providers 에서 **Allow new users to sign up** 은 끄는 것을 권장
3. Project Settings → API 에서 `Project URL`, `anon public` 키, `service_role` 키 확인
4. Render 서비스 → Environment 에 `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` 입력
   (`REQUIRE_AUTH=1` 은 render.yaml 에 이미 설정)

설정하면 로그인 화면이 나타나고, 검색할 때마다 `searches`, `price_history` 테이블에 기록되며
화면 상단에 "최근 검색"이 표시됩니다. 설정하지 않으면 로그인 없이 동작합니다.

### 클라우드 배포 시 주의
쿠팡·네이버는 데이터센터(클라우드) IP의 자동 요청을 대부분 차단합니다. 배포된 서버에서는
이 두 사이트가 "접근 제한"으로 표시될 가능성이 높고, 내 PC에서 실행할 때 더 잘 동작합니다.

## 계산 규칙

- 소매 실질가격 = 상품가격 + 배송비 (1개 구매 기준). 오름차순 상위 20개.
- 도매 실질원가 = 상품가격 × max(입력 수량, MOQ) + 배송비 (금액/수량 무료조건, N개마다 부과 반영).
- 배송비 미확인 상품은 상품가격으로 정렬하되 가격 신뢰도를 30점 낮춥니다.
- 매칭점수(규칙 기반): 검색어 단어 일치율, 모델번호 일치/불일치, 부속품 단어(케이스·필름 등), 구성수량.

## 구조

```
backend/app/
  main.py            FastAPI (/api/sources, /api/search, /api/search/stream[SSE])
  orchestrator.py    병렬 검색 · 사이트별 장애 격리 · TTL 캐시
  shipping.py        배송조건 텍스트 → 구조화 (규칙 기반)
  matching.py        검색어 확장 · 매칭점수 · 가격 신뢰도
  ranking.py         중복 제거 · 최저가 정렬 · 시장가격 통계
  connectors/        사이트별 수집기: scrapers.py(스크래핑), naver/coupang/... (공식 API)
  tools/probe.py     스크래핑 진단 도구
  supabase_store.py  Supabase 인증 확인 · 검색/가격 이력 저장
supabase/migrations/ DB 스키마 (searches, price_history)
backend/tests/       pytest 39개 (배송비·최저가·매칭·장애·API/스크래핑 파싱·차단 감지·인증/이력)
frontend/src/App.jsx 검색 · 사이트 ON/OFF · 진행상태 · TOP 20 표 · CSV 다운로드
```

## 다음 단계 (계획서 MVP-1 잔여 → MVP-2)

1. probe 결과로 사이트별 선택자 보정 (실제 페이지 기준)
2. AI Provider(검색어 확장 · 동일상품 매칭 · 복잡한 배송조건 구조화)
3. 플랫폼 수수료 설정 · 예상 순마진 · 마진율 · ROI
