"""Orquesta la lectura de solo lectura y escribe un snapshot JSON limpio."""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path

from .adapters import ADAPTERS
from .parseutil import iso_chile
from .snapshot import build_snapshot

DEFAULT_OUT = Path(os.environ.get("SNAPSHOT_PATH", "/app/data/snapshot.json"))


def fetch_all(names: list[str] | None = None) -> list:
    selected = names or list(ADAPTERS)
    results = []

    def run(name: str):
        adapter = ADAPTERS[name]()
        return adapter.fetch()

    with ThreadPoolExecutor(max_workers=len(selected) or 1) as pool:
        futs = {pool.submit(run, name): name for name in selected}
        for fut in as_completed(futs):
            results.append(fut.result())
    order = {name: i for i, name in enumerate(["uber", "pedidosya", "rappi"])}
    results.sort(key=lambda r: order.get(r.platform, 99))
    return results


def write_snapshot(path: Path, snap: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(snap, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def summarize(snap: dict) -> str:
    lines = [
        f"snapshot {snap['generated_at']} ({snap['timezone']})",
    ]
    for name, src in snap["sources"].items():
        n = src.get("stores_count")
        d = src.get("disputes_count")
        extra = src.get("disputes_status") or ""
        err = src.get("error") or src.get("disputes_error") or ""
        piece = f"  {name}: fuentes={src['status']} tiendas={n!s} disputas={d!s} ({extra})"
        if err:
            piece += f" — {err[:180]}"
        lines.append(piece)
    tot = snap["totals"]
    lines.append(
        f"  totales lectura ok: tiendas={tot['stores']} abiertas={tot['open_now']} "
        f"horario={tot['closed_schedule']} pausadas={tot['paused']} "
        f"disputas_confirmadas={tot['disputes_unopened']}"
    )
    return "\n".join(lines)


def refresh(out: Path | str = DEFAULT_OUT, providers: list[str] | None = None) -> dict:
    results = fetch_all(providers)
    snap = build_snapshot(results, generated_at=iso_chile())
    write_snapshot(Path(out), snap)
    return snap


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Refresca el snapshot de monitoreo (solo lectura).")
    p.add_argument("--out", default=str(DEFAULT_OUT), help="ruta del JSON de salida")
    p.add_argument(
        "--providers",
        default="uber,pedidosya,rappi",
        help="lista separada por comas (uber,pedidosya,rappi)",
    )
    args = p.parse_args(argv)
    names = [x.strip() for x in args.providers.split(",") if x.strip()]
    unknown = [n for n in names if n not in ADAPTERS]
    if unknown:
        print("proveedores desconocidos:", ", ".join(unknown), file=sys.stderr)
        print("disponibles:", ", ".join(ADAPTERS), file=sys.stderr)
        return 2
    snap = refresh(args.out, names)
    print(summarize(snap))
    print("escrito:", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
