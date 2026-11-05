"""Read-only client for Uber Eats Manager (merchants.ubereats.com) store status.

Auth: Cookie from ~/.uber_cookie (preferred) or env UBER_COOKIE (never hardcoded/logged).
Only calls read endpoints: queryStores, getRestaurantOrderabilityStatus, getStores.
No mutations (setOrderability/pause/hours/menu) are implemented, by design.
"""
import json, os, sys, datetime
import requests

BASE = "https://merchants.ubereats.com/manager/api/"
ALLOWED = {"queryStores", "getRestaurantOrderabilityStatus", "getStores"}  # read-only whitelist


COOKIE_FILE = os.path.expanduser("~/.uber_cookie")

def load_cookie(cookie=None):
    """Cookie file (~/.uber_cookie) first, then env UBER_COOKIE. Never log the value."""
    if cookie:
        return cookie.strip()
    if os.path.isfile(COOKIE_FILE):
        val = open(COOKIE_FILE, encoding="utf-8").read().strip()
        if val:
            return val
    val = (os.environ.get("UBER_COOKIE") or "").strip()
    if val:
        return val
    raise RuntimeError(
        "No Uber cookie: falta ~/.uber_cookie o env UBER_COOKIE. "
        "Corre python3 refresh_uber_cookie.py o pega una cookie nueva."
    )

def save_cookie(cookie):
    """Write cookie atomically with mode 0600. Never prints the value."""
    cookie = (cookie or "").strip()
    if not cookie or "=" not in cookie:
        raise RuntimeError("cookie vacía o inválida")
    path = COOKIE_FILE
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(cookie)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path

class UberEatsClient:
    def __init__(self, cookie=None):
        cookie = load_cookie(cookie)
        self.s = requests.Session()
        self.s.headers.update({
            "content-type": "application/json", "accept": "*/*",
            "origin": "https://merchants.ubereats.com",
            "referer": "https://merchants.ubereats.com/manager/stores",
            "x-csrf-token": "x",  # static value used by the web app
            "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36",
            "cookie": cookie,
        })

    def _post(self, op, body):
        if op not in ALLOWED:
            raise PermissionError(f"{op} not in read-only whitelist")
        r = self.s.post(BASE + op, params={"localeCode": "en"}, json=body, timeout=30, allow_redirects=False)
        if r.status_code in (301, 302, 401, 403) or "json" not in r.headers.get("content-type", ""):
            raise RuntimeError(f"{op}: HTTP {r.status_code} - session cookie likely expired")
        j = r.json()
        if j.get("status") != "success":
            raise RuntimeError(f"{op}: status={j.get('status')}")
        return j["data"]

    def list_stores(self, limit=500):
        """[{id,name,city,address,onboarding_status}] for all stores the user manages."""
        body = {"filter": {"composite": {"logicalOperator": "LOGICAL_OPERATOR_AND", "filters": [
            {"predicate": {"attributeName": "permission", "operator": "FILTER_OPERATOR_EQUAL",
                           "operand": {"stringVal": "merchant_manager_home_view"}}},
            {"predicate": {"attributeName": "onboarding_status", "operator": "FILTER_OPERATOR_NOT_EQUAL",
                           "operand": {"stringVal": "lost"}}}]}},
            "pagination": {"offset": 0, "limit": limit}, "scopes": [], "sort": []}
        out, offset = [], 0
        while True:
            body["pagination"]["offset"] = offset
            d = self._post("queryStores", body)
            out += [{"id": s["storeId"], "name": s.get("storeName"), "city": s.get("city"),
                     "address": s.get("address"), "onboarding_status": s.get("onboardingStatus")}
                    for s in d.get("stores", [])]
            total = d.get("pagination", {}).get("total", len(out))
            if not d.get("stores") or len(out) >= total:
                return out
            offset = len(out)

    @staticmethod
    def _classify(x):
        if not x.get("isVisible", True):
            return "not_visible"
        if x.get("onlineStatus") == "ORDERABLE":
            return "open"
        if x.get("pausedUntil") or x.get("statusReason") in ("Paused", "Busy"):
            return "paused"
        return "closed"

    def get_statuses(self, store_ids):
        res = {}
        for i in range(0, len(store_ids), 100):
            for x in self._post("getRestaurantOrderabilityStatus", {"restaurantUuids": store_ids[i:i + 100]}):
                hours = ((x.get("denormalizedHours") or {}).get("denormalizedMenuHours") or {})
                res[x["uuid"]] = {
                    "id": x["uuid"], "state": self._classify(x),
                    "online_status": x.get("onlineStatus"), "status_reason": x.get("statusReason"),
                    "raw_reason": (x.get("updateDetails") or {}).get("rawReason"),
                    "changed_by": (x.get("updateDetails") or {}).get("caller"),
                    "is_visible": x.get("isVisible"), "is_menu_open": x.get("isMenuOpen"),
                    "paused_until": x.get("pausedUntil"), "busy_until": x.get("busyUntil"),
                    "next_open": x.get("nextOpenTime"), "next_close": x.get("nextCloseTime"),
                    "updated_at": x.get("orderabilityStateUpdatedAt"),
                    "menu_hours": {k: v.get("menuHourIntervals") for k, v in hours.items()},
                    "hours_overrides": x.get("operatingHoursOverrides"),
                }
        return res

    def get_store_status(self, store_id):
        return self.get_statuses([store_id]).get(store_id)


if __name__ == "__main__":
    c = UberEatsClient()
    stores = c.list_stores()
    st = c.get_statuses([s["id"] for s in stores])
    from collections import Counter
    print(len(stores), "stores", dict(Counter(v["state"] for v in st.values())))
    for s in stores:
        v = st.get(s["id"], {})
        if v.get("state") != "open":
            print(f'{v.get("state"):12} {s["name"]} reason={v.get("raw_reason")} paused_until={v.get("paused_until")}')
