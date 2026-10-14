-- Mustard Seed remote dashboard relay (Supabase, public schema, ms_ prefix).
-- Tables have RLS on and NO policies, so the API keys can't read them directly.
-- Everything goes through these SECURITY DEFINER functions, which check a secret token
-- (sha256 stored in ms_secret). The PC and the Vercel server hold the token; browsers never see it.
create extension if not exists pgcrypto with schema extensions;
create table if not exists public.ms_secret (id int primary key default 1, token_hash text not null, pw_hash text, check (id = 1));
create table if not exists public.ms_jobs (id text primary key, status text, score real, data jsonb not null, updated_at timestamptz default now());
create index if not exists ms_jobs_status on public.ms_jobs(status);
create table if not exists public.ms_state (k text primary key, v jsonb, updated_at timestamptz default now());
create table if not exists public.ms_commands (id bigserial primary key, created_at timestamptz default now(), kind text not null,
  payload jsonb default '{}'::jsonb, status text default 'pending', result jsonb, done_at timestamptz);
create table if not exists public.ms_files (job_id text, kind text, name text, b64 text, updated_at timestamptz default now(), primary key (job_id, kind));
alter table public.ms_secret enable row level security;
alter table public.ms_jobs enable row level security;
alter table public.ms_state enable row level security;
alter table public.ms_commands enable row level security;
alter table public.ms_files enable row level security;

create or replace function public.ms_ok(p_token text) returns boolean language sql stable security definer set search_path = public, extensions as $$
  select exists (select 1 from public.ms_secret where token_hash = encode(extensions.digest(coalesce(p_token,''), 'sha256'), 'hex'));
$$;

create or replace function public.ms_push_jobs(p_token text, p_rows jsonb) returns int language plpgsql security definer set search_path = public, extensions as $$
declare n int;
begin
  if not public.ms_ok(p_token) then raise exception 'unauthorised'; end if;
  insert into public.ms_jobs (id, status, score, data, updated_at)
    select r->>'id', r->>'status', nullif(r->>'score','')::real, r, now() from jsonb_array_elements(p_rows) r
  on conflict (id) do update set status = excluded.status, score = excluded.score, data = excluded.data, updated_at = now();
  get diagnostics n = row_count; return n;
end $$;

create or replace function public.ms_prune_jobs(p_token text, p_keep text[]) returns int language plpgsql security definer set search_path = public, extensions as $$
declare n int;
begin
  if not public.ms_ok(p_token) then raise exception 'unauthorised'; end if;
  delete from public.ms_jobs where not (id = any(p_keep));
  get diagnostics n = row_count;
  delete from public.ms_files where not (job_id = any(p_keep));
  return n;
end $$;

create or replace function public.ms_set_state(p_token text, p_k text, p_v jsonb) returns void language plpgsql security definer set search_path = public, extensions as $$
begin
  if not public.ms_ok(p_token) then raise exception 'unauthorised'; end if;
  insert into public.ms_state (k, v, updated_at) values (p_k, p_v, now()) on conflict (k) do update set v = excluded.v, updated_at = now();
end $$;

create or replace function public.ms_set_password(p_token text, p_password text) returns void language plpgsql security definer set search_path = public, extensions as $$
begin
  if not public.ms_ok(p_token) then raise exception 'unauthorised'; end if;
  update public.ms_secret set pw_hash = extensions.crypt(p_password, extensions.gen_salt('bf')) where id = 1;
end $$;

create or replace function public.ms_take_commands(p_token text) returns setof public.ms_commands language plpgsql security definer set search_path = public, extensions as $$
begin
  if not public.ms_ok(p_token) then raise exception 'unauthorised'; end if;
  return query update public.ms_commands set status = 'taken' where status = 'pending' returning *;
end $$;

create or replace function public.ms_finish_command(p_token text, p_id bigint, p_result jsonb) returns void language plpgsql security definer set search_path = public, extensions as $$
begin
  if not public.ms_ok(p_token) then raise exception 'unauthorised'; end if;
  update public.ms_commands set status = 'done', result = p_result, done_at = now() where id = p_id;
  delete from public.ms_commands where created_at < now() - interval '14 days';
end $$;

create or replace function public.ms_put_file(p_token text, p_job_id text, p_kind text, p_name text, p_b64 text) returns void language plpgsql security definer set search_path = public, extensions as $$
begin
  if not public.ms_ok(p_token) then raise exception 'unauthorised'; end if;
  insert into public.ms_files (job_id, kind, name, b64, updated_at) values (p_job_id, p_kind, p_name, p_b64, now())
  on conflict (job_id, kind) do update set name = excluded.name, b64 = excluded.b64, updated_at = now();
end $$;

create or replace function public.ms_file_index(p_token text) returns table (job_id text, kind text, name text) language plpgsql security definer set search_path = public, extensions as $$
begin
  if not public.ms_ok(p_token) then raise exception 'unauthorised'; end if;
  return query select f.job_id, f.kind, f.name from public.ms_files f;
end $$;

create or replace function public.ms_check_password(p_token text, p_password text) returns boolean language plpgsql security definer set search_path = public, extensions as $$
declare h text;
begin
  if not public.ms_ok(p_token) then raise exception 'unauthorised'; end if;
  select pw_hash into h from public.ms_secret where id = 1;
  return h is not null and h = extensions.crypt(coalesce(p_password,''), h);
end $$;

create or replace function public.ms_list_jobs(p_token text, p_statuses text[], p_limit int default 300) returns setof jsonb language plpgsql security definer set search_path = public, extensions as $$
begin
  if not public.ms_ok(p_token) then raise exception 'unauthorised'; end if;
  return query select j.data || jsonb_build_object('synced_at', j.updated_at) from public.ms_jobs j
    where j.status = any(p_statuses) order by j.score desc nulls last limit least(p_limit, 1000);
end $$;

create or replace function public.ms_get_state(p_token text) returns jsonb language plpgsql security definer set search_path = public, extensions as $$
declare r jsonb;
begin
  if not public.ms_ok(p_token) then raise exception 'unauthorised'; end if;
  select jsonb_object_agg(k, jsonb_build_object('v', v, 'updated_at', updated_at)) into r from public.ms_state;
  return coalesce(r, '{}'::jsonb) || jsonb_build_object('now', now(), 'counts',
    (select coalesce(jsonb_object_agg(status, n), '{}'::jsonb) from (select status, count(*) n from public.ms_jobs group by status) x),
    'commands', (select coalesce(jsonb_agg(c order by c.id desc), '[]'::jsonb) from (select id, created_at, kind, payload, status, result, done_at from public.ms_commands order by id desc limit 25) c));
end $$;

create or replace function public.ms_add_command(p_token text, p_kind text, p_payload jsonb) returns bigint language plpgsql security definer set search_path = public, extensions as $$
declare new_id bigint;
begin
  if not public.ms_ok(p_token) then raise exception 'unauthorised'; end if;
  if p_kind not in ('job_action', 'contact_sent', 'run', 'approve_all') then raise exception 'unknown command'; end if;
  insert into public.ms_commands (kind, payload) values (p_kind, coalesce(p_payload, '{}'::jsonb)) returning id into new_id;
  return new_id;
end $$;

create or replace function public.ms_get_file(p_token text, p_job_id text, p_kind text) returns jsonb language plpgsql security definer set search_path = public, extensions as $$
begin
  if not public.ms_ok(p_token) then raise exception 'unauthorised'; end if;
  return (select jsonb_build_object('name', name, 'b64', b64) from public.ms_files where job_id = p_job_id and kind = p_kind);
end $$;
