"""Jobs de lectura/escritura y artefactos en data/exports/."""
from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path

from delivery_monitor.parseutil import iso_chile
from delivery_monitor.sanitize import sanitize

from ..config import Settings
from ..deps import get_settings

_lock = threading.Lock()


def exports_dir(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    path = settings.data_dir / "exports"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def jobs_path(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    return settings.data_dir / "jobs.json"


def _read_all(settings: Settings) -> dict:
    path = jobs_path(settings)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_all(settings: Settings, data: dict) -> None:
    path = jobs_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def create_job(kind: str, created_by: str, *, dry_run: bool, input_sanitized: dict) -> dict:
    settings = get_settings()
    job_id = uuid.uuid4().hex[:12]
    entry = {
        "id": job_id,
        "kind": kind,
        "created_at": iso_chile(),
        "created_by": created_by,
        "dry_run": dry_run,
        "status": "queued",
        "input": input_sanitized,
        "result_summary": None,
        "artifact_path": None,
        "error": None,
    }
    with _lock:
        data = _read_all(settings)
        data[job_id] = entry
        _write_all(settings, data)
    return dict(entry)


def update_job(job_id: str, **fields) -> dict:
    settings = get_settings()
    with _lock:
        data = _read_all(settings)
        entry = data.get(job_id)
        if not entry:
            raise KeyError(job_id)
        for k, v in fields.items():
            if v is not None or k in ("result_summary", "error", "artifact_path"):
                entry[k] = v
        data[job_id] = entry
        _write_all(settings, data)
        return dict(entry)


def get_job(job_id: str) -> dict | None:
    with _lock:
        return dict(_read_all(get_settings()).get(job_id) or {}) or None


def public_job(entry: dict) -> dict:
    art = entry.get("artifact_path")
    return {
        "id": entry["id"],
        "kind": entry.get("kind"),
        "created_at": entry.get("created_at"),
        "created_by": entry.get("created_by"),
        "dry_run": entry.get("dry_run"),
        "status": entry.get("status"),
        "result_summary": entry.get("result_summary"),
        "error": sanitize(entry.get("error") or ""),
        "artifact": os.path.basename(art) if art else None,
        "download_url": f"/api/reports/jobs/{entry['id']}/download" if art and entry.get("status") == "done" else None,
    }


def save_artifact(job_id: str, name: str, content: bytes) -> Path:
    settings = get_settings()
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)[:120]
    path = exports_dir(settings) / f"{job_id}-{safe}"
    path.write_bytes(content)
    os.chmod(path, 0o600)
    return path
