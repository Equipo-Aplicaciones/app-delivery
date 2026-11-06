"""Fotos que la tienda subió con la app delivery (Edge Function `evidencia` de Supabase).

La clave `x-evidencia-key` y las URLs firmadas del bucket se quedan en el servidor:
el navegador solo ve rutas del panel.
"""
from __future__ import annotations

import threading
import time
from urllib.parse import urlsplit

import httpx

from delivery_monitor.sanitize import sanitize

from ..config import Settings

AGGREGATORS = ("uber", "pedidosya")
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
MAX_BYTES = 25 * 1024 * 1024
_SIGNED_TTL = 540.0
_cache: dict[tuple[str, str, str], tuple[str, float]] = {}
_cache_lock = threading.Lock()

NOT_CONFIGURED = (
    "Evidencia sin configurar: falta la clave de la API de evidencia "
    "(cárguela en Credenciales o en EVIDENCIA_API_KEY). Las fotos de la app delivery no se consultaron."
)


class EvidenceError(RuntimeError):
    def __init__(self, message: str, *, auth: bool = False, status: int | None = None):
        super().__init__(message)
        self.auth = auth
        self.status = status


def normalize_order(numero_orden: str) -> str:
    value = (numero_orden or "").strip()
    if not value or len(value) > 80:
        raise ValueError("Falta el número de orden")
    return value


def media_path(agregador: str, numero_orden: str, image_id: str) -> str:
    from urllib.parse import quote
    return f"/api/evidence/{agregador}/media/{quote(image_id, safe='')}?numero_orden={quote(numero_orden, safe='')}"


def _allowed_host(settings: Settings) -> str:
    return urlsplit(settings.evidencia_url).hostname or ""


def _get_json(settings: Settings, client: httpx.Client, agregador: str, numero_orden: str) -> dict:
    try:
        r = client.get(
            settings.evidencia_url,
            params={"agregador": agregador, "numero_orden": numero_orden},
            headers={"x-evidencia-key": settings.evidencia_api_key},
        )
    except httpx.HTTPError as exc:
        raise EvidenceError(f"la API de evidencia no respondió ({type(exc).__name__})") from exc
    if r.status_code in (401, 403):
        raise EvidenceError("la API de evidencia rechazó la clave (401)", auth=True, status=r.status_code)
    try:
        body = r.json()
    except ValueError as exc:
        raise EvidenceError(f"la API de evidencia respondió HTTP {r.status_code} sin JSON", status=r.status_code) from exc
    if r.status_code != 200:
        msg = body.get("error") if isinstance(body, dict) else None
        raise EvidenceError(sanitize(msg) or f"la API de evidencia respondió HTTP {r.status_code}", status=r.status_code)
    if not isinstance(body, dict):
        raise EvidenceError("respuesta de evidencia con formato inesperado")
    return body


def list_images(settings: Settings, agregador: str, numero_orden: str, client: httpx.Client | None = None) -> dict:
    """Devuelve estado + imágenes con rutas del panel. Nunca la URL firmada."""
    if agregador not in AGGREGATORS:
        raise ValueError("Falta un agregador válido")
    numero_orden = normalize_order(numero_orden)
    if not settings.evidencia_api_key:
        return {"status": "not_configured", "error": NOT_CONFIGURED, "images": None}
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT)
    try:
        body = _get_json(settings, client, agregador, numero_orden)
    except EvidenceError as exc:
        return {"status": "error", "auth": exc.auth, "error": sanitize(str(exc)), "images": None}
    finally:
        if own:
            client.close()
    host = _allowed_host(settings)
    images = []
    now = time.monotonic()
    with _cache_lock:
        for row in body.get("images") or []:
            if not isinstance(row, dict):
                continue
            image_id, url, created = str(row.get("id") or ""), str(row.get("url") or ""), row.get("created_at")
            if not image_id or not url or urlsplit(url).hostname != host:
                continue
            _cache[(agregador, numero_orden, image_id)] = (url, now + _SIGNED_TTL)
            images.append({
                "id": image_id,
                "created_at": created,
                "url": media_path(agregador, numero_orden, image_id),
            })
    return {"status": "ok", "error": None, "images": images}


def _signed_url(settings: Settings, client: httpx.Client, agregador: str, numero_orden: str, image_id: str) -> str:
    key = (agregador, numero_orden, image_id)
    with _cache_lock:
        hit = _cache.get(key)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    result = list_images(settings, agregador, numero_orden, client=client)
    if result["status"] != "ok":
        raise EvidenceError(result["error"] or "evidencia no disponible", auth=bool(result.get("auth")))
    with _cache_lock:
        hit = _cache.get(key)
    if not hit:
        raise FileNotFoundError(image_id)
    return hit[0]


def fetch_image(settings: Settings, agregador: str, numero_orden: str, image_id: str,
                client: httpx.Client | None = None) -> tuple[bytes, str]:
    if agregador not in AGGREGATORS:
        raise ValueError("Falta un agregador válido")
    numero_orden = normalize_order(numero_orden)
    if not settings.evidencia_api_key:
        raise EvidenceError(NOT_CONFIGURED)
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT)
    try:
        url = _signed_url(settings, client, agregador, numero_orden, image_id)
        if urlsplit(url).hostname != _allowed_host(settings):
            raise EvidenceError("host de evidencia no permitido")
        try:
            r = client.get(url)
        except httpx.HTTPError as exc:
            raise EvidenceError(f"no se pudo bajar la imagen ({type(exc).__name__})") from exc
        if r.status_code != 200 or not r.content:
            raise EvidenceError(f"el bucket respondió HTTP {r.status_code}", status=r.status_code)
        if len(r.content) > MAX_BYTES:
            raise EvidenceError("imagen demasiado grande")
        ctype = r.headers.get("content-type", "image/jpeg").split(";")[0]
        if not ctype.startswith("image/"):
            ctype = "application/octet-stream"
        return r.content, ctype
    finally:
        if own:
            client.close()


def health(settings: Settings, client: httpx.Client | None = None) -> tuple[str, str]:
    """Consulta de solo lectura con un pedido inexistente: 200 = clave aceptada."""
    if not settings.evidencia_api_key:
        return "missing", "Falta EVIDENCIA_API_KEY en el servidor"
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT)
    try:
        _get_json(settings, client, "uber", "__health_panel__")
        return "configured", "La API de evidencia aceptó la clave"
    except EvidenceError as exc:
        return ("expired" if exc.auth else "unknown"), sanitize(str(exc))
    finally:
        if own:
            client.close()
