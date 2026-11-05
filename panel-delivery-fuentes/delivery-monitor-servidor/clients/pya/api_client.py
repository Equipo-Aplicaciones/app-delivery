"""Read-only client for the PedidosYa (Delivery Hero) partner portal.

Auth: PYA_USER / PYA_PASS env vars (login), or PYA_ACCESS_TOKEN (+ optional
PYA_REFRESH_TOKEN) env vars taken from a logged-in browser session.
Only GET requests and auth POSTs are ever issued. Never pauses/edits stores.
"""
import os, sys, json, uuid, base64, time, collections
import requests

AUTH = "https://partner-auth.us.prd.portal.restaurant/auth/v5"
VSS = "https://vss.us.restaurant-partners.com/api/v2"
VTS = "https://vts.us.restaurant-partners.com/opening-times/v1"
ORIGIN = "https://portal-app.pedidosya.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
AUTH_APP_VERSION = "3.56.3"   # authentication plugin version (version.json)
SHELL_APP_VERSION = "2.8.28"


class PyaError(Exception):
    pass


def _jwt_claims(tok):
    try:
        p = tok.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
    except Exception:
        return {}


class PedidosYaClient:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Origin": ORIGIN,
                               "Referer": ORIGIN + "/",
                               "Accept": "application/json, text/plain, */*"})
        self.device = os.environ.get("PYA_DEVICE_UUID") or str(uuid.uuid4())
        self.access = os.environ.get("PYA_ACCESS_TOKEN")
        self.refresh = os.environ.get("PYA_REFRESH_TOKEN")
        self.device_token = os.environ.get("PYA_DEVICE_TOKEN", "")
        self.profile = None
        tf = os.path.expanduser("~/.pya_tokens.json")
        if not self.access and os.path.exists(tf):
            try:
                t = json.load(open(tf))
                self.access, self.refresh = t.get("access"), t.get("refresh")
                self.device_token = t.get("device") or ""
            except Exception:
                pass

    # ---------- auth ----------
    def login(self, username=None, password=None):
        if self.access and not (username or password):
            return  # token supplied via env
        u = username or os.environ.get("PYA_USER")
        p = password or os.environ.get("PYA_PASS")
        if not u or not p:
            raise PyaError("Set PYA_USER/PYA_PASS or PYA_ACCESS_TOKEN")
        h = {"X-App-Name": "one-web", "X-App-Version": AUTH_APP_VERSION}
        # Same payload/endpoint the portal's login form sends (login-two-step).
        r = self.s.post(f"{AUTH}/login-two-step", headers=h, timeout=30,
                        json={"username": u, "password": p, "type": "password"})
        if r.status_code == 403 and "otp_triggered" in r.text:
            open(os.path.expanduser("~/.pya_otp_raw.txt"),"w").write(r.text+"\n"+str(dict(r.headers)))
            body = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
            flow = body.get("flowId") or body.get("flow_id") or (body.get("details") or [{}])[0].get("flowId") if isinstance(body, dict) else None
            flow = flow or r.headers.get("x-2fa-request-id")
            import re as _re
            if not flow:
                m = _re.search(r'"flow_?[iI]d"\s*:\s*"([^"]+)"', r.text); flow = m and m.group(1)
            open(os.path.expanduser("~/.pya_flow"), "w").write(flow or "")
            raise PyaError("OTP_REQUIRED (flow saved: %s)" % bool(flow))
        if r.status_code != 200:
            raise PyaError(f"Login failed HTTP {r.status_code}: {r.text[:200]} "
                           "(the portal shows this as 'verify your email and password')")
        d = r.json()
        self.access = d.get("access_token") or d.get("keymaker", {}).get("access_token")
        self.refresh = d.get("refresh_token") or d.get("keymaker", {}).get("refresh_token")
        self.device_token = d.get("device_token", "")
        self.profile = d.get("profile")

    def verify_otp(self, code, email):
        flow = open(os.path.expanduser("~/.pya_flow")).read().strip()
        h = {"X-App-Name": "one-web", "X-App-Version": AUTH_APP_VERSION}
        r = self.s.post(f"{AUTH}/login-two-step/verify", headers=h, timeout=30,
                        json={"flowId": flow, "otpCode": code, "email": email})
        if r.status_code != 200:
            raise PyaError(f"OTP verify failed HTTP {r.status_code}: {r.text[:200]}")
        d = r.json()
        self.access = d.get("access_token"); self.refresh = d.get("refresh_token")
        self.device_token = d.get("device_token", ""); self.profile = d.get("profile")
        self.save_tokens()

    def save_tokens(self):
        import json as _j
        f = os.path.expanduser("~/.pya_tokens.json")
        fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.write(fd, _j.dumps({"access": self.access, "refresh": self.refresh, "device": self.device_token}).encode()); os.close(fd)

    def _refresh(self):
        if not self.refresh:
            return False
        r = self.s.post(f"{AUTH}/token-refresh", timeout=30,
                        headers={"X-App-Name": "one-web", "X-App-Version": AUTH_APP_VERSION,
                                 "X-RPS-Device": self.device},
                        json={"refresh_token": self.refresh, "device_token": self.device_token})
        if r.status_code != 200:
            return False
        d = r.json()
        self.access, self.refresh = d["access_token"], d.get("refresh_token", self.refresh)
        self.profile = d.get("profile") or self.profile
        if (self.profile or {}).get("accounts"):  # jerarquía de cuentas (sin secretos) para finanzas
            import json as _j
            open(os.path.expanduser("~/.pya_accounts.json"), "w").write(_j.dumps(self.profile["accounts"]))
        self.device_token = d.get("device_token") or self.device_token
        self.save_tokens()
        return True

    def token_expires_in(self):
        exp = _jwt_claims(self.access or "").get("exp")
        return None if exp is None else int(exp - time.time())

    def _get(self, url, extra=None, params=None):
        if not self.access:
            self.login()
        exp = self.token_expires_in()
        if exp is not None and exp < 60:
            self._refresh()
        for attempt in (0, 1):
            claims = _jwt_claims(self.access)
            h = {"Authorization": f"Bearer {self.access}",
                 "X-App-Name": "oneweb", "X-RPS-Client-App-Name": "OneWeb",
                 "X-App-Version": SHELL_APP_VERSION, "X-RPS-Device": self.device,
                 "X-Is-Impersonation": "false"}
            if claims.get("sub"):
                h["X-User-Id"] = str(claims["sub"])
            h.update(extra or {})
            r = self.s.get(url, headers=h, params=params, timeout=30)
            if r.status_code == 401 and attempt == 0 and self._refresh():
                continue
            if r.status_code != 200:
                raise PyaError(f"GET {url} -> HTTP {r.status_code}: {r.text[:200]}")
            return r.json() if r.text else None

    # ---------- data (read-only) ----------
    def status_counts(self):
        return self._get(f"{VSS}/vendors/status/counts")

    def _status_list(self):
        d = self._get(f"{VSS}/vendors/status")
        if isinstance(d, dict):
            for k in ("items", "vendors", "data", "statuses"):
                if isinstance(d.get(k), list):
                    return d[k]
            return [d]
        return d or []

    def list_stores(self):
        out = []
        for v in self._status_list():
            ge, pid = v.get("globalEntityId"), v.get("platformVendorId")
            out.append({"id": f"{ge};{pid}", "global_entity_id": ge, "vendor_id": pid,
                        "name": v.get("name") or v.get("vendorName"),
                        "state": v.get("state") or v.get("availabilityState", "UNKNOWN"),
                        "raw": v})
        return out

    def get_store_status(self, store_id):
        """store_id like 'PY_CL;616753'. Returns status + delivery schedule."""
        st = next((s for s in self.list_stores() if s["id"] == store_id), None)
        h = {"x-client-id": "vendor-portal-web", "X-RPS-Client-App-Name": "oneweb",
             "X-vendor-id": store_id}
        cal = self._get(f"{VTS}/vendor/{store_id}/calendars/DELIVERY", h)
        special = self._get(f"{VTS}/vendor/{store_id}/schedules/DELIVERY", h)
        return {"id": store_id, "state": st and st["state"], "status": st and st["raw"],
                "calendars": cal, "special_schedules": special}


def main():
    c = PedidosYaClient()
    try:
        c.login()
        stores = c.list_stores()
    except PyaError as e:
        print("ERROR:", e, file=sys.stderr)
        return 1
    print(f"Stores: {len(stores)}  (token expires in {c.token_expires_in()}s)")
    for k, n in collections.Counter(s["state"] for s in stores).most_common():
        print(f"  {k}: {n}")
    if len(sys.argv) > 1:
        print(json.dumps(c.get_store_status(sys.argv[1]), indent=2, ensure_ascii=False)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
