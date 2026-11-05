-- PostgREST no expone el schema private. La clave queda en public,
-- con RLS y sin permisos para anon ni authenticated. Solo service_role la lee.

create table public.evidencia_clave (
  id integer primary key default 1,
  api_key text not null,
  constraint evidencia_clave_singleton check (id = 1),
  constraint evidencia_clave_larga check (char_length(api_key) >= 16)
);

alter table public.evidencia_clave enable row level security;

revoke all on table public.evidencia_clave from public, anon, authenticated;

insert into public.evidencia_clave (id, api_key)
select id, api_key from private.evidencia_clave;

drop table private.evidencia_clave;
