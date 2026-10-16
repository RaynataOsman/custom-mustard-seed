-- 16 Oct 2026 (applied to project iltybjpqtcrbedtcoedz via the SQL editor).
-- Light role list + single-role fetch for the online dashboard. The full Review list (846 roles) is ~7 MB,
-- over Vercel's 4.5 MB response limit and heavy on the free Supabase egress allowance. The list leaves out
-- the long text (description, cover letter, prep, gaps, referral note text); a role's full data loads when
-- opened. Read-only and token-checked like every other ms_* function. Safe to run more than once.

create or replace function public.ms_list_jobs_lite(p_token text, p_statuses text[], p_limit int default 1000)
returns setof jsonb language plpgsql security definer set search_path = public, extensions as $$
begin
  if not public.ms_ok(p_token) then raise exception 'unauthorised'; end if;
  return query
    select (j.data - 'description' - 'cover_letter' - 'interview_prep' - 'gaps' - 'geo_reason' - 'contacts')
           || jsonb_build_object('synced_at', j.updated_at,
                                 'score_reasons', left(coalesce(j.data->>'score_reasons', ''), 160),
                                 'has_cover', (j.data->>'cover_letter') is not null,
                                 'n_prep', coalesce(jsonb_array_length(case when jsonb_typeof(j.data->'interview_prep') = 'array'
                                                                       then j.data->'interview_prep' end), 0),
                                 'contacts', coalesce((select jsonb_agg(c - 'note' - 'followup' - 'headline')
                                                       from jsonb_array_elements(case when jsonb_typeof(j.data->'contacts') = 'array'
                                                                                      then j.data->'contacts' else '[]'::jsonb end) c), '[]'::jsonb))
    from public.ms_jobs j
    where j.status = any(p_statuses)
    order by j.score desc nulls last
    limit least(p_limit, 2000);
end $$;

create or replace function public.ms_get_job(p_token text, p_id text)
returns jsonb language plpgsql security definer set search_path = public, extensions as $$
declare r jsonb;
begin
  if not public.ms_ok(p_token) then raise exception 'unauthorised'; end if;
  select j.data || jsonb_build_object('synced_at', j.updated_at) into r from public.ms_jobs j where j.id = p_id;
  return r;
end $$;
