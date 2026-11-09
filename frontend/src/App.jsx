import { useEffect, useMemo, useRef, useState } from 'react'
import { createClient } from '@supabase/supabase-js'

const API = import.meta.env.VITE_API_BASE || ''
const won = (v) => (v === null || v === undefined ? '-' : `${Math.round(v).toLocaleString('ko-KR')}원`)
const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString('ko-KR', { hour12: false }) : '-')

const STATUS_LABEL = {
  PENDING: '검색 중',
  SEARCH_SUCCESS: '성공',
  SEARCH_TIMEOUT: '시간 초과',
  API_LIMIT: '요청 한도 초과',
  AUTH_REQUIRED: '인증 필요',
  BLOCKED: '접근 제한',
  PARSER_ERROR: '해석 오류',
  UNAVAILABLE: '사용 불가',
}

function SearchApp({ token, config, onSignOut, userEmail }) {
  const [sources, setSources] = useState([])
  const [demo, setDemo] = useState(false)
  const [selected, setSelected] = useState({})
  const [query, setQuery] = useState('')
  const [quantity, setQuantity] = useState(1)
  const [minMatch, setMinMatch] = useState(40)
  const [running, setRunning] = useState(false)
  const [sites, setSites] = useState({})
  const [expanded, setExpanded] = useState([])
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const esRef = useRef(null)
  const [historyTick, setHistoryTick] = useState(0)

  useEffect(() => {
    fetch(`${API}/api/sources`, { headers: authHeaders(token) })
      .then((r) => r.json())
      .then((d) => {
        setSources(d.sources)
        setDemo(d.demo_mode)
        setSelected(Object.fromEntries(d.sources.map((s) => [s.id, true])))
      })
      .catch(() => setError('백엔드(API)에 연결할 수 없습니다. 백엔드 서버가 실행 중인지 확인하세요.'))
  }, [])

  const startSearch = (e) => {
    e?.preventDefault()
    const q = query.trim()
    if (!q || running) return
    const ids = sources.filter((s) => selected[s.id]).map((s) => s.id)
    if (!ids.length) return setError('검색할 사이트를 하나 이상 선택하세요.')
    setError('')
    setResult(null)
    setExpanded([])
    setSites(Object.fromEntries(ids.map((id) => [id, { source: id, status: 'PENDING' }])))
    setRunning(true)
    esRef.current?.close()
    const params = new URLSearchParams({ q, sources: ids.join(','), quantity, min_match_score: minMatch })
    if (token) params.set('token', token)
    const es = new EventSource(`${API}/api/search/stream?${params}`)
    esRef.current = es
    es.addEventListener('start', (ev) => setExpanded(JSON.parse(ev.data).expanded_queries))
    es.addEventListener('site', (ev) => {
      const s = JSON.parse(ev.data).site
      setSites((prev) => ({ ...prev, [s.source]: s }))
    })
    es.addEventListener('result', (ev) => setResult(JSON.parse(ev.data).result))
    es.addEventListener('done', () => {
      es.close()
      setRunning(false)
      setHistoryTick((t) => t + 1)
    })
    es.onerror = () => {
      es.close()
      setRunning(false)
      setError('검색 중 연결이 끊어졌습니다.')
    }
  }

  const wholesaleSources = sources.filter((s) => s.kind === 'wholesale')
  const retailSources = sources.filter((s) => s.kind === 'retail')
  const nameOf = (id) => sources.find((s) => s.id === id)?.name || id

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-4 py-4 flex items-center gap-3">
          <h1 className="text-xl font-bold">상품 소싱 가격비교</h1>
          <span className="text-sm text-slate-500">도매 원가 · 국내 쇼핑몰 최저가 TOP 20</span>
          <div className="ml-auto flex items-center gap-3">
            {demo && (
              <span className="text-xs font-semibold bg-amber-100 text-amber-800 px-2 py-1 rounded">
                데모 모드: 가상 데이터 (실제 가격 아님)
              </span>
            )}
            {userEmail && (
              <>
                <span className="text-xs text-slate-500">{userEmail}</span>
                <button onClick={onSignOut} className="text-xs border border-slate-300 rounded px-2 py-1 hover:bg-slate-50">로그아웃</button>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-6 space-y-6">
        <form onSubmit={startSearch} className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 space-y-4">
          <div className="flex gap-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="상품명 또는 모델명 (예: 삼성 USB-C 고속충전 케이블 1m)"
              className="flex-1 border border-slate-300 rounded-lg px-4 py-3 text-base focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              disabled={running}
              className="px-6 rounded-lg bg-blue-600 text-white font-semibold hover:bg-blue-700 disabled:bg-slate-400"
            >
              {running ? '검색 중…' : '검색'}
            </button>
          </div>
          <SourceGroup title="도매" list={wholesaleSources} selected={selected} setSelected={setSelected} />
          <SourceGroup title="소매" list={retailSources} selected={selected} setSelected={setSelected} />
          <div className="flex flex-wrap gap-6 text-sm text-slate-600">
            <label className="flex items-center gap-2">
              도매 원가 계산 수량
              <input type="number" min={1} value={quantity} onChange={(e) => setQuantity(Math.max(1, +e.target.value || 1))}
                className="w-20 border border-slate-300 rounded px-2 py-1" />
              <span className="text-xs text-slate-400">(MOQ보다 작으면 MOQ 적용)</span>
            </label>
            <label className="flex items-center gap-2">
              최소 매칭점수
              <input type="range" min={0} max={100} step={5} value={minMatch} onChange={(e) => setMinMatch(+e.target.value)} />
              <span className="w-8 text-right">{minMatch}</span>
            </label>
          </div>
        </form>

        {config.history_enabled && (
          <History token={token} tick={historyTick} onPick={(q) => setQuery(q)} />
        )}

        {error && <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3">{error}</div>}

        {Object.keys(sites).length > 0 && (
          <SiteProgress sites={sites} nameOf={nameOf} expanded={expanded} />
        )}

        {result && (
          <>
            <StatsRow result={result} />
            <ResultTable
              title={`국내 쇼핑몰 최저가 TOP ${result.retail_top.length}`}
              subtitle="실질가격 = 상품가격 + 배송비(1개 구매 기준), 오름차순"
              rows={result.retail_top}
              query={result.query}
              filename="retail_top20"
            />
            <ResultTable
              title={`도매 실질원가 TOP ${result.wholesale_top.length}`}
              subtitle={`실질원가 = 상품가격 × max(${quantity}, MOQ) + 배송비(수량·금액 무료조건 반영)`}
              rows={result.wholesale_top}
              query={result.query}
              wholesale
              filename="wholesale_top20"
            />
          </>
        )}
      </main>
    </div>
  )
}

function SourceGroup({ title, list, selected, setSelected }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="w-10 text-sm font-semibold text-slate-500">{title}</span>
      {list.map((s) => (
        <label
          key={s.id}
          title={s.reason || s.note}
          className={`flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-full border cursor-pointer select-none ${
            selected[s.id] ? 'bg-blue-50 border-blue-300' : 'bg-white border-slate-300 text-slate-400'
          }`}
        >
          <input type="checkbox" checked={!!selected[s.id]} onChange={(e) => setSelected((p) => ({ ...p, [s.id]: e.target.checked }))} />
          {s.name}
          {!s.configured && <span className="text-[10px] text-amber-700 bg-amber-100 rounded px-1">미연결</span>}
        </label>
      ))}
    </div>
  )
}

function SiteProgress({ sites, nameOf, expanded }) {
  return (
    <section className="bg-white rounded-xl shadow-sm border border-slate-200 p-5">
      <div className="flex items-baseline gap-3 mb-3">
        <h2 className="font-semibold">사이트별 검색 상태</h2>
        {expanded.length > 0 && <span className="text-xs text-slate-500">검색어: {expanded.join(' · ')}</span>}
      </div>
      <ul className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2 text-sm">
        {Object.values(sites).map((s) => {
          const ok = s.status === 'SEARCH_SUCCESS'
          const pending = s.status === 'PENDING'
          return (
            <li key={s.source} className="border border-slate-200 rounded-lg px-3 py-2">
              <div className="flex items-center gap-2">
                <span className={pending ? 'animate-pulse text-blue-500' : ok ? 'text-green-600' : 'text-red-500'}>
                  {pending ? '●' : ok ? '✓' : '✕'}
                </span>
                <span className="font-medium">{nameOf(s.source)}</span>
                <span className="ml-auto text-xs text-slate-500">
                  {pending ? '검색 중' : ok ? `${s.elapsed_sec}초 · ${s.count}건${s.from_cache ? ' · 캐시' : ''}` : STATUS_LABEL[s.status]}
                </span>
              </div>
              {!pending && !ok && (
                <div className="mt-1 text-xs text-slate-500">
                  {s.message || '현재 검색 결과를 가져오지 못했습니다.'}
                  {s.manual_url && (
                    <a href={s.manual_url} target="_blank" rel="noreferrer" className="ml-1 text-blue-600 underline">직접 확인</a>
                  )}
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function Stat({ label, value }) {
  return (
    <div className="bg-slate-50 rounded-lg px-3 py-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="font-semibold">{value}</div>
    </div>
  )
}

function StatsBlock({ title, s }) {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5">
      <h3 className="font-semibold mb-3">{title} <span className="text-xs font-normal text-slate-500">매칭 후보 {s.count}건 · 판매자 {s.seller_count}</span></h3>
      <div className="grid grid-cols-3 gap-2 text-sm">
        <Stat label="최저" value={won(s.min_price)} />
        <Stat label="중앙값" value={won(s.median_price)} />
        <Stat label="평균" value={won(s.mean_price)} />
        <Stat label="최고" value={won(s.max_price)} />
        <Stat label="가격대(25~75%)" value={s.p25_price ? `${won(s.p25_price)}~${won(s.p75_price)}` : '-'} />
        <Stat label="표준편차" value={won(s.std_price)} />
      </div>
    </div>
  )
}

function StatsRow({ result }) {
  return (
    <div className="grid md:grid-cols-2 gap-4">
      <StatsBlock title="국내 소매 시장가격 (실질가격)" s={result.retail_stats} />
      <StatsBlock title="도매 실질원가" s={result.wholesale_stats} />
    </div>
  )
}

function toCsv(rows, wholesale) {
  const head = ['순위', '판매처', '상품명', '판매자', '상품가격', '배송비', '배송조건', wholesale ? 'MOQ' : null,
    wholesale ? '실질원가' : '실질가격', '매칭점수', '가격신뢰도', 'URL', '검색시각'].filter(Boolean)
  const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`
  const lines = rows.map((r) => [r.rank, r.source_name, r.name, r.seller, r.price,
    r.shipping.fee_known ? r.shipping_fee : '미확인', r.shipping_condition, wholesale ? r.min_order_quantity : null,
    r.effective_price, r.match_score, r.price_confidence, r.url, fmtTime(r.checked_at)].filter((_, i) => wholesale || i !== 7))
  return '﻿' + [head, ...lines].map((l) => l.map(esc).join(',')).join('\r\n')
}

function ResultTable({ title, subtitle, rows, query, wholesale, filename }) {
  const download = () => {
    const blob = new Blob([toCsv(rows, wholesale)], { type: 'text/csv;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${filename}_${query.replace(/\s+/g, '_')}.csv`
    a.click()
  }
  const anyUnknown = useMemo(() => rows.some((r) => !r.shipping.fee_known), [rows])
  return (
    <section className="bg-white rounded-xl shadow-sm border border-slate-200">
      <div className="flex items-center gap-3 px-5 py-4 border-b border-slate-200">
        <div>
          <h2 className="font-semibold">{title}</h2>
          <p className="text-xs text-slate-500">{subtitle}</p>
        </div>
        <button onClick={download} disabled={!rows.length}
          className="ml-auto text-sm border border-slate-300 rounded-lg px-3 py-1.5 hover:bg-slate-50 disabled:opacity-40">
          CSV 다운로드
        </button>
      </div>
      {rows.length === 0 ? (
        <p className="px-5 py-8 text-center text-slate-500 text-sm">조건에 맞는 상품이 없습니다. 최소 매칭점수를 낮추거나 사이트 연결 상태를 확인하세요.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500 text-xs">
              <tr>
                {['순위', '판매처', '상품명', '상품가격', '배송비', '배송조건', ...(wholesale ? ['MOQ'] : []),
                  wholesale ? '실질원가' : '실질가격', '매칭', '신뢰도', '검색시각'].map((h) => (
                  <th key={h} className="px-3 py-2 text-left font-medium whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={`${r.source}-${r.external_id}-${r.url}`} className="border-t border-slate-100 hover:bg-blue-50/40">
                  <td className="px-3 py-2 font-semibold text-center">{r.rank}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{r.source_name}</td>
                  <td className="px-3 py-2 min-w-64">
                    <a href={r.url} target="_blank" rel="noreferrer" className="text-blue-700 hover:underline">{r.name}</a>
                    {r.seller && <div className="text-xs text-slate-400">{r.seller}</div>}
                  </td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">{won(r.price)}</td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    {r.shipping.fee_known ? won(r.shipping_fee) : <span className="text-amber-700">미확인</span>}
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-600 min-w-40">{r.shipping_condition}</td>
                  {wholesale && <td className="px-3 py-2 text-right">{r.min_order_quantity}</td>}
                  <td className="px-3 py-2 text-right font-semibold whitespace-nowrap">{won(r.effective_price)}</td>
                  <td className="px-3 py-2 text-right">{r.match_score}</td>
                  <td className="px-3 py-2 text-right">{r.price_confidence}</td>
                  <td className="px-3 py-2 text-xs text-slate-400 whitespace-nowrap">{fmtTime(r.checked_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {anyUnknown && (
        <p className="px-5 py-3 text-xs text-amber-700 border-t border-slate-100">
          배송비 ‘미확인’은 해당 사이트 API가 배송비를 제공하지 않는 경우입니다. 실질가격은 상품가격만으로 계산되었으니 상품 페이지에서 확인하세요.
        </p>
      )}
    </section>
  )
}

const authHeaders = (token) => (token ? { Authorization: `Bearer ${token}` } : {})

function History({ token, tick, onPick }) {
  const [items, setItems] = useState([])
  useEffect(() => {
    fetch(`${API}/api/history?limit=12`, { headers: authHeaders(token) })
      .then((r) => (r.ok ? r.json() : { items: [] }))
      .then((d) => setItems(d.items || []))
      .catch(() => {})
  }, [token, tick])
  if (!items.length) return null
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-slate-500">최근 검색</span>
      {items.map((h) => (
        <button key={h.id} onClick={() => onPick(h.query)} title={fmtTime(h.created_at)}
          className="px-2.5 py-1 rounded-full bg-white border border-slate-200 hover:border-blue-300">
          {h.query}
          {h.retail_stats?.min_price ? <span className="ml-1 text-xs text-slate-400">최저 {won(h.retail_stats.min_price)}</span> : null}
        </button>
      ))}
    </div>
  )
}

function Login({ supabase }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setMsg('')
    const { error } = await supabase.auth.signInWithPassword({ email, password })
    setBusy(false)
    if (error) setMsg('로그인에 실패했습니다. 이메일과 비밀번호를 확인하세요.')
  }
  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm bg-white rounded-xl shadow-sm border border-slate-200 p-6 space-y-4">
        <h1 className="text-lg font-bold">상품 소싱 가격비교 로그인</h1>
        <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="이메일"
          className="w-full border border-slate-300 rounded-lg px-3 py-2" />
        <input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} placeholder="비밀번호"
          className="w-full border border-slate-300 rounded-lg px-3 py-2" />
        {msg && <p className="text-sm text-red-600">{msg}</p>}
        <button disabled={busy} className="w-full rounded-lg bg-blue-600 text-white font-semibold py-2 hover:bg-blue-700 disabled:bg-slate-400">
          {busy ? '확인 중…' : '로그인'}
        </button>
        <p className="text-xs text-slate-500">계정은 관리자가 Supabase에서 생성합니다.</p>
      </form>
    </div>
  )
}

export default function App() {
  const [config, setConfig] = useState(null)
  const [supabase, setSupabase] = useState(null)
  const [session, setSession] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    fetch(`${API}/api/config`)
      .then((r) => r.json())
      .then((c) => {
        setConfig(c)
        if (c.auth_required && c.supabase_url && c.supabase_anon_key) {
          const client = createClient(c.supabase_url, c.supabase_anon_key)
          setSupabase(client)
          client.auth.getSession().then(({ data }) => setSession(data.session))
          client.auth.onAuthStateChange((_e, s) => setSession(s))
        }
      })
      .catch(() => setErr('백엔드(API)에 연결할 수 없습니다. 백엔드 서버가 실행 중인지 확인하세요.'))
  }, [])

  if (err) return <div className="p-8 text-red-700">{err}</div>
  if (!config) return <div className="p-8 text-slate-500">불러오는 중…</div>
  if (config.auth_required && !session) return supabase ? <Login supabase={supabase} /> : null
  return (
    <SearchApp
      config={config}
      token={session?.access_token}
      userEmail={session?.user?.email}
      onSignOut={() => supabase?.auth.signOut()}
    />
  )
}
