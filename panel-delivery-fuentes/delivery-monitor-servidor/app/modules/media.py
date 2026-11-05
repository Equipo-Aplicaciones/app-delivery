"""Fotos de reclamo guardadas fuera de git con nombre opaco e índice por pedido.

Las imágenes pueden traer PII (cédulas, direcciones): se sirven solo con sesión
y nunca se incluyen en reportes exportados.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import shutil
import threading
from pathlib import Path

from delivery_monitor.parseutil import iso_chile

PLATFORMS = ("uber", "pedidosya")
ORDER_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
MEDIA_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,40}\.[a-z0-9]{2,5}$")
_EXT_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
    ".heic": "image/heic", ".mp4": "video/mp4", ".pdf": "application/pdf",
}
_lock = threading.Lock()


class MediaError(ValueError):
    pass


def valid_order(order_id: str) -> str:
    order_id = (order_id or "").strip()
    if not ORDER_RE.match(order_id):
        raise MediaError("Número de pedido inválido")
    return order_id


def _order_dir(root: Path, platform: str, order_id: str) -> Path:
    if platform not in PLATFORMS:
        raise MediaError("Plataforma inválida")
    return root / platform / valid_order(order_id)


def _index_path(folder: Path) -> Path:
    return folder / "index.json"


def _read_index(folder: Path) -> dict:
    path = _index_path(folder)
    if not path.is_file():
        return {"items": [], "meta": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"items": [], "meta": None}
    if not isinstance(data, dict):
        return {"items": [], "meta": None}
    data.setdefault("items", [])
    data.setdefault("meta", None)
    return data


def _write_index(folder: Path, data: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = _index_path(folder).with_suffix(".json.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp, _index_path(folder))


def _content_type(path: Path) -> str:
    ext = path.suffix.lower()
    return _EXT_TYPES.get(ext) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def import_folder(root: Path, platform: str, order_id: str, group: str, src: Path) -> list[dict]:
    """Mueve los archivos que dejó un CLI a nombres opacos y los agrega al índice."""
    folder = _order_dir(root, platform, order_id)
    added = []
    if not src.is_dir():
        return added
    with _lock:
        data = _read_index(folder)
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        for item in sorted(src.iterdir()):
            if not item.is_file() or item.name.endswith(".json"):
                continue
            ext = item.suffix.lower() if item.suffix.lower() in _EXT_TYPES else ".bin"
            media_id = secrets.token_urlsafe(12) + ext
            dest = folder / media_id
            shutil.move(str(item), dest)
            os.chmod(dest, 0o600)
            entry = {
                "id": media_id,
                "group": group,
                "content_type": _content_type(dest),
                "bytes": dest.stat().st_size,
                "sensitive": False,
                "saved_at": iso_chile(),
            }
            data["items"].append(entry)
            added.append(entry)
        _write_index(folder, data)
    return added


def replace_group(root: Path, platform: str, order_id: str, group: str, src: Path) -> list[dict]:
    """Reemplaza las fotos de un grupo (p. ej. al volver a consultar la plataforma)."""
    folder = _order_dir(root, platform, order_id)
    with _lock:
        data = _read_index(folder)
        keep, drop = [], []
        for item in data["items"]:
            (drop if item.get("group") == group else keep).append(item)
        sensitive_before = any(i.get("sensitive") for i in drop)
        for item in drop:
            try:
                (folder / item["id"]).unlink()
            except (OSError, KeyError):
                pass
        data["items"] = keep
        if folder.exists() or keep:
            _write_index(folder, data)
    added = import_folder(root, platform, order_id, group, src)
    if sensitive_before and added:
        for entry in added:
            set_sensitive(root, platform, order_id, entry["id"], True)
            entry["sensitive"] = True
    return added


def list_items(root: Path, platform: str, order_id: str) -> list[dict]:
    folder = _order_dir(root, platform, order_id)
    return [i for i in _read_index(folder)["items"] if (folder / i.get("id", "")).is_file()]


def get_meta(root: Path, platform: str, order_id: str) -> dict | None:
    return _read_index(_order_dir(root, platform, order_id)).get("meta")


def set_meta(root: Path, platform: str, order_id: str, meta: dict) -> None:
    folder = _order_dir(root, platform, order_id)
    with _lock:
        data = _read_index(folder)
        data["meta"] = meta
        _write_index(folder, data)


def find(root: Path, platform: str, order_id: str, media_id: str) -> tuple[Path, dict]:
    if not MEDIA_ID_RE.match(media_id or ""):
        raise MediaError("Archivo inválido")
    folder = _order_dir(root, platform, order_id)
    for item in _read_index(folder)["items"]:
        if item.get("id") == media_id:
            path = folder / media_id
            if path.is_file():
                return path, item
    raise FileNotFoundError(media_id)


def set_sensitive(root: Path, platform: str, order_id: str, media_id: str, sensitive: bool) -> dict:
    folder = _order_dir(root, platform, order_id)
    with _lock:
        data = _read_index(folder)
        for item in data["items"]:
            if item.get("id") == media_id:
                item["sensitive"] = bool(sensitive)
                _write_index(folder, data)
                return item
    raise FileNotFoundError(media_id)
