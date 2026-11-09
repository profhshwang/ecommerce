-- 상품 소싱 가격비교: 초기 스키마 (계획서 33~36절 중 MVP-1 범위)
-- Supabase SQL Editor 에 붙여 넣어 실행하거나, Supabase GitHub 연동 시 자동 적용된다.

create table if not exists public.searches (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete set null,
  query text not null,
  expanded_queries text[] not null default '{}',
  selected_sources text[] not null default '{}',
  quantity int not null default 1,
  search_started_at timestamptz not null,
  search_completed_at timestamptz not null,
  result_count int not null default 0,
  status text not null default 'done',
  error_sources jsonb not null default '[]'::jsonb,
  retail_stats jsonb,
  wholesale_stats jsonb,
  created_at timestamptz not null default now()
);
create index if not exists searches_user_created_idx on public.searches (user_id, created_at desc);
create index if not exists searches_query_idx on public.searches (query);

-- 검색할 때마다 TOP 결과의 가격을 저장 (가격 이력, TC-09)
create table if not exists public.price_history (
  id bigint generated always as identity primary key,
  search_id uuid references public.searches(id) on delete cascade,
  query text not null,
  kind text not null check (kind in ('retail', 'wholesale')),
  source text not null,
  external_id text,
  product_name text not null,
  product_url text not null,
  seller text,
  rank int,
  price int not null,
  shipping_fee int,
  shipping_fee_known boolean not null default true,
  shipping_condition text,
  min_order_quantity int not null default 1,
  effective_price int not null,
  match_score int,
  price_confidence int,
  captured_at timestamptz not null default now()
);
create index if not exists price_history_url_idx on public.price_history (product_url, captured_at desc);
create index if not exists price_history_query_idx on public.price_history (query, captured_at desc);

-- RLS: 로그인한 사용자는 모두 읽기 가능 (초기에는 모든 사용자 동일 권한, 계획서 2.1).
-- 쓰기는 백엔드(service_role 키)만 수행한다.
alter table public.searches enable row level security;
alter table public.price_history enable row level security;

drop policy if exists "authenticated read searches" on public.searches;
create policy "authenticated read searches" on public.searches
  for select to authenticated using (true);

drop policy if exists "authenticated read price_history" on public.price_history;
create policy "authenticated read price_history" on public.price_history
  for select to authenticated using (true);
