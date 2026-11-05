# uber.py — Uber Eats Manager (actualizado 2026-11-05)

Ruta: `/workspace/uber_client/uber.py`

Auth: `~/.uber_cookie` (preferido) o env `UBER_COOKIE`. Renovar: `refresh_uber_cookie.py`.

```python
#!/usr/bin/env python3
"""CLI Uber Eats Manager (Tarragona). Cookie desde ~/.uber_cookie o env UBER_COOKIE (nunca se imprime).
Escrituras (pause/activate/soldout/instock) exigen --yes; usar --dry-run para ver el payload."""
import argparse, copy, csv, datetime as dt, json, os, sys
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_client import UberEatsClient
import requests

TZ = ZoneInfo("America/Santiago")
API = "https://merchants.ubereats.com/manager/api/"
MM = "https://merchants.ubereats.com/manager/menumaker/api/"
GQL = "https://merchants.ubereats.com/manager/graphql"
STATE = os.path.expanduser("~/.uber_state")
INDEFINITE = "2243-10-17T00:00:00.000Z"   # constante 'le' de Menu Maker (hide_indefinitely)
DURATIONS = {"10": "_10", "20": "_20", "30": "_30", "60": "_60", "rest_of_day": "REST_OF_DAY"}
REASONS = ["CLOSING_EARLY", "PROBLEM_IN_RESTAURANT", "OUT_OF_ITEM", "OTHER"]
Q_BUSY = """mutation SetStoresBusy($stores: [SetStoresBusyInput!]!) {
  setStoresBusy(stores: $stores) { success { orgUUID statusReason } failure { orgUUID code message } } }"""
Q_ONLINE = """mutation SetStoresOnline($orgUUIDs: [ID]!) {
  setStoresOnline(orgUUIDs: $orgUUIDs) { success { orgUUID statusReason } failure { orgUUID code message } } }"""

_c = None
def cli():
    global _c
    if _c is None: _c = UberEatsClient()
    return _c

def api(op, body):
    r = cli().s.post(API + op, params={"localeCode": "en"}, json=body, timeout=120, allow_redirects=False)
    if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
        raise RuntimeError(f"{op}: HTTP {r.status_code} (¿cookie vencida?)")
    j = r.json()
    if j.get("status") != "success": raise RuntimeError(f"{op}: {str(j.get('data'))[:200]}")
    return j["data"]

def mm(op, sid, body):
    r = cli().s.post(MM + op, params={"localeCode": "en", "restaurantUUID": sid}, json=body, timeout=120, allow_redirects=False)
    j = r.json()
    if j.get("status") != "success": raise RuntimeError(f"{op}: {str(j)[:200]}")
    return j["data"]

def gql(name, query, variables):
    r = cli().s.post(GQL, json={"operationName": name, "query": query, "variables": variables}, timeout=60, allow_redirects=False)
    j = r.json()
    if j.get("errors"): raise RuntimeError(f"{name}: {str(j['errors'])[:300]}")
    return j["data"]

def pmap(fn, xs, n=5):
    import time
    def safe(x):
        for k in range(4):
            try: return fn(x)
            except Exception as e:
                err = e; time.sleep(1.5 * (k + 1))
        return {"_error": str(err)[:200], "_x": x}
    with ThreadPoolExecutor(n) as ex: return list(ex.map(safe, xs))

# ---------- tiendas ----------
def stores(sel=None, ids=None):
    allst = cli().list_stores()
    out = allst
    if ids: out = [s for s in allst if s["id"] in ids]
    elif sel: out = [s for s in allst if any(x.lower() in (s["name"] or "").lower() for x in sel)]
    return out

def cl(ts):
    """ISO/epoch -> 'YYYY-MM-DD HH:MM' hora Chile"""
    if not ts or ts in ("0", 0): return ""
    try:
        if isinstance(ts, (int, float)) or str(ts).isdigit():
            v = float(ts); v = v / 1000 if v > 1e11 else v
            d = dt.datetime.fromtimestamp(v, dt.timezone.utc)
        else: d = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d.astimezone(TZ).strftime("%Y-%m-%d %H:%M")
    except Exception: return str(ts)

# ---------- salida ----------
def emit(rows, a, cols=None, title=None):
    if a.json: print(json.dumps(rows, ensure_ascii=False, indent=1, default=str)); return
    cols = cols or (list(rows[0].keys()) if rows else [])
    if a.csv:
        w = csv.DictWriter(sys.stdout, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows); return
    if title: print(title)
    if not rows: print("(sin filas)"); return
    wid = {c: min(45, max(len(c), *(len(str(r.get(c, ""))) for r in rows))) for c in cols}
    print("  ".join(c.ljust(wid[c]) for c in cols)); print("  ".join("-" * wid[c] for c in cols))
    for r in rows: print("  ".join(str(r.get(c, ""))[:45].ljust(wid[c]) for c in cols))

def need_confirm(a, payload):
    if a.dry_run or not a.yes:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        print("\n[DRY-RUN] No se ejecutó nada." + ("" if a.dry_run else " Agrega --yes para ejecutar."), file=sys.stderr)
        return False
    return True

# ---------- 1. pausa / activación ----------
def cmd_pause(a):
    st = stores(a.store, a.id)
    if not st: sys.exit("Ninguna tienda coincide")
    sts = cli().get_statuses([s["id"] for s in st])
    payload = {"operationName": "SetStoresBusy", "query": Q_BUSY, "variables": {"stores": [
        {"orgUUID": s["id"], "timezone": "America/Santiago", "duration": DURATIONS[a.duration],
         "reason": a.reason, "otherInfo": a.comment or ""} for s in st]}}
    print(f"Pausar {len(st)} tienda(s): " + ", ".join(s["name"] for s in st), file=sys.stderr)
    if not need_confirm(a, payload): return
    d = gql("SetStoresBusy", Q_BUSY, payload["variables"])["setStoresBusy"]
    emit([{"id": x["orgUUID"], "result": "ok", "detail": x.get("statusReason")} for x in d.get("success") or []] +
         [{"id": x["orgUUID"], "result": "fail", "detail": x.get("message")} for x in d.get("failure") or []], a)

def cmd_activate(a):
    st = stores(a.store, a.id)
    if not st: sys.exit("Ninguna tienda coincide")
    payload = {"operationName": "SetStoresOnline", "query": Q_ONLINE, "variables": {"orgUUIDs": [s["id"] for s in st]}}
    print(f"Activar {len(st)} tienda(s): " + ", ".join(s["name"] for s in st), file=sys.stderr)
    if not need_confirm(a, payload): return
    d = gql("SetStoresOnline", Q_ONLINE, payload["variables"])["setStoresOnline"]
    emit([{"id": x["orgUUID"], "result": "ok", "detail": x.get("statusReason")} for x in d.get("success") or []] +
         [{"id": x["orgUUID"], "result": "fail", "detail": x.get("message")} for x in d.get("failure") or []], a)

# ---------- 2. monitoreo ----------
def cmd_monitor(a):
    st = stores(a.store, a.id); names = {s["id"]: s["name"] for s in st}
    sts = cli().get_statuses(list(names))
    rows = sorted([{"store": names[i], "state": v["state"], "reason": v.get("raw_reason") or v.get("status_reason"),
                    "paused_until": cl(v.get("paused_until") or v.get("busy_until")), "next_open": cl(v.get("next_open")),
                    "next_close": cl(v.get("next_close")), "id": i} for i, v in sts.items()], key=lambda r: (r["state"], r["store"]))
    os.makedirs(STATE, exist_ok=True); snap = os.path.join(STATE, "monitor_snapshot.json")
    if a.changes:
        prev = json.load(open(snap)) if os.path.exists(snap) else {}
        diff = [{"store": r["store"], "before": prev.get(r["id"], {}).get("state", "(nuevo)"), "now": r["state"],
                 "reason": r["reason"], "id": r["id"]} for r in rows if prev.get(r["id"], {}).get("state") != r["state"]]
        emit(diff, a, title=f"Cambios desde snapshot ({len(diff)}):")
    else:
        from collections import Counter
        emit(rows if not a.only else [r for r in rows if r["state"] in a.only], a,
             ["store", "state", "reason", "paused_until", "next_open", "next_close"],
             title=f"{dt.datetime.now(TZ):%Y-%m-%d %H:%M} (hora Chile) — {len(rows)} tiendas {dict(Counter(r['state'] for r in rows))}")
    json.dump({r["id"]: r for r in rows}, open(snap, "w"), ensure_ascii=False)

# ---------- 3. agotar / encender ----------
def find_items(sid, name, contains):
    d = mm("getMenuData", sid, {"storeUUID": sid, "shouldLoadItems": True, "offeringTypes": ["INSTANT"]})
    hits = []
    for m in d["menus"].values():
        for it in ((m.get("entities") or {}).get("itemsMap") or {}).values():
            t = (((it.get("itemInfo") or {}).get("title") or {}).get("defaultValue") or "").strip().lower()
            if (name.lower() in t) if contains else (t == name.lower()): hits.append(it)
    return d, hits

def build_item_change(sid, name, mode, contains):
    bl = mm("hydrateBusinessLocation", sid, {"storeUUID": sid})
    d, hits = find_items(sid, name, contains)
    if not hits: return None, "not_carried"
    tz = ZoneInfo(bl.get("timezone") or "America/Santiago")
    if mode == "today":
        until = (dt.datetime.now(tz) + dt.timedelta(days=1)).replace(hour=4, minute=0, second=0, microsecond=0).isoformat()
        val = {"suspendUntil": "", "suspendReason": "", "suspendUntilMilliseconds": until}
    elif mode == "indefinite":
        val = {"suspendUntil": "", "suspendReason": "", "suspendUntilMilliseconds": INDEFINITE}
    else:
        val = {"suspendUntil": None, "suspendReason": None, "suspendUntilMilliseconds": None}
    changes = []
    for h in hits:
        it = copy.deepcopy(h); si = it.get("suspensionInfo") or {}
        it["suspensionInfo"] = {**si, "defaultValue": {**(si.get("defaultValue") or {}), **val}}
        changes.append({"action": "update", "menuType": d["menuMapping"][0]["menuType"], "type": "item", "data": it})
    body = {"changes": changes, "cityId": bl["regionId"], "internalTags": bl.get("internalTags") or [],
            "countryCode": bl["iso2"], "storeUUID": sid, "shouldLoadItems": True, "offeringTypes": ["INSTANT"]}
    return body, [((h.get("itemInfo") or {}).get("title") or {}).get("defaultValue") for h in hits]

def cmd_items(a, mode):
    st = stores(a.store, a.id)
    if not st: sys.exit("Ninguna tienda coincide")
    plans = pmap(lambda s: (s, *build_item_change(s["id"], a.item, mode, a.contains)), st)
    rows, todo = [], []
    for p in plans:
        if isinstance(p, dict): rows.append({"store": p["_x"]["name"], "result": "error", "detail": p["_error"]}); continue
        s, body, info = p
        if body is None: rows.append({"store": s["name"], "result": info, "detail": ""}); continue
        todo.append((s, body)); rows.append({"store": s["name"], "result": "planned", "detail": "; ".join(info)})
    if a.dry_run or not a.yes:
        if todo and (a.dry_run or a.show_payload):
            ex = copy.deepcopy(todo[0][1])
            for ch in ex["changes"]: ch["data"] = {"uuid": ch["data"]["uuid"], "title": ch["data"].get("itemInfo", {}).get("title"),
                                                    "suspensionInfo": ch["data"]["suspensionInfo"], "...": "(resto del ítem sin cambios)"}
            print("Payload ejemplo (upsertMenus) para", todo[0][0]["name"], ":\n" + json.dumps(ex, ensure_ascii=False, indent=1), file=sys.stderr)
        emit(rows, a, ["store", "result", "detail"], title=f"[DRY-RUN] {mode} '{a.item}' — {len(todo)} tiendas a cambiar" + ("" if a.dry_run else " (agrega --yes)"))
        return
    def run(t):
        s, body = t
        r = cli().s.post(MM + "upsertMenus", params={"localeCode": "en", "restaurantUUID": s["id"]}, json=body, timeout=120).json()
        if r.get("status") != "success": return {"store": s["name"], "result": "fail", "detail": str(r)[:150]}
        _, h2 = find_items(s["id"], a.item, a.contains)
        v = [((h.get("suspensionInfo") or {}).get("defaultValue") or {}).get("suspendUntilMilliseconds") for h in h2]
        ok = all((x is None) if mode == "instock" else bool(x) for x in v)
        return {"store": s["name"], "result": "ok" if ok else "verify_failed", "detail": ", ".join(cl(x) or "en stock" for x in v)}
    res = pmap(run, todo, 4)
    emit([r for r in rows if r["result"] != "planned"] + [r if "_error" not in r else {"store": r["_x"][0]["name"], "result": "error", "detail": r["_error"]} for r in res], a, ["store", "result", "detail"])

# ---------- 4. informe de agotados ----------
def cmd_soldout_report(a):
    st = stores(a.store, a.id); now = dt.datetime.now(dt.timezone.utc)
    def one(s):
        d = mm("getMenuData", s["id"], {"storeUUID": s["id"], "shouldLoadItems": True, "offeringTypes": ["INSTANT"]})
        out, seen = [], set()
        for m in d["menus"].values():
            for it in ((m.get("entities") or {}).get("itemsMap") or {}).values():
                u = ((it.get("suspensionInfo") or {}).get("defaultValue") or {}).get("suspendUntilMilliseconds")
                if not u or it["uuid"] in seen: continue
                try: ud = dt.datetime.fromisoformat(str(u).replace("Z", "+00:00"))
                except Exception: continue
                if ud <= now: continue
                seen.add(it["uuid"])
                out.append({"store": s["name"], "item": ((it.get("itemInfo") or {}).get("title") or {}).get("defaultValue"),
                            "until_chile": "indefinido" if u == INDEFINITE or ud.year > 2200 else cl(u), "item_uuid": it["uuid"]})
        return out
    res = pmap(one, st); rows = []
    for r in res:
        if isinstance(r, dict): rows.append({"store": r["_x"]["name"], "item": "ERROR " + r["_error"], "until_chile": ""})
        else: rows += r
    rows.sort(key=lambda r: (r["store"], r["item"] or ""))
    emit(rows, a, ["store", "item", "until_chile"], title=f"Ítems agotados: {len(rows)} en {len({r['store'] for r in rows})} tiendas (de {len(st)} revisadas)")

# ---------- 5. ventas ----------
def opsum(ids, d1, d2):
    p1 = dt.date.fromisoformat(d1) - dt.timedelta(days=7); p2 = dt.date.fromisoformat(d2) - dt.timedelta(days=7)
    o = api("operationsSummary", {"currentTimePeriod": {"startDate": d1, "endDate": d2}, "previousTimePeriod": {"startDate": str(p1), "endDate": str(p2)},
          "dominantCurrency": "CLP", "restaurantIds": ids, "isCached": False, "areSelectedLocationsGroceryRetailOnly": False})
    r = {"completed": 0, "cancelled": 0, "unfulfilled": 0, "inaccurate": 0, "refunds_clp": 0, "lost_sales_clp": 0, "chargebacks_clp": 0, "downtime_min": 0}
    for t in o["currentOperationsSummary"].get("orderTypesMetadata") or []:
        k = t["orderStatus"].replace("ORDER_STATUS_", "").lower()
        k = {"canceled": "cancelled", "cancelled": "cancelled"}.get(k, k)
        if k in r: r[k] += t.get("totalOrderVolume") or 0
        r["refunds_clp"] += round((t.get("customerRefundsAmount") or {}).get("amount") or 0)
        r["lost_sales_clp"] += (t.get("lostSalesAmount") or {}).get("amount") or 0
        r["chargebacks_clp"] += round((t.get("chargebackAmount") or {}).get("amount") or 0)
    r["downtime_min"] = (o["currentOperationsSummary"].get("downtimeSummary") or {}).get("storeDowntimeInMinutes") or 0
    return r

def cmd_sales(a):
    today = dt.datetime.now(TZ).date()
    d1 = a.start or str(today - dt.timedelta(days=1)); d2 = a.end or d1
    st = stores(a.store, a.id); names = {s["id"]: s["name"] for s in st}
    end_excl = str(dt.date.fromisoformat(d2) + dt.timedelta(days=1))
    sd = api("getStores", {"restaurantsMetadata": [], "isTopEatsIncluded": False, "storeFilters": {"dateFilter": {"startDate": d1, "endDate": end_excl}}})["storeData"]
    sales = {x["restaurantUuid"]["value"]: x["storeSalesData"] for x in sd}
    ops = dict(zip(names, pmap(lambda i: opsum([i], d1, d2), list(names)))) if not a.no_ops else {}
    rows = []
    for i, n in names.items():
        s = sales.get(i) or {}; o = ops.get(i) or {}
        rows.append({"store": n, "sales_clp": (s.get("totalSales") or {}).get("amount", 0), "orders": s.get("totalOrders", 0),
                     **{k: o.get(k, "") for k in ["completed", "cancelled", "unfulfilled", "inaccurate", "refunds_clp", "lost_sales_clp", "chargebacks_clp", "downtime_min"]},
                     **({"ops_error": o["_error"]} if "_error" in o else {})})
    rows.sort(key=lambda r: -(r["sales_clp"] or 0))
    tot = {"store": "TOTAL"}
    for k in rows[0] if rows else []:
        if k != "store": tot[k] = round(sum(r[k] for r in rows if isinstance(r.get(k), (int, float))))
    rows.append(tot)
    emit(rows, a, ["store", "sales_clp", "orders", "completed", "cancelled", "unfulfilled", "inaccurate", "refunds_clp", "lost_sales_clp", "chargebacks_clp", "downtime_min"],
         title=f"Ventas {d1}..{d2} (CLP). Ventas/pedidos: getStores (casi tiempo real). Cancelados/no cumplidos/reembolsos: operationsSummary (desfase ~1 día; hoy suele venir en 0).")

# ---------- 6. disputas ----------
def hist(ids, d1, d2, flt, cursor="", nxt="liveOrders", limit=50):
    return api("getHistoricOrders", {"filters": {"currentTab": "historyOrders", "displayCurrencyCode": "CLP", "isEatsPassSubscriber": False,
        "locationConstraints": {"cities": [], "countries": [], "locationUuids": ids}, "orderIssuesV2": [], "issueOrderStatusFilter": flt,
        "search": "", "dateFilter": {"startDate": f"{d1} 00:00:00", "endDate": f"{d2} 23:59:59", "lastUpdatedAt": ""}, "displayByocIssues": False},
        "sort": {"sortColumn": "SORT_COLUMN_ORDER_COMPLETED_AT", "sortDirection": "SORT_DIRECTION_DESC"},
        "pagination": {"cursor": cursor, "limit": limit, "nextTable": nxt}})

def cmd_disputes(a):
    today = dt.datetime.now(TZ).date()
    d1 = a.start or str(today - dt.timedelta(days=29)); d2 = a.end or str(today)
    st = stores(a.store, a.id); ids = [s["id"] for s in st]
    head = hist(ids, d1, d2, [], limit=1)
    cnt = head.get("ordersIssueCount") or {}
    flt = {"pending": ["ISSUE_ORDER_STATUS_ISSUE_CHARGED", "ISSUE_ORDER_STATUS_POTENTIAL_DEDUCTION"], "charged": ["ISSUE_ORDER_STATUS_ISSUE_CHARGED"],
           "disputed": ["ISSUE_ORDER_STATUS_ALL_DISPUTED"], "accepted": ["ISSUE_ORDER_STATUS_DISPUTE_ACCEPTED"],
           "rejected": ["ISSUE_ORDER_STATUS_DISPUTE_REJECTED"]}[a.status]
    rows, cur, nxt = [], "", "liveOrders"
    while len(rows) < a.max:
        d = hist(ids, d1, d2, flt, cur, nxt)
        for o in d.get("orders") or []:
            rows.append({"store": o["restaurant"]["name"], "order": o.get("orderId"), "requested": o.get("requestedAt"), "tag": (o.get("orderTag") or "").replace("ORDER_TAG_", ""),
                         "issue": o.get("issueType"), "sales": o.get("salesTotal"), "chargeback": o.get("chargebackTotal"),
                         "possible_chargeback": o.get("possibleChargebackAmountFormatted"), "workflow_uuid": o.get("workflowUuid")})
        pr = d.get("paginationResult") or {}
        if not d.get("orders") or not pr.get("nextCursor"): break
        cur, nxt = pr["nextCursor"], pr.get("nextTable") or nxt
    print(f"Pedidos con incidencias {d1}..{d2}, {len(ids)} tiendas: " + ", ".join(f"{k}={v}" for k, v in cnt.items()), file=sys.stderr)
    emit(rows[:a.max], a, ["store", "order", "requested", "tag", "issue", "sales", "chargeback", "possible_chargeback"], title=f"Filtro '{a.status}': {len(rows[:a.max])} pedidos")

def cmd_dispute_photos(a):
    """Solo lectura: fotos del cliente, comentario, explicación IA y evidencia de la tienda por pedido."""
    import ue_evidence as ev
    rows = []
    for spec in a.orders:
        store, oid = spec.split(":", 1) if ":" in spec else (None, spec)
        st = stores([store] if store else a.store, a.id); ids = [s["id"] for s in st]
        today = dt.datetime.now(TZ).date(); d1 = a.start or str(today - dt.timedelta(days=29)); d2 = a.end or str(today)
        hit, cur, nxt = None, "", "liveOrders"
        for _ in range(400):
            d = hist(ids, d1, d2, [], cur, nxt)
            hit = next((o for o in d.get("orders") or [] if o.get("orderId") == oid), None)
            pr = d.get("paginationResult") or {}
            if hit or (not pr.get("nextCursor") and pr.get("nextTable") in (nxt, "None", None)): break
            cur, nxt = pr.get("nextCursor", ""), pr.get("nextTable") or nxt
        if not hit: rows.append({"order": oid, "error": "no encontrado"}); continue
        o = ev.collect(gql, hit["workflowUuid"], hit.get("orderUuid"), hit["restaurant"]["uuid"])
        folder = os.path.join(a.out, oid)
        if not a.no_download:
            o["files"] = ev.download(o["customer_images"], os.path.join(folder, "cliente")) + ev.download(o["store_evidence"], os.path.join(folder, "tienda"))
            json.dump(o, open(os.path.join(folder, "detalle.json"), "w"), ensure_ascii=False, indent=1)
        isv = (o.get("order") or {}).get("issueSummaryV2") or {}; ds = o.get("dispute") or {}
        rows.append({"order": oid, "store": hit["restaurant"]["name"], "tag": hit.get("orderTag", "").replace("ORDER_TAG_", ""), "issue": isv.get("issueType"),
                     "comentario_cliente": " | ".join(c["text"] for c in o["customer_comments"]), "fotos_cliente": len(o["customer_images"]), "evidencia_tienda": len(o["store_evidence"]),
                     "disputa": ds.get("disputeStatus"), "motivo": ds.get("disputeReason"), "descripcion": ds.get("disputeDescription"),
                     "ia": (isv.get("aiExplanation") or "").replace("\n", " "), "carpeta": folder if not a.no_download else ""})
    emit(rows, a, ["order", "store", "tag", "issue", "comentario_cliente", "fotos_cliente", "evidencia_tienda", "disputa", "motivo", "carpeta"], title="Evidencia de pedidos")

Q_SUBMIT = """mutation SubmitDispute($disputeSubmission: Dispute_Submission!) {
  submitDispute(disputeSubmission: $disputeSubmission) { disputeUUID disputeRiskCheck } }"""
DISPUTE_REASONS = ["CUSTOMER_MISTAKE", "CUSTOMER_PROVIDED_EVIDENCE_INCORRECT", "DELIVERY_DRIVER_RELATED", "EVIDENCE_UNCONVINCING",
                   "INCORRECT_REFUND_AMOUNT", "OTHER", "STORE_EVIDENCE_AVAILABLE"]
EVID_EXT = {".jpg", ".jpeg", ".png", ".mp4", ".mpg", ".3gpp", ".pdf"}
Q_ELIG = """query OrderDetails($workflowUUID: ID!, $detailsRequestedByRestaurantUUID: ID) { orderDetails(workflowUUID: $workflowUUID, detailsRequestedByRestaurantUUID: $detailsRequestedByRestaurantUUID) {
  orderId orderUUID restaurant { uuid name } items { uuid name quantity supportV2 { issueType quantity isChargeback } }
  disputeEligibilityCheck { disputeEligibility disputeFlow riskDisputeEligibilityOutcome } chargebackDisputeV2 { disputeStatus } } }"""

def cmd_dispute(a):
    """Arma SubmitDispute. Por defecto dry-run (solo imprime). --yes enviaría (multipart GraphQL si hay evidencia)."""
    if a.reason not in DISPUTE_REASONS: sys.exit(f"reason inválido; usa uno de {DISPUTE_REASONS}")
    if a.reason == "OTHER" and not a.description: sys.exit("OTHER requiere --description")
    for f in a.evidence:
        if not os.path.isfile(f) or os.path.splitext(f)[1].lower() not in EVID_EXT: sys.exit(f"evidencia inválida: {f}")
        if os.path.getsize(f) > 104857600: sys.exit(f"{f} supera 100 MB")
    if len(a.evidence) > 3: sys.exit("máximo 3 archivos de evidencia")
    od = gql("OrderDetails", Q_ELIG, {"workflowUUID": a.workflow, "detailsRequestedByRestaurantUUID": a.restaurant})["orderDetails"]
    el = od.get("disputeEligibilityCheck") or {}
    items = [{"uuid": i["uuid"], "name": i["name"], "quantity": (i.get("supportV2") or [{}])[0].get("quantity") or i["quantity"]}
             for i in od.get("items") or [] if i.get("supportV2")]
    sub = {"orderUuid": od["orderUUID"], "reason": a.reason, "description": a.description or "", "evidence": [None] * len(a.evidence),
           "locale": a.locale, "disputeFlow": el.get("disputeFlow"), **({"disputedItems": items} if items else {}), "captchaToken": None}
    problems = []
    if el.get("disputeEligibility") != "ELIGIBLE": problems.append(f"disputeEligibility={el.get('disputeEligibility')} (la UI solo muestra el formulario con ELIGIBLE)")
    if el.get("disputeFlow") == "DISPUTE_WITH_EVIDENCE" and not a.evidence: problems.append("disputeFlow exige evidencia")
    if el.get("riskDisputeEligibilityOutcome") == "ELIGIBLE_AFTER_CAPTCHA": problems.append("requiere captcha (no automatizable)")
    print(json.dumps({"order": od.get("orderId"), "store": (od.get("restaurant") or {}).get("name"), "eligibility": el,
                      "operationName": "SubmitDispute", "variables": {"disputeSubmission": sub},
                      "evidence_files": [{"path": f, "bytes": os.path.getsize(f)} for f in a.evidence],
                      "transport": "multipart (graphql-multipart-request-spec)" if a.evidence else "JSON", "problems": problems}, ensure_ascii=False, indent=1))
    if a.dry_run or not a.yes:
        print("DRY-RUN: no se envió nada. Usa --yes para enviar.", file=sys.stderr); return
    if problems: sys.exit("No se envía: " + "; ".join(problems))
    if not a.evidence:
        print(json.dumps(gql("SubmitDispute", Q_SUBMIT, {"disputeSubmission": sub}), ensure_ascii=False)); return
    ops = json.dumps({"operationName": "SubmitDispute", "query": Q_SUBMIT, "variables": {"disputeSubmission": sub}})
    fmap = json.dumps({str(i): [f"variables.disputeSubmission.evidence.{i}"] for i in range(len(a.evidence))})
    files = {str(i): (os.path.basename(f), open(f, "rb")) for i, f in enumerate(a.evidence)}
    s = cli().s; h = {k: v for k, v in s.headers.items() if k.lower() != "content-type"}
    h["apollo-require-preflight"] = "true"
    r = requests.post(GQL, data={"operations": ops, "map": fmap}, files=files, headers=h, timeout=120, allow_redirects=False)
    print(r.status_code, r.text[:1000])

# ---------- 7. horarios ----------
DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
def fmt_iv(ivs):
    return " / ".join(f"{i['startMinute']//60:02d}:{i['startMinute']%60:02d}-{i['endMinute']//60:02d}:{i['endMinute']%60:02d}" for i in ivs or []) or "cerrado"

def cmd_hours(a):
    st = stores(a.store, a.id); names = {s["id"]: s["name"] for s in st}
    sts = cli().get_statuses(list(names)); rows = []
    for i, v in sts.items():
        mh = v.get("menu_hours") or {}
        week = {}
        for menu in mh.values():
            for d_, ivs in (menu or {}).items(): week.setdefault(d_, []).extend(ivs)
        ov = v.get("hours_overrides") or {}
        ovs = []
        for kind in ("singleOverrides", "recurringOverrides"):
            x = ov.get(kind)
            if not x: continue
            items = x if isinstance(x, list) else list(x.values()) if all(isinstance(y, (dict, list)) for y in x.values()) else [x]
            for o in items: ovs.append(kind[:-9] + ":" + json.dumps(o, ensure_ascii=False, default=str)[:200])
        rows.append({"store": names[i], **{d_[:3]: fmt_iv(week.get(d_)) for d_ in DAYS}, "overrides": "; ".join(ovs) or "-"})
    rows.sort(key=lambda r: r["store"])
    try: hol = api("getUpcomingHolidaysFromFlipr", {"countryCodes": ["CL"], "daysAhead": a.days, "limit": 10}).get("holidays") or []
    except Exception as e: hol = [f"error: {e}"]
    print(f"Feriados CL próximos {a.days} días según Uber: {json.dumps(hol, ensure_ascii=False) if hol else 'ninguno'}", file=sys.stderr)
    emit(rows, a, ["store"] + [d_[:3] for d_ in DAYS] + ["overrides"], title=f"Horario semanal (hora local tienda) — {len(rows)} tiendas")


# ---------- 8. activar menú completo ----------
DEFAULT_EXCLUDE = ["Papas Cheddar", "Papas Cheddar Bacon", "Salsa Tártara", "Promo Super Basket Recargado",
                   "Promo Box Recargado", "Combo Mundialero Coca-Cola", "Papas Bites con Salsa Cheddar"]
def norm(t):
    import unicodedata
    t = unicodedata.normalize("NFKD", (t or "").strip().lower())
    return " ".join("".join(ch for ch in t if not unicodedata.combining(ch)).split())

def load_excl(a):
    ex = list(DEFAULT_EXCLUDE) if not a.no_default_exclude else []
    ex += a.exclude or []
    if a.exclude_file:
        ex += [l.strip() for l in open(a.exclude_file, encoding="utf-8") if l.strip() and not l.startswith("#")]
    return {norm(x) for x in ex}

def _susp_until(it, now):
    u = ((it.get("suspensionInfo") or {}).get("defaultValue") or {}).get("suspendUntilMilliseconds")
    if not u: return None
    try: ud = dt.datetime.fromisoformat(str(u).replace("Z", "+00:00"))
    except Exception: return None
    return u if ud > now else None

def plan_menu(s, excl):
    sid = s["id"]; now = dt.datetime.now(dt.timezone.utc)
    d = mm("getMenuData", sid, {"storeUUID": sid, "shouldLoadItems": True, "offeringTypes": ["INSTANT"]})
    rows, changes, seen = [], [], set()
    for m in d["menus"].values():
        ents = m.get("entities") or {}
        opt_ids = {o["uuid"] for c in (ents.get("customizationsMap") or {}).values() for o in (c.get("options") or [])}
        top_ids = set()
        for it in (ents.get("itemsMap") or {}).values():
            pass
        for sec in (m.get("subsectionsMap") or {}).values():
            for e in (sec.get("displayItems") or []):
                top_ids.add(e.get("uuid") if isinstance(e, dict) else e)
        for it in (ents.get("itemsMap") or {}).values():
            if it["uuid"] in seen: continue
            u = _susp_until(it, now)
            if not u: continue
            seen.add(it["uuid"])
            name = ((it.get("itemInfo") or {}).get("title") or {}).get("defaultValue")
            typ = "opcion" if it["uuid"] in opt_ids and it["uuid"] not in top_ids else "producto"
            prev = "agotado indefinido" if str(u).startswith("22") else "agotado hasta " + cl(u)
            row = {"store": s["name"], "product": name, "type": typ, "previous": prev, "uuid": it["uuid"]}
            if norm(name) in excl:
                rows.append(dict(row, action="excluido", result="omitido")); continue
            x = copy.deepcopy(it); si = x.get("suspensionInfo") or {}
            x["suspensionInfo"] = {**si, "defaultValue": {**(si.get("defaultValue") or {}),
                                   "suspendUntil": None, "suspendReason": None, "suspendUntilMilliseconds": None}}
            changes.append({"action": "update", "menuType": d["menuMapping"][0]["menuType"], "type": "item", "data": x})
            rows.append(dict(row, action="activar", result="pendiente"))
    body = None
    if changes:
        bl = mm("hydrateBusinessLocation", sid, {"storeUUID": sid})
        body = {"changes": changes, "cityId": bl["regionId"], "internalTags": bl.get("internalTags") or [],
                "countryCode": bl["iso2"], "storeUUID": sid, "shouldLoadItems": True, "offeringTypes": ["INSTANT"]}
    return rows, body

def write_log(rows, platform):
    fn = f"/workspace/{platform}-activacion-{dt.datetime.now(TZ):%Y-%m-%d}.csv"
    cols = ["timestamp", "store", "product", "type", "previous", "action", "result"]
    new = not os.path.exists(fn); ts = dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    with open(fn, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols, extrasaction="ignore")
        if new: w.writeheader()
        for r in rows: w.writerow(dict(r, timestamp=ts))
    return fn

def cmd_activate_menu(a):
    import time; t0 = time.time()
    excl = load_excl(a)
    st = stores(a.store or (None if a.id else ["Tarragona"]), a.id)
    if not st: sys.exit("Ninguna tienda coincide")
    plans = pmap(lambda s: (s, *plan_menu(s, excl)), st)
    rows, todo, fails = [], [], 0
    for p in plans:
        if isinstance(p, dict):
            rows.append({"store": p["_x"]["name"], "product": "", "type": "", "previous": "", "action": "leer menú", "result": "error: " + p["_error"]}); fails += 1; continue
        s, r, body = p; rows += r
        if body: todo.append((s, body))
    real = a.yes and not a.dry_run
    if not real:
        for r in rows:
            if r["result"] == "pendiente": r["result"] = "dry-run"
    else:
        def run(t):
            s, body = t
            r = cli().s.post(MM + "upsertMenus", params={"localeCode": "en", "restaurantUUID": s["id"]}, json=body, timeout=180).json()
            if r.get("status") != "success": return s["id"], None, str(r)[:150]
            d = mm("getMenuData", s["id"], {"storeUUID": s["id"], "shouldLoadItems": True, "offeringTypes": ["INSTANT"]})
            now = dt.datetime.now(dt.timezone.utc)
            still = {it["uuid"] for m in d["menus"].values() for it in ((m.get("entities") or {}).get("itemsMap") or {}).values() if _susp_until(it, now)}
            return s["id"], still, ""
        res = {}
        for x in pmap(run, todo, 4):
            if isinstance(x, dict): res[x["_x"][0]["id"]] = (None, x["_error"])
            else: res[x[0]] = (x[1], x[2])
        sid_by_name = {s["name"]: s["id"] for s, _ in todo}
        for r in rows:
            if r["result"] != "pendiente": continue
            still, err = res.get(sid_by_name.get(r["store"]), (None, "sin respuesta"))
            if still is None: r["result"] = "error: " + err; fails += 1
            elif r["uuid"] in still: r["result"] = "verificación falló (sigue agotado)"; fails += 1
            else: r["result"] = "ok"
    fn = write_log(rows, "uber")
    from collections import Counter
    c = Counter((r["action"], r["type"]) for r in rows)
    emit(rows, a, ["store", "product", "type", "previous", "action", "result"])
    print(f"{'[DRY-RUN] ' if not real else ''}Uber activate-menu: {len(st)} tiendas, {len(todo)} con cambios, "
          f"productos a activar {c[('activar','producto')]}, opciones a activar {c[('activar','opcion')]}, "
          f"excluidos {sum(v for k, v in c.items() if k[0]=='excluido')}, fallas {fails}, {time.time()-t0:.0f}s — log {fn}", file=sys.stderr)
    if fails: sys.exit(1)

# ---------- main ----------
def main():
    P = argparse.ArgumentParser(description="CLI Uber Eats Manager. Cookie: ~/.uber_cookie o UBER_COOKIE.")
    sp = P.add_subparsers(dest="cmd", required=True)
    def base(p, write=False):
        p.add_argument("--store", "-s", action="append", help="subcadena del nombre (repetible)")
        p.add_argument("--id", action="append", help="UUID de tienda (repetible)")
        g = p.add_mutually_exclusive_group(); g.add_argument("--json", action="store_true"); g.add_argument("--csv", action="store_true")
        if write:
            p.add_argument("--dry-run", action="store_true", help="solo muestra el payload"); p.add_argument("--yes", action="store_true", help="confirmar ejecución real")
        return p
    p = base(sp.add_parser("pause", help="pausar tiendas (SetStoresBusy)"), True)
    p.add_argument("--duration", choices=list(DURATIONS), default="rest_of_day", help="minutos o rest_of_day (fin del día)")
    p.add_argument("--reason", choices=REASONS, default="OTHER"); p.add_argument("--comment")
    base(sp.add_parser("activate", help="reanudar tiendas (SetStoresOnline)"), True)
    p = base(sp.add_parser("monitor", help="estado abierta/cerrada/pausada/no visible"))
    p.add_argument("--changes", action="store_true", help="solo cambios vs snapshot ~/.uber_state"); p.add_argument("--only", action="append", choices=["open", "closed", "paused", "not_visible"])
    for nm in ["soldout", "instock"]:
        p = base(sp.add_parser(nm, help=f"{nm} de un producto"), True)
        p.add_argument("--item", required=True); p.add_argument("--contains", action="store_true", help="coincidencia por subcadena (default: exacta)")
        p.add_argument("--show-payload", action="store_true")
        if nm == "soldout": p.add_argument("--until", choices=["today", "indefinite"], default="today")
    base(sp.add_parser("soldout-report", help="ítems agotados por tienda"))
    p = base(sp.add_parser("sales", help="ventas/cancelados por tienda")); p.add_argument("--start"); p.add_argument("--end"); p.add_argument("--no-ops", action="store_true")
    p = base(sp.add_parser("disputes", help="incidencias/disputas")); p.add_argument("--start"); p.add_argument("--end"); p.add_argument("--max", type=int, default=200)
    p.add_argument("--status", choices=["pending", "charged", "disputed", "accepted", "rejected"], default="pending")
    p = base(sp.add_parser("dispute", help="disputar un cobro (dry-run por defecto)"), write=True); p.add_argument("--workflow", required=True); p.add_argument("--restaurant", required=True)
    p.add_argument("--reason", required=True, choices=DISPUTE_REASONS); p.add_argument("--description", default=""); p.add_argument("--evidence", nargs="*", default=[]); p.add_argument("--locale", default="es")
    p = base(sp.add_parser("dispute-photos", help="fotos/evidencia de pedidos con incidencia (solo lectura)")); p.add_argument("orders", nargs="+", help="ID de pedido (ej. AA7A2) o 'Tienda:ID'")
    p.add_argument("--start"); p.add_argument("--end"); p.add_argument("--out", default="/workspace/uber_dispute_photos"); p.add_argument("--no-download", action="store_true")
    p = base(sp.add_parser("hours", help="horario semanal + excepciones/feriados")); p.add_argument("--days", type=int, default=30)
    p = base(sp.add_parser("activate-menu", help="reactivar todo lo agotado (productos + opciones) salvo exclusiones"), True)
    p.add_argument("--exclude", action="append", help="nombre exacto a excluir (repetible)")
    p.add_argument("--exclude-file", help="archivo con un nombre por línea")
    p.add_argument("--no-default-exclude", action="store_true", help="no usar la lista por defecto")
    a = P.parse_args()
    {"pause": cmd_pause, "activate": cmd_activate, "monitor": cmd_monitor, "soldout": lambda a: cmd_items(a, a.until),
     "instock": lambda a: cmd_items(a, "instock"), "soldout-report": cmd_soldout_report, "sales": cmd_sales,
     "disputes": cmd_disputes, "hours": cmd_hours, "activate-menu": cmd_activate_menu, "dispute-photos": cmd_dispute_photos, "dispute": cmd_dispute}[a.cmd](a)

if __name__ == "__main__": main()

```

---

# refresh_uber_cookie.py

```python
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

```

---

# api_client.py (cookie load/save)

```python
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

```
