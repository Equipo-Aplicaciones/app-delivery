#!/usr/bin/env python3
"""pya.py — CLI PedidosYa Partner Portal (Tarragona). Ver README.md.
Tokens: ~/.pya_tokens.json (se refrescan solos). Nunca imprime tokens.
Escrituras (pause/activate/soldout/instock) solo con --yes; por defecto dry-run."""
import argparse, csv, json, os, sys, datetime as dt
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_client import PedidosYaClient, PyaError, VSS, VTS, SHELL_APP_VERSION, _jwt_claims

TZ = ZoneInfo("America/Santiago")
GE = "PY_CL"
INV = "https://vendor-api-cl.us.restaurant-partners.com/api/4/platforms/{ge}/vendors/{vid}/catalogs"
VAGW = "https://vagw-api.us.prd.portal.restaurant/query"
GQL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gql")
STATE = os.path.expanduser("~/.pya_state")
REASONS = ["TOO_BUSY_KITCHEN", "TOO_BUSY_NO_DRIVERS", "UPDATES_IN_MENU", "TECHNICAL_PROBLEM",
           "BAD_WEATHER", "OTHER", "CLOSED"]

c = PedidosYaClient()

def loc(ts):
    if not ts: return ""
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")[:26] + ("+00:00" if ts.endswith("Z") and len(ts) > 27 else "")
                                     if False else ts.replace("Z", "+00:00")).astimezone(TZ).strftime("%Y-%m-%d %H:%M")

def _ts(ts):
    try:
        s = ts.replace("Z", "+00:00")
        if "." in s:  # recorta nanosegundos
            a, b = s.split("."); frac, off = b[:6], b[b.find("+"):] if "+" in b else ""
            s = f"{a}.{frac.split('+')[0]}{off}"
        return dt.datetime.fromisoformat(s).astimezone(TZ).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts or ""

def _headers(extra=None):
    cl = _jwt_claims(c.access)
    h = {"Authorization": f"Bearer {c.access}", "X-App-Name": "oneweb", "X-RPS-Client-App-Name": "OneWeb",
         "X-App-Version": SHELL_APP_VERSION, "X-RPS-Device": c.device, "X-Is-Impersonation": "false",
         "X-User-Id": str(cl.get("sub", "")), "Content-Type": "application/json"}
    h.update(extra or {}); return h

def _send(method, url, body):
    c._get  # noqa
    exp = c.token_expires_in()
    if exp is not None and exp < 60: c._refresh()
    r = c.s.request(method, url, headers=_headers(), json=body, timeout=60)
    if r.status_code == 401 and c._refresh():
        r = c.s.request(method, url, headers=_headers(), json=body, timeout=60)
    if r.status_code >= 300:
        raise PyaError(f"{method} {url} -> HTTP {r.status_code}: {r.text[:300]}")
    return r.json() if r.text else None

def gql(op, variables):
    q = json.load(open(os.path.join(GQL_DIR, op + ".json")))
    q["variables"] = variables
    d = _send("POST", VAGW, q)
    if d.get("errors"): raise PyaError(json.dumps(d["errors"])[:300])
    return d["data"]

# ---------- tiendas ----------
def describe(v):
    st, cat = v.get("state"), v.get("category")
    out = {"vendor_id": v.get("platformVendorId"), "name": v.get("name"), "state": st, "category": cat,
           "reason": "", "since": "", "until": "", "author": "", "changeable": ""}
    if st == "CLOSED" and v.get("closure"):
        cz = v["closure"]; out.update(reason=cz.get("reason", ""), since=_ts(cz.get("start")),
                                      until=_ts(cz.get("end")), author=cz.get("author", ""),
                                      changeable=cz.get("changeable", ""))
    elif st == "HIGH_DEMAND_MODE" and v.get("highDemandMode"):
        h = v["highDemandMode"]; out.update(reason=f"+{h.get('extraPrepTimeMinutes')} min prep",
                                            since=_ts(h.get("start")), until=_ts(h.get("end")), author=h.get("author", ""))
    elif st == "CHECKIN" and v.get("checkIn"):
        ci = v["checkIn"]; out.update(reason=ci.get("reason") or ci.get("state", ""), until=_ts(ci.get("openingAt")))
    elif st == "INACTIVE":
        out["reason"] = "inactivo (dado de baja/sin activar en PedidosYa)"
    nx = v.get("nextOrCurrentSlot") or {}
    out["slot"] = f"{_ts(nx.get('openingAt'))[-5:]}-{_ts(nx.get('closingAt'))[-5:]}" if nx else ""
    return out

GROUP = {"OPEN": "abierta", "HIGH_DEMAND_MODE": "abierta (alta demanda)", "CLOSED": "cerrada temporal",
         "INACTIVE": "inactiva", "OUTSIDE_SCHEDULE": "fuera de horario", "CHECKIN": "check-in",
         "CHECKOUT": "abierta (checkout)", "NOT_FOUND": "no encontrada"}

def stores(args):
    vs = c._status_list()
    sel = []
    for v in vs:
        nm = (v.get("name") or "").lower(); vid = str(v.get("platformVendorId"))
        if args.id and vid not in args.id: continue
        if args.store and not any(s.lower() in nm for s in args.store): continue
        sel.append(v)
    return sel

def emit(rows, args, cols=None):
    if not rows: print("(sin resultados)"); return
    cols = cols or list(rows[0].keys())
    if args.json: print(json.dumps(rows, ensure_ascii=False, indent=2)); return
    if args.csv:
        w = csv.DictWriter(sys.stdout, cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows); return
    wd = {k: min(40, max(len(k), *(len(str(r.get(k, ""))) for r in rows))) for k in cols}
    print("  ".join(k.ljust(wd[k]) for k in cols))
    for r in rows: print("  ".join(str(r.get(k, ""))[:40].ljust(wd[k]) for k in cols))

def cmd_monitor(a):
    rows = [describe(v) for v in stores(a)]
    for r in rows: r["estado"] = GROUP.get(r["state"], r["state"])
    if a.only: rows = [r for r in rows if r["state"] in a.only]
    from collections import Counter
    print("Resumen:", dict(Counter(r["estado"] for r in rows)), file=sys.stderr)
    os.makedirs(STATE, exist_ok=True); snap = os.path.join(STATE, "monitor_snapshot.json")
    if a.changes:
        old = json.load(open(snap)) if os.path.exists(snap) else {}
        ch = [dict(r, antes=old.get(r["vendor_id"], "(nuevo)")) for r in rows if old.get(r["vendor_id"]) != r["state"]]
        allr = rows; rows = ch
    else:
        allr = rows
    if not a.only:
        json.dump({r["vendor_id"]: r["state"] for r in allr}, open(snap, "w"))
    cols = ["vendor_id", "name", "estado", "reason", "since", "until", "author", "slot"] + (["antes"] if a.changes else [])
    emit(rows, a, cols)

def _avail_payload(v, a, open_):
    # Cuerpo real del portal (plugin availability 1.29.2, useAvailabilityUpdator). Verificado en vivo 04-11-2026.
    if open_: return {"state": "OPEN"}
    if a.minutes:
        return {"state": "CLOSED", "closure": {"mode": "MINUTES", "minutes": a.minutes, "reason": a.reason, "changeable": True}}
    return {"state": "CLOSED", "closure": {"mode": "END_OF_SLOT", "reason": a.reason, "changeable": True}}

def _write_avail(a, open_):
    sel = stores(a)
    if not sel: print("Ninguna tienda coincide."); return
    for v in sel:
        url = f"{VSS.replace('/api/v2', '')}/api/v3/globalEntities/{v['globalEntityId']}/vendors/{v['platformVendorId']}/availability"
        body = _avail_payload(v, a, open_)
        print(f"{v['name']} [{v['platformVendorId']}] estado={v['state']}\n  PUT {url}\n  {json.dumps(body)}")
        if a.yes and not a.dry_run:
            print("  ->", json.dumps(_send("PUT", url, body), ensure_ascii=False)[:300])
    if not a.yes or a.dry_run: print("\n(dry-run: no se envió nada; usa --yes para ejecutar)")

def cmd_pause(a): _write_avail(a, False)
def cmd_activate(a): _write_avail(a, True)

def cmd_hours(a):
    rows = []
    h = {"x-client-id": "vendor-portal-web", "X-RPS-Client-App-Name": "oneweb"}
    for v in stores(a):
        sid = f"{v['globalEntityId']};{v['platformVendorId']}"
        hh = dict(h, **{"X-vendor-id": sid})
        try:
            cal = c._get(f"{VTS}/vendor/{sid}/calendars/DELIVERY", hh)
            sp = c._get(f"{VTS}/vendor/{sid}/schedules/DELIVERY", hh)
        except PyaError as e:
            rows.append({"vendor_id": v["platformVendorId"], "name": v["name"], "error": str(e)[:80]}); continue
        if a.raw: rows.append({"vendor_id": v["platformVendorId"], "name": v["name"], "calendars": cal, "schedules": sp}); continue
        rows.append({"vendor_id": v["platformVendorId"], "name": v["name"],
                     "horario": _fmt_sched(cal), "especiales": _fmt_special(sp)})
    if a.raw: print(json.dumps(rows, ensure_ascii=False, indent=2)); return
    emit(rows, a, ["vendor_id", "name", "horario", "especiales"])

DN = ["Do", "Lu", "Ma", "Mi", "Ju", "Vi", "Sa"]  # day 0 = domingo (convención JS; verificar)
def _hm(m): return f"{m // 60:02d}:{m % 60:02d}"
def _fmt_sched(cal):
    try:
        out = []
        for cl in (cal or {}).get("calendars", []):
            byd = {d["day"]: ",".join(f"{_hm(t['from'])}-{_hm(t['to'])}" for t in d.get("openingTimes", []))
                   for d in cl.get("schedule", {}).get("openingTimesByDay", [])}
            out.append(" ".join(f"{DN[i]} {byd.get(i, 'cerrado')}" for i in (1, 2, 3, 4, 5, 6, 0)))
        return " | ".join(out)
    except Exception:
        return json.dumps(cal, ensure_ascii=False)[:120]

def _fmt_special(sp):
    items = (sp or {}).get("schedules", [])
    return "; ".join(json.dumps(i, ensure_ascii=False)[:100] for i in items) if items else "ninguno"

# ---------- productos ----------
def products(v, available=None, name=None):
    url = INV.format(ge=v["globalEntityId"], vid=v["platformVendorId"]) + "/products"
    out, key = [], None
    while True:
        p = {"pageSize": 100}
        if available is not None: p["isAvailable"] = str(available).lower()
        if name: p["nameContains"] = name
        if key: p["nextPageKey"] = key
        d = c._get(url, params=p) or {}
        out += d.get("data", []); key = d.get("nextKey")
        if not key: return out

def cmd_soldout_report(a):
    rows = []
    for v in stores(a):
        if v.get("state") == "INACTIVE" and not a.include_inactive: continue
        try: ps = products(v, available=False)
        except PyaError as e:
            print(f"! {v['name']}: {str(e)[:100]}", file=sys.stderr); continue
        for p in ps:
            rows.append({"vendor_id": v["platformVendorId"], "store": v["name"], "product_id": p["id"],
                         "product": p["name"], "category": (p.get("category") or {}).get("name", ""),
                         "context": (p.get("availability") or {}).get("context", ""), "updated": _ts(p.get("updatedAt"))})
    print(f"{len(rows)} productos agotados en {len({r['vendor_id'] for r in rows})} tiendas", file=sys.stderr)
    emit(rows, a)

def _set_product(a, available):
    sel = stores(a); n = 0
    for v in sel:
        try: ps = products(v, name=a.item)
        except PyaError as e: print(f"! {v['name']}: {str(e)[:100]}"); continue
        ps = [p for p in ps if a.contains or p["name"].strip().lower() == a.item.strip().lower()]
        for p in ps:
            url = INV.format(ge=v["globalEntityId"], vid=v["platformVendorId"]) + f"/products/{p['id']}/availability"
            body = _prod_body(available, a)
            print(f"{v['name']} | {p['name']} [{p['id']}] disponible={p['availability'].get('available')} -> {available}\n  PUT {url} {json.dumps(body)}")
            n += 1
            if a.yes and not a.dry_run:
                print("  ->", json.dumps(_send("PUT", url, body), ensure_ascii=False)[:300])
    print(f"\n{n} producto(s) afectados." + ("" if a.yes and not a.dry_run else " (dry-run: no se envió nada; usa --yes)"))

def _prod_body(available, a):
    # Cuerpo real del portal (plugin menuManagementV2 1.18.23, updateProductAvailability).
    b = {"available": available, "context": "MENU_UPDATE"}
    if not available:
        u = getattr(a, "until", "indefinite") or "indefinite"
        if u == "tomorrow":
            b["schedules"] = [{"action": "ENABLE", "type": "NEXT_BUSINESS_DAY"}]
        elif u.isdigit():
            t = dt.datetime.now(dt.timezone.utc).replace(microsecond=0) + dt.timedelta(minutes=int(u))
            b["schedules"] = [{"action": "ENABLE", "type": "AT_TIMESTAMP", "timestamp": t.strftime("%Y-%m-%dT%H:%M:%S.000Z")}]
    return b

def cmd_soldout(a): _set_product(a, False)
def cmd_instock(a): _set_product(a, True)

# ---------- ventas / cancelados ----------
def _range(a):
    today = dt.datetime.now(TZ).date()
    s = dt.date.fromisoformat(a.start) if a.start else today
    e = dt.date.fromisoformat(a.end) if a.end else s
    return s, e

def _utc_bounds(s, e):
    t0 = dt.datetime.combine(s, dt.time(0), TZ).astimezone(dt.timezone.utc)
    t1 = dt.datetime.combine(e, dt.time(23, 59, 59, 999000), TZ).astimezone(dt.timezone.utc)
    f = lambda t: t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"
    return f(t0), f(t1)

def _sales_one(vs, s, e):
    codes = [f"{v['globalEntityId']};{v['platformVendorId']}" for v in vs]
    gv = [{"globalEntityId": v["globalEntityId"], "vendorId": v["platformVendorId"]} for v in vs]
    t0, t1 = _utc_bounds(s, e)
    sales = gql("SalesOverviewByTime", {"params": {"global_vendor_codes": codes, "from": str(s), "to": str(e), "precision": "Hour" if s == e else "Day"}})
    iss = gql("TodayIssues", {"issuesMetricParams": {"global_vendor_codes": codes, "from": str(s), "to": str(e)},
              "cancelledOrdersCountParams": {"globalVendorCodes": gv, "disableLimit": True, "timeFrom": t0, "timeTo": t1, "filter": {"orderStatuses": ["CANCELLED"]}},
              "delayedOrdersCountParams": {"globalVendorCodes": gv, "disableLimit": True, "timeFrom": t0, "timeTo": t1, "filter": {"isDelayedOrder": True}}})
    sb = sales["salesOverview"]["salesByTime"]
    return {"pedidos": sb["order_count"], "ventas": round(float(sb["revenue"])),
            "cancelados": iss["orders"]["cancelledOrders"]["amount"], "atrasados": iss["orders"]["delayedOrders"]["amount"],
            "una_estrella": iss["reports"]["issuesMetric"]["oneStarRatingsCount"]}, sb, iss

def cmd_sales(a):
    s, e = _range(a); vs = [v for v in stores(a) if v.get("state") != "INACTIVE" or a.include_inactive]
    if a.by_store:
        rows = []
        for v in vs:
            try: r, _, _ = _sales_one([v], s, e)
            except PyaError as ex: r = {"error": str(ex)[:80]}
            rows.append(dict({"vendor_id": v["platformVendorId"], "name": v["name"]}, **r))
        emit(rows, a); return
    tot, sb, iss = _sales_one(vs, s, e)
    print(f"Periodo {s}..{e} ({len(vs)} tiendas)", file=sys.stderr)
    emit([dict({"desde": str(s), "hasta": str(e)}, **tot)], a)
    if a.ops:
        codes = [f"{v['globalEntityId']};{v['platformVendorId']}" for v in vs]
        oh = gql("OpsHealth", {"params": {"global_vendor_codes": codes}})["reports"]["operationsHealthMetric"]
        print("\nSalud operacional (portal, periodo por defecto):")
        emit([{"metrica": k, "actual": v["current"], "anterior": v["previous"]} for k, v in oh.items() if isinstance(v, dict)], a)

# ---------- activate-menu ----------
import unicodedata, time
DEFAULT_EXCLUDE = ["Papas Cheddar", "Papas Cheddar Bacon", "Salsa Tártara", "Promo Super Basket Recargado",
                   "Promo Box Recargado", "Combo Mundialero Coca-Cola", "Papas Bites con Salsa Cheddar"]

def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    return " ".join("".join(ch for ch in s if not unicodedata.combining(ch)).lower().split())

def load_excl(a):
    ex = [] if a.no_default_exclude else list(DEFAULT_EXCLUDE)
    ex += a.exclude or []
    if a.exclude_file:
        ex += [l.strip() for l in open(a.exclude_file, encoding="utf-8") if l.strip() and not l.startswith("#")]
    return {norm(x) for x in ex}

def write_log(rows, platform="pedya"):
    path = f"/workspace/{platform}-activacion-{dt.datetime.now(TZ):%Y-%m-%d}.csv"
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["timestamp", "store", "product", "type", "previous", "action", "result"], extrasaction="ignore")
        if new: w.writeheader()
        ts = dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
        for r in rows: w.writerow({"timestamp": ts, **r})
    return path

def _prev(av):
    sc = (av or {}).get("schedules") or []
    for s in sc:
        if s.get("type") == "AT_TIMESTAMP": return f"agotado hasta {_ts(s.get('timestamp'))}"
        if s.get("type") == "NEXT_BUSINESS_DAY": return "agotado hasta próximo día hábil"
    return "agotado indefinido"

def unavailable_items(v):
    """Ítems realmente agotados según el portal (no el listado crudo de /product-options).
    /product-options marca muchas opciones de menú compartido (CHAIN) como available:false
    aunque el local las tiene activas; PUT a esos ids responde 404 NOT_FOUND.
    La fuente correcta es GET catalogs/items?isAvailable=false."""
    base = INV.format(ge=v["globalEntityId"], vid=v["platformVendorId"])
    return c._get(base + "/items", params={"isAvailable": "false", "sizeSupport": "true"}) or {}

def unavailable_options(v):
    """Lista (grupo, opción) realmente agotadas; solo las que el portal muestra apagadas."""
    out = []
    for g in (unavailable_items(v).get("productOptions") or []):
        for o in g.get("options") or []:
            if (o.get("availability") or {}).get("available", True): continue
            out.append((g, o))
    return out

def plan_store(v, excl):
    base = INV.format(ge=v["globalEntityId"], vid=v["platformVendorId"])
    rows, ops = [], []
    for p in products(v, available=False):
        r = {"store": v["name"], "product": p["name"], "type": "producto", "previous": _prev(p.get("availability"))}
        if norm(p["name"]) in excl: rows.append({**r, "action": "excluido", "result": "omitido"}); continue
        rows.append({**r, "action": "activar", "result": "dry-run"})
        ops.append((len(rows) - 1, f"{base}/products/{p['id']}/availability", ("p", p["id"], None)))
    for g, o in unavailable_options(v):
        r = {"store": v["name"], "product": f"{o['name']} ({g.get('name','')})", "type": "opcion",
             "previous": _prev(o.get("availability"))}
        if norm(o["name"]) in excl: rows.append({**r, "action": "excluido", "result": "omitido"}); continue
        rows.append({**r, "action": "activar", "result": "dry-run"})
        ops.append((len(rows) - 1, f"{base}/product-options/{g['id']}/options/{o['id']}/availability", ("o", g["id"], o["id"])))
    return rows, ops

def _verify(v, ops):
    bad_p = {p["id"] for p in products(v, available=False)}
    bad_o = {(g["id"], o["id"]) for g, o in unavailable_options(v)}
    return {i for i, _, (k, a1, a2) in ops if (k == "p" and a1 in bad_p) or (k == "o" and (a1, a2) in bad_o)}

def cmd_activate_menu(a):
    t0 = time.time(); real = a.yes and not a.dry_run; excl = load_excl(a)
    if not a.store and not a.id: a.store = ["Tarragona"]
    allrows, errs, nst, nchg = [], 0, 0, 0
    for v in stores(a):
        if v.get("state") == "INACTIVE": continue
        nst += 1
        try: rows, ops = plan_store(v, excl)
        except PyaError as e:
            errs += 1; allrows.append({"store": v["name"], "product": "", "type": "", "previous": "", "action": "leer", "result": f"error: {str(e)}"}); continue
        if ops: nchg += 1
        if real and ops:
            for i, url, _ in ops:
                try: _send("PUT", url, {"available": True, "context": "MENU_UPDATE"}); rows[i]["result"] = "enviado"
                except PyaError as e: rows[i]["result"] = f"error: {str(e)}"
            time.sleep(5)
            try:
                still = _verify(v, ops)
                for i, _, _ in ops:
                    if rows[i]["result"] == "enviado": rows[i]["result"] = "error: sigue agotado" if i in still else "ok verificado"
            except PyaError as e:
                for i, _, _ in ops: rows[i]["result"] += " (sin verificar)"
        errs += sum(r["result"].startswith("error") for r in rows)
        allrows += rows
    path = write_log(allrows)
    act = [r for r in allrows if r["action"] == "activar"]
    if a.json or a.csv: emit(allrows, a, ["store", "product", "type", "previous", "action", "result"])
    print(f"[{'REAL' if real else 'DRY-RUN'}] PedidosYa activate-menu: {nst} tiendas, {nchg} con cambios, "
          f"productos a activar {sum(r['type']=='producto' for r in act)}, opciones a activar {sum(r['type']=='opcion' for r in act)}, "
          f"excluidos {sum(r['action']=='excluido' for r in allrows)}, fallas {errs}, {time.time()-t0:.0f}s — log {path}", file=sys.stderr)
    if errs: sys.exit(1)

# ---------- reportería (solo lectura) ----------
VRS = "https://vrs-api.us.prd.portal.restaurant"
VOS = "https://vos-api.us.prd.portal.restaurant/v1/vendors/reports"
VOS_REPORTS = ["performance", "performance/summary", "ops/summary", "dishes", "heatmap", "eod", "area",
               "avg_acceptance_time", "awt", "contact-rate", "customer_conversion", "customer_retention",
               "customers/summary", "offline_duration", "order_rejection", "orders-marked-as-ready",
               "out-of-stock", "prep_time"]

def gqld(op, variables):
    """Ejecuta un documento .graphql extraído de los plugins (gql/<op>.graphql). Solo queries."""
    q = open(os.path.join(GQL_DIR, op + ".graphql")).read()
    if q.lstrip().startswith("mutation"): raise PyaError("mutations bloqueadas (solo lectura)")
    d = _send("POST", VAGW, {"operationName": op, "query": q, "variables": variables})
    if d.get("errors"): raise PyaError(json.dumps(d["errors"], ensure_ascii=False)[:300])
    return d["data"]

def _rng7(a):
    today = dt.datetime.now(TZ).date()
    e = dt.date.fromisoformat(a.end) if a.end else today
    s = dt.date.fromisoformat(a.start) if a.start else e - dt.timedelta(days=6)
    return s, e

def _codes(vs): return [f"{v['globalEntityId']};{v['platformVendorId']}" for v in vs]
def _gv(vs): return [{"globalEntityId": v["globalEntityId"], "vendorId": v["platformVendorId"]} for v in vs]
def _active(a): return [v for v in stores(a) if v.get("state") != "INACTIVE" or getattr(a, "include_inactive", False)]

def cmd_reviews(a):
    vs = _active(a); s, e = _rng7(a); rows = []
    t0, t1 = _utc_bounds(s, e)
    for v in vs:
        flt = {"startDate": t0, "endDate": t1}
        if a.min_rating: flt["ratingMin"] = a.min_rating
        if a.max_rating: flt["ratingMax"] = a.max_rating
        if a.with_text: flt["hasText"] = True
        pag = {"perPage": 50}
        while True:
            d = _send("POST", VRS + "/v1/reviews", {"global_vendor_codes": _codes([v]), "include_stats": True, "pagination": pag, "filter": flt})
            rv = d.get("reviews") or []
            for r in rv:
                rows.append({"store": v["name"], "date": _ts(r.get("date")), "order_id": r.get("orderId"), "rating": r.get("rating"),
                             "text": (r.get("text") or "").replace("\n", " "), "replied": bool(r.get("reply")),
                             "products": "; ".join(f"{p.get('name')}={p.get('rating')}" for p in r.get("product_ratings") or [])})
            if not d.get("hasNext") and not (d.get("pagination") or {}).get("hasNext") or not rv or len(rv) < 50: break
            last = rv[-1]; pag = {"perPage": 50, "beforeId": last["id"], "beforeTimestamp": last["date"]}
    print(f"{len(rows)} reseñas {s}..{e} en {len({r['store'] for r in rows})} tiendas", file=sys.stderr)
    emit(rows, a)

def cmd_ratings(a):
    vs = _active(a); rows = []
    for i in range(0, len(vs), 50):
        d = _send("POST", VRS + "/v1/ratings", {"global_vendor_codes": _codes(vs[i:i + 50])})
        nm = {f"{v['globalEntityId']};{v['platformVendorId']}": v["name"] for v in vs}
        for r in d.get("avg_ratings") or []:
            c5 = {x["rating"]: x["rating_count"] for x in r.get("ratings") or []}
            rows.append({"store": nm.get(r["global_vendor_code"], r["global_vendor_code"]), "avg": r.get("avg_rating"),
                         "total": r.get("total_rating_count"), **{f"r{k}": c5.get(k, 0) for k in range(1, 6)}})
    rows.sort(key=lambda r: (r["avg"] or 9))
    emit(rows, a)

def _list_orders(vs, s, e, statuses=None):
    t0, t1 = _utc_bounds(s, e); out = []
    params = {"globalVendorCodes": _gv(vs), "timeFrom": t0, "timeTo": t1}
    if statuses: params["filter"] = {"orderStatuses": statuses}
    while True:
        d = gqld("ListOrders", {"params": params})["orders"]["listOrders"]
        out += d.get("orders") or []
        if not d.get("nextPageToken"): return out
        time.sleep(1.5)  # evitar bloqueo PerimeterX (403) en listados largos
        params["pagination"] = {"pageToken": d["nextPageToken"]}

def _iss(x):
    md = x.get("metadata") or []
    md = md if isinstance(md, list) else [md]
    return x["orderIssue"] + "".join(f":{m.get('reason') or ''}:{m.get('amount') or m.get('deduction') or m.get('fee') or ''}" for m in md)

def cmd_orders(a):
    s, e = _rng7(a) if a.start else _range(a); vs = _active(a); rows = []
    for i in range(0, len(vs), 20):
        if i: time.sleep(2)
        for o in _list_orders(vs[i:i + 20], s, e, [x.upper() for x in a.status] if a.status else None):
            iss = o.get("orderIssuesDetails") or []
            if a.issues and not [x for x in iss if x["orderIssue"] != "AVOIDABLE_WAIT_TIME"] and not o.get("totalFeesAndDeductions"): continue
            rows.append({"store": o["vendorName"], "order_id": o["orderId"], "placed": _ts(o["placedTimestamp"]), "status": o["orderStatus"],
                         "subtotal": o.get("subtotal"), "commission": (o.get("billing") or {}).get("commissionAmount"),
                         "net": (o.get("billing") or {}).get("netRevenue"), "fees_deductions": o.get("totalFeesAndDeductions"),
                         "issues": "; ".join(_iss(x) for x in iss)})
    print(f"{len(rows)} pedidos {s}..{e}", file=sys.stderr); emit(rows, a)

def cmd_order(a):
    v = [x for x in stores(a)][0]; gv = _gv([v])[0]
    photos = bool(getattr(a, "photos", False))
    ts = None
    try:
        lst = [o for o in _list_orders([v], *(_rng7(a))) if o["orderId"] == a.order]
        ts = lst[0]["placedTimestamp"] if lst else None
    except PyaError as e:
        if not photos: raise
        print(f"aviso: ListOrders falló ({e}); GetOrderDetails sin placedTimestamp", file=sys.stderr)
    d = gqld("GetOrderDetails", {"params": {"orderId": a.order, "GlobalVendorCode": gv, "placedTimestamp": ts,
             "isBillingDataFlagEnabled": True, "useRefundStreamIssueSource": True},
             "orderIssueParams": {"orderId": a.order, "GlobalVendorCode": gv}, "hasPhotoEvidence": photos})
    out = {"order": d["orders"]["order"]}
    if photos:
        pics = d["orders"].get("orderIssuePictures")
        # no imprimir query firmada de S3 (AWSAccessKeyId / x-amz-security-token)
        if isinstance(pics, dict) and pics.get("urls"):
            red = []
            for u in pics["urls"]:
                ru = {}
                for k in ("original", "compressed", "thumbnail"):
                    v = (u or {}).get(k)
                    ru[k] = (v.split("?", 1)[0] + "?REDACTED") if v else v
                red.append(ru)
            pics = {**pics, "urls": red}
        out["orderIssuePictures"] = pics
    print(json.dumps(out if photos else out["order"], ensure_ascii=False, indent=2))

def cmd_issues(a):
    s, e = _rng7(a); vs = _active(a); rows = []; t0, t1 = _utc_bounds(s, e)
    for v in (vs if a.by_store else [None]):
        sel = [v] if v else vs
        d = gqld("OrderIssueTiles", {"params": {"global_vendor_codes": _codes(sel), "from": t0, "to": t1, "timezone": "America/Santiago"}})
        for t in d["reports"]["orderIssueTiles"]["tiles"]:
            rows.append({"store": v["name"] if v else f"TOTAL ({len(sel)} tiendas)", "type": t["type"], "orders": t["ordersCount"],
                         "amount": t["amount"], "amount_type": t["amountType"], "orders_with_amount": t["ordersAmountCount"]})
    print(f"Problemas de pedidos {s}..{e}", file=sys.stderr); emit(rows, a)

def _accounts():
    f = os.path.expanduser("~/.pya_accounts.json")
    if not os.path.exists(f): c._refresh()
    acc = json.load(open(f))
    return [{"grid": "", "billingParentId": b, "chainId": ""} for b in sorted({x["billing_parent_id"] for x in acc if x.get("billing_parent_id")})]

def cmd_payouts(a):
    s, e = (_rng7(a) if (a.start or a.end) else (dt.datetime.now(TZ).date() - dt.timedelta(days=60), dt.datetime.now(TZ).date()))
    rows, tok = [], None
    while True:
        p = {"globalEntityId": GE, "accounts": _accounts(), "startDate": str(s), "endDate": str(e), "pagination": {"pageSize": 50, **({"pageToken": tok} if tok else {})}}
        d = gqld("ListPayouts", {"params": p})["finances"]["listPayouts"]
        for x in d.get("payouts") or []:
            inv = x.get("invoices") or []
            rows.append({"payout_id": x["payoutId"], "date": x["at"], "status": x["status"], "amount": x["payoutAmount"], "currency": x["payoutCurrency"],
                         "orders": x["payoutOrders"], "account": (x.get("payoutAccount") or {}).get("billingParentId"),
                         "invoices": "; ".join(f"{i['invoiceId']} {i['period']['from']}..{i['period']['to']} {i['invoiceAmount']:.0f}" for i in inv)})
        tok = d.get("nextPageToken")
        if not tok: break
    print(f"{len(rows)} pagos {s}..{e}, total {sum(r['amount'] for r in rows):,.0f} CLP", file=sys.stderr); emit(rows, a)

def cmd_earnings(a):
    s, e = _rng7(a)
    d = gqld("getPayoutEarningsSummary", {"params": {"globalEntityId": GE, "accounts": _accounts(), "startDate": str(s), "endDate": str(e)}, "withBreakdown": True})
    x = d["finances"]["getPayoutEarningsSummary"]
    if a.json: print(json.dumps(x, ensure_ascii=False, indent=2)); return
    rows = [{"concepto": k, "monto": x.get(k)} for k in ("totalGrossSales", "totalCommissions", "totalNetPayout", "ordersCount")]
    b = x.get("breakdown") or {}
    def walk(o, pre):
        for k, v in (o or {}).items():
            if isinstance(v, dict): walk(v, pre + k + ".")
            elif isinstance(v, list):
                for it in v: rows.append({"concepto": pre + k + ":" + str(it.get("reason") or it.get("type")), "monto": it.get("amount")})
            elif v is not None: rows.append({"concepto": pre + k, "monto": v})
    walk(b, "")
    print(f"Resumen de ganancias {s}..{e} ({x.get('currency')})", file=sys.stderr); emit(rows, a)

def cmd_invoices(a):
    d = gqld("ListOutstandingInvoices", {"params": {"globalEntityId": GE, "accounts": _accounts(), "pagination": {"pageSize": 50}}})
    inv = d["finances"]["listOutstandingInvoices"].get("invoices") or []
    s, e = (_rng7(a) if (a.start or a.end) else (dt.datetime.now(TZ).date() - dt.timedelta(days=90), dt.datetime.now(TZ).date()))
    st = gqld("ListAdditionalStatements", {"params": {"globalEntityId": GE, "accounts": _accounts(), "statementDateFrom": str(s), "statementDateTo": str(e), "pagination": {"pageSize": 50}}})
    stl = st["finances"]["listAdditionalStatements"].get("additionalStatements") or []
    print(f"{len(inv)} facturas pendientes; {len(stl)} estados adicionales {s}..{e}", file=sys.stderr)
    emit([{"tipo": "factura_pendiente", **{k: v for k, v in i.items() if not isinstance(v, (dict, list))}} for i in inv] +
         [{"tipo": "estado_adicional", **{k: v for k, v in i.items() if not isinstance(v, (dict, list))}} for i in stl], a)

def cmd_report(a):
    s, e = _rng7(a); vs = _active(a)
    if a.name not in VOS_REPORTS: raise PyaError(f"reporte desconocido; opciones: {', '.join(VOS_REPORTS)}")
    out = []
    for v in (vs if a.by_store else [None]):
        sel = [v] if v else vs
        d = _send("POST", f"{VOS}/{a.name}", {"global_vendor_codes": _codes(sel), "from": str(s), "to": str(e)}).get("data")
        lab = v["name"] if v else "TOTAL"
        if isinstance(d, list): out += [{"store": lab, **{k: (json.dumps(x, ensure_ascii=False) if isinstance(x, (dict, list)) else x) for k, x in r.items()}} for r in d]
        else: out += [{"store": lab, **{k: (json.dumps(x, ensure_ascii=False) if isinstance(x, (dict, list)) else x) for k, x in (d or {}).items()}}]
    print(f"Reporte {a.name} {s}..{e} ({len(vs)} tiendas)", file=sys.stderr); emit(out, a)

def main():
    p = argparse.ArgumentParser(description="PedidosYa Partner Portal CLI")
    sp = p.add_subparsers(dest="cmd", required=True)
    def common(x):
        x.add_argument("-s", "--store", action="append", help="subcadena del nombre (repetible)")
        x.add_argument("--id", action="append", help="platformVendorId (repetible)")
        x.add_argument("--json", action="store_true"); x.add_argument("--csv", action="store_true")
        return x
    def write(x):
        x.add_argument("--yes", action="store_true", help="ejecutar de verdad"); x.add_argument("--dry-run", action="store_true")
    m = common(sp.add_parser("monitor")); m.add_argument("--changes", action="store_true")
    m.add_argument("--only", action="append", help="OPEN, HIGH_DEMAND_MODE, CLOSED, INACTIVE...")
    m.set_defaults(f=cmd_monitor)
    x = common(sp.add_parser("pause")); write(x); x.add_argument("--reason", default="TOO_BUSY_KITCHEN", choices=REASONS)
    x.add_argument("--minutes", type=int, help="minutos; sin valor = resto del día"); x.set_defaults(f=cmd_pause)
    x = common(sp.add_parser("activate")); write(x); x.set_defaults(f=cmd_activate)
    x = common(sp.add_parser("hours")); x.add_argument("--raw", action="store_true"); x.set_defaults(f=cmd_hours)
    for n, fn in (("soldout", cmd_soldout), ("instock", cmd_instock)):
        x = common(sp.add_parser(n)); write(x); x.add_argument("--item", required=True)
        x.add_argument("--contains", action="store_true"); x.set_defaults(f=fn)
        if n == "soldout": x.add_argument("--until", default="indefinite", help="indefinite | tomorrow (próximo día hábil) | N minutos")
    x = common(sp.add_parser("activate-menu")); write(x)
    x.add_argument("--exclude", action="append"); x.add_argument("--exclude-file"); x.add_argument("--no-default-exclude", action="store_true")
    x.set_defaults(f=cmd_activate_menu)
    x = common(sp.add_parser("soldout-report")); x.add_argument("--include-inactive", action="store_true"); x.set_defaults(f=cmd_soldout_report)
    x = common(sp.add_parser("sales")); x.add_argument("--start"); x.add_argument("--end")
    x.add_argument("--by-store", action="store_true"); x.add_argument("--ops", action="store_true")
    x.add_argument("--include-inactive", action="store_true"); x.set_defaults(f=cmd_sales)
    def rng(x): x.add_argument("--start", help="YYYY-MM-DD (Chile)"); x.add_argument("--end"); x.add_argument("--include-inactive", action="store_true"); return x
    x = rng(common(sp.add_parser("reviews"))); x.add_argument("--min-rating", type=int); x.add_argument("--max-rating", type=int)
    x.add_argument("--with-text", action="store_true"); x.set_defaults(f=cmd_reviews)
    x = rng(common(sp.add_parser("ratings"))); x.set_defaults(f=cmd_ratings)
    x = rng(common(sp.add_parser("orders"))); x.add_argument("--status", action="append", help="DELIVERED, CANCELLED, ...")
    x.add_argument("--issues", action="store_true", help="solo pedidos con reclamos/descuentos/cargos"); x.set_defaults(f=cmd_orders)
    x = rng(common(sp.add_parser("order"))); x.add_argument("order"); x.add_argument("--photos", action="store_true", help="incluye orderIssuePictures (urls original/compressed/thumbnail)"); x.set_defaults(f=cmd_order)
    x = rng(common(sp.add_parser("issues"))); x.add_argument("--by-store", action="store_true"); x.set_defaults(f=cmd_issues)
    x = rng(common(sp.add_parser("payouts"))); x.set_defaults(f=cmd_payouts)
    x = rng(common(sp.add_parser("earnings"))); x.set_defaults(f=cmd_earnings)
    x = rng(common(sp.add_parser("invoices"))); x.set_defaults(f=cmd_invoices)
    x = rng(common(sp.add_parser("report"))); x.add_argument("name", help=", ".join(VOS_REPORTS)); x.add_argument("--by-store", action="store_true"); x.set_defaults(f=cmd_report)
    a = p.parse_args()
    try: a.f(a)
    except PyaError as e:
        print("ERROR:", e, file=sys.stderr); sys.exit(1)

if __name__ == "__main__":
    main()
