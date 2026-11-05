-- Metadata for delivery-dispute photos.
-- Remote migration version 20261105190131 (name create_evidencia),
-- applied on project nfryurrhgaeepdwqtswo.
-- Several rows per (agregador, numero_orden) are allowed: no unique constraint on that pair.
-- Image bytes live in the private storage bucket evidencia (same project).
-- The app talks only to the API. service_role stays server-side and bypasses RLS.
-- anon and authenticated have no table grants. Policies below are an explicit deny
-- so the Data API cannot read or write this table with the publishable key.

create table public.evidencia (
  id uuid primary key default gen_random_uuid(),
  agregador text not null,
  numero_orden text not null,
  storage_path text not null,
  created_at timestamptz not null default now(),
  constraint evidencia_agregador_check
    check (agregador in ('uber', 'pedidosya')),
  constraint evidencia_numero_orden_trimmed_check
    check (
      char_length(numero_orden) > 0
      and numero_orden = btrim(numero_orden)
    ),
  constraint evidencia_storage_path_unique unique (storage_path)
);

comment on table public.evidencia is
  'Metadata de fotos de disputa. Los bytes están en el bucket evidencia. Varias filas por (agregador, numero_orden).';

comment on column public.evidencia.agregador is
  'Catálogo cerrado: uber | pedidosya.';

comment on column public.evidencia.numero_orden is
  'Número de orden ya recortado (sin espacios al inicio ni al final).';

comment on column public.evidencia.storage_path is
  'Clave del objeto dentro del bucket evidencia. No es una URL pública.';

create index evidencia_clave_idx
  on public.evidencia (agregador, numero_orden, created_at);

alter table public.evidencia enable row level security;

revoke all on table public.evidencia from public, anon, authenticated;
grant select, insert, update, delete on table public.evidencia to service_role;

create policy evidencia_api_only_select
  on public.evidencia
  for select
  to anon, authenticated
  using (false);

create policy evidencia_api_only_insert
  on public.evidencia
  for insert
  to anon, authenticated
  with check (false);

create policy evidencia_api_only_update
  on public.evidencia
  for update
  to anon, authenticated
  using (false)
  with check (false);

create policy evidencia_api_only_delete
  on public.evidencia
  for delete
  to anon, authenticated
  using (false);

insert into storage.buckets (id, name, public)
values ('evidencia', 'evidencia', false);

create policy evidencia_bucket_deny_select
  on storage.objects
  for select
  to anon, authenticated
  using (bucket_id = 'evidencia' and false);

create policy evidencia_bucket_deny_insert
  on storage.objects
  for insert
  to anon, authenticated
  with check (bucket_id = 'evidencia' and false);

create policy evidencia_bucket_deny_update
  on storage.objects
  for update
  to anon, authenticated
  using (bucket_id = 'evidencia' and false)
  with check (bucket_id = 'evidencia' and false);

create policy evidencia_bucket_deny_delete
  on storage.objects
  for delete
  to anon, authenticated
  using (bucket_id = 'evidencia' and false);
