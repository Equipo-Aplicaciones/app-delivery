-- Clave de prueba de la API. El valor no vive en este archivo.
-- Se inserta en private.evidencia_clave (id = 1) fuera del repositorio.
-- service_role la lee desde la Edge Function. anon y authenticated no entran.

create schema if not exists private;

create table private.evidencia_clave (
  id integer primary key default 1,
  api_key text not null,
  constraint evidencia_clave_singleton check (id = 1),
  constraint evidencia_clave_larga check (char_length(api_key) >= 16)
);

alter table private.evidencia_clave enable row level security;

revoke all on schema private from public, anon, authenticated;
revoke all on table private.evidencia_clave from public, anon, authenticated;
grant usage on schema private to service_role;
grant select on table private.evidencia_clave to service_role;
