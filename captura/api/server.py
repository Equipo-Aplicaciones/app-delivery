"""API local de evidencia.

La app solo sube. Otro proyecto lee. Son dos claves distintas y las dos viajan
en `Authorization: Bearer`, nunca en la URL. La de lectura no se copia a la app.

  GET  /healthz
  POST /v1/evidencia                          clave de subida (JPEG o GIF animado)
  GET  /v1/evidencia?agregador=&numero_orden= clave de lectura
  GET  /v1/evidencia/{id}                     clave de lectura
  GET  /v1/evidencia/{id}/imagen              clave de lectura
  DELETE /v1/evidencia/{id}                   clave de subida, solo fotos recientes
"""

from __future__ import annotations

import hmac
import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

AGGREGATORS = {"uber", "pedidosya", "rappi"}
MAX_BYTES = 8_000_000
# La tienda puede borrar o cambiar las fotos del día. El panel limita al día de Chile;
# aquí, como resguardo, nunca se borra una foto con más de 36 horas (ya es evidencia).
DELETE_MAX_AGE = timedelta(hours=36)
HOST = os.environ.get("EVIDENCIA_HOST", "0.0.0.0")
PORT = int(os.environ.get("EVIDENCIA_PORT", "8787"))
ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("EVIDENCIA_DATA", ROOT / "data"))
FILES = DATA / "files"
DB_PATH = DATA / "evidencia.sqlite"
READ_PATH = DATA / "read-key"
UPLOAD_PATH = DATA / "upload-key"

_lock = threading.Lock()
_name_re = re.compile(r'name="([^"]+)"')
_file_re = re.compile(r'filename="([^"]*)"')


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    FILES.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS evidencia (
          id TEXT PRIMARY KEY,
          agregador TEXT NOT NULL CHECK (agregador IN ('uber', 'pedidosya', 'rappi')),
          numero_orden TEXT NOT NULL CHECK (
            length(numero_orden) > 0 AND numero_orden = trim(numero_orden)
          ),
          storage_name TEXT NOT NULL UNIQUE,
          content_type TEXT NOT NULL,
          byte_size INTEGER NOT NULL,
          created_at TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS evidencia_clave_idx
        ON evidencia (agregador, numero_orden, created_at)
        """
    )
    db.commit()
    return db


DB = connect()


def load_key(path: Path) -> str:
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    path.parent.mkdir(parents=True, exist_ok=True)
    key = os.urandom(32).hex()
    path.write_text(key + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return key


def read_key() -> str:
    return load_key(READ_PATH)


def upload_key() -> str:
    return load_key(UPLOAD_PATH)


def same_secret(provided: str, expected: str) -> bool:
    if not provided or len(provided) != len(expected):
        return False
    return hmac.compare_digest(provided, expected)


def presented_key(headers) -> str:
    auth = headers.get("Authorization") or ""
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip()
    return ""


def role_of(headers) -> str | None:
    provided = presented_key(headers)
    if same_secret(provided, read_key()):
        return "read"
    if same_secret(provided, upload_key()):
        return "upload"
    return None


def image_url(base: str, image_id: str) -> str:
    return f"{base}/v1/evidencia/{quote(image_id)}/imagen"


def parse_multipart(content_type: str, body: bytes) -> dict[str, dict]:
    marker = "boundary="
    if marker not in content_type:
        return {}
    boundary = content_type.split(marker, 1)[1].split(";", 1)[0].strip().strip('"')
    if not boundary:
        return {}
    fields: dict[str, dict] = {}
    for chunk in body.split(b"--" + boundary.encode()):
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        if chunk in (b"", b"--", b"--\r\n") or chunk.startswith(b"--"):
            continue
        header_blob, sep, data = chunk.partition(b"\r\n\r\n")
        if not sep:
            continue
        if data.endswith(b"\r\n"):
            data = data[:-2]
        name = None
        filename = None
        for line in header_blob.decode("utf-8", "replace").split("\r\n"):
            if not line.lower().startswith("content-disposition"):
                continue
            found = _name_re.search(line)
            named = _file_re.search(line)
            name = found.group(1) if found else None
            filename = named.group(1) if named else None
        if name:
            fields[name] = {"filename": filename, "data": data}
    return fields


def valid_order(raw: str) -> str | None:
    value = raw.strip()
    if not value or value != raw.strip() or len(value) > 80:
        return None
    if any(ch in value for ch in "/\\\x00"):
        return None
    return value


def media_type(blob: bytes) -> tuple[str, str] | None:
    """(content_type, extensión) de la evidencia aceptada: foto JPEG o GIF animado de la tienda."""
    if blob.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if blob.startswith(b"GIF87a") or blob.startswith(b"GIF89a"):
        return "image/gif", "gif"
    return None


def insert_photo(agregador: str, numero_orden: str, blob: bytes) -> dict:
    content_type, ext = media_type(blob) or ("image/jpeg", "jpg")
    image_id = str(uuid.uuid4())
    storage_name = f"{image_id}.{ext}"
    created = now_iso()
    path = FILES / storage_name
    path.write_bytes(blob)
    try:
        with _lock:
            DB.execute(
                """
                INSERT INTO evidencia (
                  id, agregador, numero_orden, storage_name, content_type, byte_size, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (image_id, agregador, numero_orden, storage_name, content_type, len(blob), created),
            )
            DB.commit()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {"saved": True, "id": image_id, "created_at": created}


def list_photos(agregador: str, numero_orden: str) -> list[sqlite3.Row]:
    with _lock:
        return list(
            DB.execute(
                """
                SELECT id, created_at, agregador, numero_orden, byte_size
                FROM evidencia
                WHERE agregador = ? AND numero_orden = ?
                ORDER BY created_at ASC, id ASC
                """,
                (agregador, numero_orden),
            )
        )


def get_photo(image_id: str) -> sqlite3.Row | None:
    with _lock:
        return DB.execute("SELECT * FROM evidencia WHERE id = ?", (image_id,)).fetchone()


def delete_photo(image_id: str) -> str:
    """Borra la fila y el archivo. Devuelve 'ok', 'no_existe' o 'antigua'."""
    with _lock:
        row = DB.execute(
            "SELECT storage_name, created_at FROM evidencia WHERE id = ?", (image_id,)
        ).fetchone()
        if row is None:
            return "no_existe"
        try:
            created = datetime.strptime(row["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return "antigua"
        if datetime.now(timezone.utc) - created > DELETE_MAX_AGE:
            return "antigua"
        DB.execute("DELETE FROM evidencia WHERE id = ?", (image_id,))
        DB.commit()
    (FILES / row["storage_name"]).unlink(missing_ok=True)
    return "ok"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        path = urlparse(self.path).path
        print(f"{self.address_string()} {self.command} {path}")

    def base(self) -> str:
        host = self.headers.get("Host") or f"127.0.0.1:{PORT}"
        return f"http://{host}"

    def send_json(self, body: dict, status: int = 200) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def require_role(self, expected: str) -> bool:
        if role_of(self.headers) == expected:
            return True
        self.send_json({"error": "no autorizado"}, 401)
        return False

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self.send_json({"ok": True})
            return
        if parsed.path == "/v1/evidencia":
            if not self.require_role("read"):
                return
            self.handle_list(parse_qs(parsed.query))
            return
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) == 3 and parts[0] == "v1" and parts[1] == "evidencia":
            if not self.require_role("read"):
                return
            self.handle_detail(parts[2])
            return
        if len(parts) == 4 and parts[:2] == ["v1", "evidencia"] and parts[3] == "imagen":
            if not self.require_role("read"):
                return
            self.handle_image(parts[2])
            return
        self.send_json({"error": "no encontrado"}, 404)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/v1/evidencia":
            self.send_json({"error": "no encontrado"}, 404)
            return
        if not self.require_role("upload"):
            return
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0 or length > MAX_BYTES + 64_000:
            self.send_json({"error": "Falta la foto del pedido"}, 400)
            return
        body = self.rfile.read(length)
        fields = parse_multipart(self.headers.get("Content-Type") or "", body)
        agregador = fields.get("agregador", {}).get("data", b"").decode("utf-8", "replace").strip()
        numero = valid_order(fields.get("numero_orden", {}).get("data", b"").decode("utf-8", "replace"))
        blob = fields.get("imagen", {}).get("data", b"")
        if agregador not in AGGREGATORS:
            self.send_json({"error": "Falta un agregador válido"}, 400)
            return
        if not numero:
            self.send_json({"error": "Falta el número de orden"}, 400)
            return
        if media_type(blob) is None or len(blob) > MAX_BYTES:
            self.send_json({"error": "Falta la foto del pedido"}, 400)
            return
        try:
            saved = insert_photo(agregador, numero, blob)
        except Exception:
            self.send_json({"error": "La base no recibió la imagen"}, 500)
            return
        self.send_json(saved, 201)

    def do_DELETE(self) -> None:
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        if not (len(parts) == 3 and parts[:2] == ["v1", "evidencia"]):
            self.send_json({"error": "no encontrado"}, 404)
            return
        if not self.require_role("upload"):
            return
        result = delete_photo(parts[2])
        if result == "ok":
            self.send_json({"deleted": True})
        elif result == "no_existe":
            self.send_json({"error": "No existe esa foto"}, 404)
        else:
            self.send_json({"error": "Solo se pueden borrar fotos del día"}, 409)

    def handle_list(self, query: dict[str, list[str]]) -> None:
        agregador = (query.get("agregador") or [""])[0]
        numero = valid_order((query.get("numero_orden") or [""])[0])
        if agregador not in AGGREGATORS:
            self.send_json({"error": "Falta un agregador válido"}, 400)
            return
        if not numero:
            self.send_json({"error": "Falta el número de orden"}, 400)
            return
        rows = list_photos(agregador, numero)
        images = [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "agregador": row["agregador"],
                "numero_orden": row["numero_orden"],
                "url": image_url(self.base(), row["id"]),
            }
            for row in rows
        ]
        self.send_json({"images": images})

    def handle_detail(self, image_id: str) -> None:
        row = get_photo(image_id)
        if row is None:
            self.send_json({"error": "no encontrado"}, 404)
            return
        self.send_json(
            {
                "id": row["id"],
                "agregador": row["agregador"],
                "numero_orden": row["numero_orden"],
                "created_at": row["created_at"],
                "content_type": row["content_type"],
                "byte_size": row["byte_size"],
                "imagen_url": image_url(self.base(), row["id"]),
            }
        )

    def handle_image(self, image_id: str) -> None:
        row = get_photo(image_id)
        if row is None:
            self.send_json({"error": "no encontrado"}, 404)
            return
        path = FILES / row["storage_name"]
        if not path.is_file():
            self.send_json({"error": "No se pudo consultar la evidencia"}, 500)
            return
        blob = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", row["content_type"] or "image/jpeg")
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Cache-Control", "private, max-age=600")
        self.end_headers()
        self.wfile.write(blob)


def main() -> None:
    read_key()
    upload_key()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"evidencia escuchando en {HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
