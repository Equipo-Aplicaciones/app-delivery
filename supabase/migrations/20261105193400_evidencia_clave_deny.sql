-- Denegación explícita para que la Data API no lea la clave de prueba.

create policy evidencia_clave_deny_select
  on public.evidencia_clave
  for select
  to anon, authenticated
  using (false);

create policy evidencia_clave_deny_insert
  on public.evidencia_clave
  for insert
  to anon, authenticated
  with check (false);

create policy evidencia_clave_deny_update
  on public.evidencia_clave
  for update
  to anon, authenticated
  using (false)
  with check (false);

create policy evidencia_clave_deny_delete
  on public.evidencia_clave
  for delete
  to anon, authenticated
  using (false);
