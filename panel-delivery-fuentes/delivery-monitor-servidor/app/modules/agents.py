"""Agentes con API key (hash en disco; la clave cruda solo al crear)."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import uuid

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse

from delivery_monitor.parseutil import iso_chile

from ..deps import audit, get_settings, operator

router = APIRouter(prefix="/api/agents")

_lock = threading.Lock()
SCOPES = (
    "snapshot.read", "reports.read", "disputes.read", "stores.write",
    "catalog.write", "disputes.write", "automations.write",
)
HUMAN_ONLY = ("credentials.write", "agents.admin")


def _path():
    return get_settings().data_dir / "agents.json"


def _read() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    os.chmod(p, 0o600)


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


RATE_LIMIT = int(os.environ.get("AGENT_RATE_LIMIT_PER_MIN", "120"))
_hits: dict[str, list[float]] = {}
_last_seen: dict[str, float] = {}


def authenticate(raw: str, scope: str | None) -> str:
    """Valida la API key de un agente y el scope de la ruta. Devuelve `agent:<id>`."""
    if not raw.startswith("tdk_") or len(raw) > 200:
        raise HTTPException(status_code=401, detail="No autenticado")
    digest = _hash_key(raw)
    with _lock:
        data = _read()
        entry = next((v for v in data.values()
                      if not v.get("revoked") and hmac.compare_digest(str(v.get("key_hash") or ""), digest)), None)
        if not entry:
            raise HTTPException(status_code=401, detail="No autenticado")
        if scope is None or scope not in (entry.get("scopes") or []):
            raise HTTPException(status_code=403, detail=f"El agente no tiene el scope requerido ({scope or 'solo operador'})")
        now = time.monotonic()
        hits = [t for t in _hits.get(entry["id"], []) if now - t < 60]
        if len(hits) >= RATE_LIMIT:
            raise HTTPException(status_code=429, detail="Demasiadas solicitudes de este agente")
        hits.append(now)
        _hits[entry["id"]] = hits
        if now - _last_seen.get(entry["id"], -1e9) > 60:
            _last_seen[entry["id"]] = now
            entry["last_used_at"] = iso_chile()
            data[entry["id"]] = entry
            _write(data)
    return f"agent:{entry['id']}"


def _clean_scopes(raw) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="scopes debe ser una lista")
    wanted = [str(s).strip() for s in raw if str(s).strip()]
    if any(s in HUMAN_ONLY for s in wanted):
        raise HTTPException(status_code=403, detail="credentials.write y agents.admin quedan solo para el operador humano")
    unknown = [s for s in wanted if s not in SCOPES]
    if unknown:
        raise HTTPException(status_code=400, detail="Scopes desconocidos: " + ", ".join(unknown[:5]))
    return sorted(set(wanted))


def _public(entry: dict) -> dict:
    return {
        "id": entry["id"],
        "name": entry.get("name"),
        "scopes": entry.get("scopes") or [],
        "prefix": entry.get("prefix"),
        "revoked": bool(entry.get("revoked")),
        "created_at": entry.get("created_at"),
        "last_used_at": entry.get("last_used_at"),
    }


@router.get("")
async def list_agents(request: Request):
    operator(request)
    with _lock:
        items = [_public(v) for v in _read().values() if not v.get("revoked")]
    return {"agents": items, "available_scopes": list(SCOPES)}


@router.post("")
async def create_agent(request: Request, body: dict = Body(...)):
    user = operator(request)
    name = str(body.get("name") or "").strip()[:120]
    if not name:
        raise HTTPException(status_code=400, detail="Falta name")
    scopes = _clean_scopes(body.get("scopes"))
    raw = "tdk_" + secrets.token_urlsafe(32)
    entry = {
        "id": uuid.uuid4().hex[:10],
        "name": name,
        "scopes": scopes,
        "prefix": raw[:12],
        "key_hash": _hash_key(raw),
        "revoked": False,
        "created_at": iso_chile(),
        "last_used_at": None,
    }
    with _lock:
        data = _read()
        data[entry["id"]] = entry
        _write(data)
    audit(user, "agents.create", entry["id"], False, "ok", name)
    pub = _public(entry)
    pub["api_key"] = raw
    pub["note"] = "Guarde esta clave ahora: no se volverá a mostrar."
    return JSONResponse(pub, headers={"Cache-Control": "no-store"})


@router.patch("/{agent_id}")
async def patch_agent(request: Request, agent_id: str, body: dict = Body(...)):
    user = operator(request)
    with _lock:
        data = _read()
        entry = data.get(agent_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Agente no encontrado")
        if "name" in body:
            entry["name"] = str(body["name"])[:120]
        if "scopes" in body:
            entry["scopes"] = _clean_scopes(body["scopes"])
        if body.get("revoked") is True:
            entry["revoked"] = True
        data[agent_id] = entry
        _write(data)
    audit(user, "agents.patch", agent_id, False, "ok")
    return _public(entry)


@router.delete("/{agent_id}")
async def delete_agent(request: Request, agent_id: str):
    user = operator(request)
    with _lock:
        data = _read()
        entry = data.get(agent_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Agente no encontrado")
        entry["revoked"] = True
        data[agent_id] = entry
        _write(data)
    audit(user, "agents.delete", agent_id, False, "ok")
    return {"revoked": True, "id": agent_id}
