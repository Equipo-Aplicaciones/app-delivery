import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

JPEG = b"\xff\xd8\xff\xd9"


def start(data: Path):
    os.environ["EVIDENCIA_DATA"] = str(data)
    os.environ["EVIDENCIA_PORT"] = "0"
    import importlib
    import server

    importlib.reload(server)
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return server, httpd


def call(httpd, method, path, key=None, data=None, headers=None):
    req_headers = dict(headers or {})
    if key:
        req_headers["Authorization"] = f"Bearer {key}"
    port = httpd.server_address[1]
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers=req_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as res:
            body = res.read()
            return res.status, dict(res.headers), body
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read()


def multipart(agregador, numero, blob):
    boundary = "----evidencia"
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="agregador"\r\n\r\n{agregador}\r\n',
        f'--{boundary}\r\nContent-Disposition: form-data; name="numero_orden"\r\n\r\n{numero}\r\n',
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="imagen"; filename="pedido.jpg"\r\n'
            "Content-Type: image/jpeg\r\n\r\n"
        ).encode()
        + blob
        + f"\r\n--{boundary}--\r\n".encode(),
    ]
    body = b""
    for part in parts:
        body += part if isinstance(part, bytes) else part.encode()
    return body, f"multipart/form-data; boundary={boundary}"


class EvidenciaApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server, self.httpd = start(Path(self.tmp.name))
        self.upload = self.server.upload_key()
        self.read = self.server.read_key()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def post(self, agregador="uber", numero="88", blob=JPEG):
        body, content_type = multipart(agregador, numero, blob)
        return call(
            self.httpd,
            "POST",
            "/v1/evidencia",
            key=self.upload,
            data=body,
            headers={"Content-Type": content_type},
        )

    def test_guarda_y_lista_solo_esa_pareja(self):
        status, _, raw = self.post()
        self.assertEqual(status, 201)
        saved = json.loads(raw)
        self.assertTrue(saved["saved"])
        self.post(agregador="rappi", numero="88")
        self.post(agregador="uber", numero="88")
        status, _, raw = call(
            self.httpd,
            "GET",
            "/v1/evidencia?agregador=uber&numero_orden=88",
            key=self.read,
        )
        self.assertEqual(status, 200)
        images = json.loads(raw)["images"]
        self.assertEqual(len(images), 2)
        self.assertTrue(all(row["agregador"] == "uber" for row in images))
        self.assertNotIn("?", images[0]["url"])
        status, _, _ = call(self.httpd, "GET", url_path(images[0]["url"]), key=self.upload)
        self.assertEqual(status, 401)
        status, headers, blob = call(self.httpd, "GET", url_path(images[0]["url"]), key=self.read)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/jpeg")
        self.assertEqual(blob, JPEG)

    def test_otra_orden_no_mezcla(self):
        self.post(numero="15")
        status, _, raw = call(
            self.httpd,
            "GET",
            "/v1/evidencia?agregador=uber&numero_orden=16",
            key=self.read,
        )
        self.assertEqual(json.loads(raw)["images"], [])
        self.assertEqual(status, 200)

    def test_sin_clave_no_entra(self):
        status, _, _ = call(self.httpd, "GET", "/v1/evidencia?agregador=uber&numero_orden=88")
        self.assertEqual(status, 401)

    def test_rechaza_agregador_y_foto_vacia(self):
        status, _, raw = self.post(agregador="pedya")
        self.assertEqual(status, 400)
        self.assertIn("agregador", json.loads(raw)["error"])
        status, _, _ = self.post(blob=b"no-es-jpeg")
        self.assertEqual(status, 400)

    def test_ficha_para_otro_proyecto(self):
        _, _, raw = self.post(agregador="pedidosya", numero="PY-9")
        image_id = json.loads(raw)["id"]
        denied, _, _ = call(self.httpd, "GET", f"/v1/evidencia/{image_id}", key=self.upload)
        self.assertEqual(denied, 401)
        posted, _, _ = self.post(agregador="uber", numero="NO-READ")
        self.assertEqual(posted, 201)
        # The helper above used the upload key. A read key must not be able to store.
        body, content_type = multipart("uber", "NO-READ-2", JPEG)
        rejected, _, _ = call(
            self.httpd,
            "POST",
            "/v1/evidencia",
            key=self.read,
            data=body,
            headers={"Content-Type": content_type},
        )
        self.assertEqual(rejected, 401)
        status, _, raw = call(self.httpd, "GET", f"/v1/evidencia/{image_id}", key=self.read)
        body = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertEqual(body["agregador"], "pedidosya")
        self.assertEqual(body["numero_orden"], "PY-9")
        path = url_path(body["imagen_url"])
        status, _, blob = call(self.httpd, "GET", path, key=self.read)
        self.assertEqual(status, 200)
        self.assertEqual(blob, JPEG)
        status, _, _ = call(self.httpd, "GET", path)
        self.assertEqual(status, 401)


def url_path(url: str) -> str:
    return "/" + url.split("/", 3)[3]


if __name__ == "__main__":
    unittest.main()
