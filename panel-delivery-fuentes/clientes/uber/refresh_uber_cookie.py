#!/usr/bin/env python3
"""Renueva / valida la cookie de Uber Eats Manager.

Nunca imprime el valor de la cookie.

Uso:
  python3 refresh_uber_cookie.py --check          # solo health check
  python3 refresh_uber_cookie.py --from-env       # copia UBER_COOKIE -> ~/.uber_cookie
  python3 refresh_uber_cookie.py --from-file PATH # lee header Cookie desde un archivo

La renovación desde el navegador la hace el agente (abre merchants.ubereats.com,
exporta el header Cookie a un archivo temporal y llama --from-file). Las cookies
HttpOnly (sid, jwt-session) no salen por document.cookie.
"""
from __future__ import annotations
import argparse, os, sys, datetime as dt
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_client import UberEatsClient, load_cookie, save_cookie, COOKIE_FILE

TZ = ZoneInfo("America/Santiago")


def health() -> dict:
    c = UberEatsClient()
    stores = c.list_stores(limit=20)
    return {"ok": True, "stores_sample": len(stores), "checked_at": dt.datetime.now(TZ).isoformat()}


def main():
    p = argparse.ArgumentParser(description="Validar/guardar cookie Uber (nunca la imprime)")
    p.add_argument("--check", action="store_true", help="solo verificar que la cookie actual funciona")
    p.add_argument("--from-env", action="store_true", help="sembrar ~/.uber_cookie desde UBER_COOKIE")
    p.add_argument("--from-file", metavar="PATH", help="leer header Cookie desde archivo y guardar")
    a = p.parse_args()

    if a.from_env:
        val = (os.environ.get("UBER_COOKIE") or "").strip()
        if not val:
            print("ERROR: UBER_COOKIE vacío en el entorno", file=sys.stderr)
            sys.exit(2)
        path = save_cookie(val)
        print(f"ok: cookie guardada en {path} ({len(val)} chars)", file=sys.stderr)

    if a.from_file:
        path_in = a.from_file
        val = open(path_in, encoding="utf-8").read().strip()
        # permitir "Cookie: ..." o solo el valor
        if val.lower().startswith("cookie:"):
            val = val.split(":", 1)[1].strip()
        path = save_cookie(val)
        print(f"ok: cookie guardada en {path} ({len(val)} chars)", file=sys.stderr)
        try:
            os.remove(path_in)
        except OSError:
            pass

    if a.check or a.from_env or a.from_file or not (a.from_env or a.from_file or a.check):
        # default: check
        try:
            load_cookie()
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(2)
        try:
            info = health()
        except Exception as e:
            print(f"FAIL: cookie no sirve ({type(e).__name__}: {e})", file=sys.stderr)
            sys.exit(1)
        print(f"OK: cookie válida — sample {info['stores_sample']} locales — {info['checked_at']}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
