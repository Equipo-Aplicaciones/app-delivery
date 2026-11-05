(() => {
  const $ = (id) => document.getElementById(id);

  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (v === null || v === undefined || v === false) return;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (v === true) el.setAttribute(k, "");
      else el.setAttribute(k, String(v));
    });
    children.flat(Infinity).forEach((c) => {
      if (c === null || c === undefined || c === false) return;
      el.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
    });
    return el;
  }

  async function api(url, options) {
    const res = await fetch(url, { credentials: "same-origin", ...options });
    if (res.status === 401) {
      window.location.href = "/login";
      throw new Error("No autenticado");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(typeof data.detail === "string" ? data.detail : ("Error " + res.status));
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function clp(n) {
    if (n === null || n === undefined || n === "") return "—";
    const num = Number(n);
    if (Number.isNaN(num)) return String(n);
    return "$" + Math.round(num).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  }

  const ISO_TS = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$/;
  function when(value) {
    if (!value || !ISO_TS.test(String(value))) return value || "";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleString("es-CL", { timeZone: "America/Santiago", day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function setState(el, text, kind) {
    el.textContent = text || "";
    el.className = "state" + (kind ? " " + kind : "");
  }

  function busy(btn, label) {
    const prev = btn.textContent;
    btn.disabled = true;
    btn.textContent = label;
    return () => { btn.disabled = false; btn.textContent = prev; };
  }

  const STATUS_TEXT = {
    configured: "Vigente",
    missing: "Sin cargar",
    expired: "Caducada",
    unknown: "Sin confirmar",
    pending: "Pendiente",
    not_configured: "Sin configurar",
  };

  // ---------- navegación ----------
  const VIEWS = ["monitoreo", "disputas", "credenciales"];
  const loaded = {};

  function showView() {
    const name = (location.hash || "#monitoreo").slice(1).split("/")[0];
    const view = VIEWS.includes(name) ? name : "monitoreo";
    VIEWS.forEach((v) => { $("view-" + v).hidden = v !== view; });
    document.querySelectorAll(".modnav a").forEach((a) => {
      a.classList.toggle("active", a.dataset.view === view);
      if (a.dataset.view === view) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    if (!loaded[view]) {
      loaded[view] = true;
      if (view === "disputas") initDisputes();
      if (view === "credenciales") loadCredentials(false);
    }
  }
  window.addEventListener("hashchange", showView);

  // ---------- disputas ----------
  const dstate = { tab: "uber", uber: null, pya: null, snapshot: null };

  function setDTab(tab) {
    dstate.tab = tab;
    document.querySelectorAll("[data-dtab]").forEach((b) => {
      b.classList.toggle("active", b.dataset.dtab === tab);
      b.setAttribute("aria-selected", b.dataset.dtab === tab ? "true" : "false");
    });
    ["uber", "pedidosya", "buscar"].forEach((t) => { $("dpanel-" + t).hidden = t !== tab; });
  }
  document.querySelectorAll("[data-dtab]").forEach((b) => b.addEventListener("click", () => setDTab(b.dataset.dtab)));

  function table(el, headers, rows, empty) {
    el.innerHTML = "";
    el.classList.add("stack");
    el.appendChild(h("thead", {}, h("tr", {}, headers.map((t) => h("th", { text: t })))));
    const tb = h("tbody");
    if (!rows.length) tb.appendChild(h("tr", { class: "empty" }, h("td", { colspan: headers.length, class: "muted", text: empty })));
    rows.forEach((r) => {
      Array.from(r.children).forEach((td, i) => { if (headers[i]) td.setAttribute("data-label", headers[i]); });
      tb.appendChild(r);
    });
    el.appendChild(tb);
  }

  function sourceLine(data) {
    if (!data) return "";
    const src = data.source === "live" ? "Consulta en vivo" : "Snapshot";
    const at = data.fetched_at ? " · " + when(data.fetched_at) + " (hora de Chile)" : "";
    const win = data.window && (data.window.label || (data.window.start ? data.window.start + " a " + data.window.end : ""));
    return src + at + (win ? " · Ventana " + win : "");
  }

  function errorKind(data) {
    if (data.status === "ok") return "";
    if (data.status === "missing_credentials" || data.auth) return "err";
    return "warn";
  }

  function renderUber() {
    const data = dstate.uber;
    const st = $("u-state");
    if (!data) return;
    const rows = Array.isArray(data.disputes) ? data.disputes : null;
    if (!rows) {
      const lead = data.status === "missing_credentials" ? "" : (data.auth ? "Sesión rechazada por Uber. " : "");
      setState(st, lead + (data.error || "Sin listado.") + " Esto no significa cero cobros.", errorKind(data));
      table($("u-table"), ["Tienda", "Pedido", "Fecha", "Importe", "Incidencia", "Estado", ""], [], "Sin datos de Uber.");
      return;
    }
    const q = ($("u-q").value || "").trim().toLowerCase();
    const shown = rows.filter((d) => !q || ((d.store_name || "") + " " + (d.order_id || "")).toLowerCase().includes(q));
    const amount = shown.reduce((acc, d) => acc + (Number(d.amount_clp) || 0), 0);
    const counters = data.counters ? " · Uber informa " + Object.entries(data.counters).map(([k, v]) => k + ": " + v).join(", ") : "";
    setState(st, sourceLine(data) + " · " + shown.length + " cobros, " + clp(amount) + (data.truncated ? " (lista truncada)" : "") + counters, "");
    table(
      $("u-table"),
      ["Tienda", "Pedido", "Fecha", "Importe", "Incidencia", "Estado", ""],
      shown.map((d) => h("tr", {},
        h("td", { text: d.store_name || "—" }),
        h("td", { class: "mono", text: d.order_id || "—" }),
        h("td", { text: d.ordered_at || "—" }),
        h("td", { class: "num", text: d.amount_display || clp(d.amount_clp) }),
        h("td", { text: [d.issue, d.tag].filter(Boolean).join(" · ") || "—" }),
        h("td", { text: d.state || "—" }),
        h("td", {}, h("button", { type: "button", class: "small-btn", onclick: () => openUber(d.order_id, d) }, "Abrir"))
      )),
      "Ningún cobro coincide."
    );
  }

  async function loadUber(live) {
    const btn = $("u-live");
    const done = live ? busy(btn, "Consultando Uber…") : () => {};
    const params = new URLSearchParams({ platform: "uber", status: $("u-status").value });
    if (live) params.set("live", "true");
    if ($("u-start").value) params.set("start", $("u-start").value);
    if ($("u-end").value) params.set("end", $("u-end").value);
    if (live) setState($("u-state"), "Consultando Uber en solo lectura. Puede tardar unos minutos con muchas tiendas.", "");
    try {
      dstate.uber = await api("/api/disputes?" + params.toString());
      renderUber();
    } catch (err) {
      setState($("u-state"), err.message, "err");
    } finally {
      done();
    }
  }

  function renderPya() {
    const data = dstate.pya;
    if (!data) return;
    const tiles = Array.isArray(data.complaint_tiles) ? data.complaint_tiles : null;
    if (!tiles) {
      setState($("p-state"), (data.auth && data.status !== "missing_credentials" ? "Sesión rechazada por PedidosYa. " : "") + (data.error || "Sin reclamos.") + " Esto no significa cero reclamos.", errorKind(data));
      table($("p-table"), ["Tienda / agregado", "Tipo", "Pedidos", "Monto", "Qué es"], [], "Sin datos de PedidosYa.");
      return;
    }
    setState($("p-state"), sourceLine(data) + " · " + tiles.length + " mosaicos de reclamo", "");
    table(
      $("p-table"),
      ["Tienda / agregado", "Tipo", "Pedidos", "Monto", "Qué es"],
      tiles.map((t) => h("tr", {},
        h("td", { text: t.store || "—" }),
        h("td", { text: t.type || "—" }),
        h("td", { class: "num", text: t.orders == null ? "—" : String(t.orders) }),
        h("td", { class: "num", text: t.amount == null ? "—" : String(t.amount) }),
        h("td", { class: "muted", text: t.note || "Reclamo, no disputa" })
      )),
      "Sin mosaicos de reclamo en este periodo."
    );
  }

  async function loadPya(live) {
    const btn = $("p-live");
    const done = live ? busy(btn, "Consultando…") : () => {};
    const params = new URLSearchParams({ platform: "pedidosya" });
    if (live) params.set("live", "true");
    if ($("p-start").value) params.set("start", $("p-start").value);
    if ($("p-end").value) params.set("end", $("p-end").value);
    if ($("p-bystore").checked) params.set("by_store", "true");
    try {
      dstate.pya = await api("/api/disputes?" + params.toString());
      renderPya();
    } catch (err) {
      setState($("p-state"), err.message, "err");
    } finally {
      done();
    }
  }

  async function fillPyaStores() {
    const sel = $("p-store");
    sel.innerHTML = "";
    try {
      dstate.snapshot = dstate.snapshot || await api("/api/snapshot");
    } catch (err) {
      dstate.snapshot = { stores: [] };
    }
    const stores = (dstate.snapshot.stores || []).filter((s) => s.platform === "pedidosya" && s.store_id);
    if (!stores.length) {
      sel.appendChild(h("option", { value: "", text: "Sin tiendas en el snapshot" }));
      return;
    }
    sel.appendChild(h("option", { value: "", text: "Elija la tienda" }));
    stores.sort((a, b) => String(a.name).localeCompare(String(b.name))).forEach((s) => {
      sel.appendChild(h("option", { value: s.store_id, text: s.name }));
    });
  }

  function initDisputes() {
    setDTab("uber");
    loadUber(false);
    loadPya(false);
    fillPyaStores();
  }

  $("u-live").addEventListener("click", () => loadUber(true));
  $("u-status").addEventListener("change", () => loadUber(dstate.uber && dstate.uber.source === "live"));
  $("u-q").addEventListener("input", renderUber);
  $("p-live").addEventListener("click", () => loadPya(true));
  $("p-open").addEventListener("submit", (e) => {
    e.preventDefault();
    const order = $("p-order").value.trim();
    const store = $("p-store").value;
    if (!order || !store) return;
    openPya(order, store, $("p-photos").checked);
  });

  $("e-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const agg = $("e-agg").value;
    const order = $("e-order").value.trim();
    const box = $("e-result");
    box.innerHTML = "";
    if (!order) return;
    box.appendChild(h("p", { class: "state", text: "Buscando fotos de la app…" }));
    try {
      const data = await api("/api/evidence/" + encodeURIComponent(agg) + "?numero_orden=" + encodeURIComponent(order));
      box.innerHTML = "";
      box.appendChild(appEvidenceBlock(data, null));
      const open = agg === "uber"
        ? h("button", { type: "button", class: "ghost", onclick: () => openUber(order, null) }, "Abrir ficha de Uber de este pedido")
        : h("p", { class: "muted small", text: "Para ver el pedido en PedidosYa, ábralo por número en la pestaña PedidosYa (requiere la tienda)." });
      box.appendChild(h("div", { class: "row" }, open));
    } catch (err) {
      box.innerHTML = "";
      box.appendChild(h("p", { class: "state err", text: err.message }));
    }
  });

  // ---------- ficha ----------
  function openDrawer(kicker, title) {
    $("dr-kicker").textContent = kicker;
    $("dr-title").textContent = title;
    $("dr-body").innerHTML = "";
    $("drawer").hidden = false;
    document.body.classList.add("no-scroll");
    return $("dr-body");
  }
  function closeDrawer() {
    $("drawer").hidden = true;
    document.body.classList.remove("no-scroll");
  }
  document.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", closeDrawer));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("drawer").hidden) closeDrawer(); });

  function kv(pairs) {
    return h("dl", { class: "kv" }, pairs.filter((p) => p[1] !== null && p[1] !== undefined && p[1] !== "").map(([k, v]) =>
      [h("dt", { text: k }), h("dd", { text: String(v) })]
    ));
  }

  function fetchNote(fetch) {
    if (!fetch || fetch.status === "ok") return null;
    if (fetch.status === "cached") return h("p", { class: "muted small", text: "Datos guardados en el panel. Use «Volver a descargar» para consultar la plataforma." });
    return h("p", { class: "state " + (fetch.auth ? "err" : "warn"), text: fetch.error || "No se pudo consultar la plataforma." });
  }

  function mediaTile(item, opts) {
    const ctype = item.content_type || "";
    const isImg = ctype.startsWith("image/") || opts.app;
    const fig = h("figure", { class: "tile" + (item.sensitive ? " sensitive" : "") });
    if (isImg) {
      fig.appendChild(h("a", { href: item.url, target: "_blank", rel: "noopener" },
        h("img", { src: item.url, alt: opts.alt, loading: "lazy" })));
    } else {
      fig.appendChild(h("a", { href: item.url, target: "_blank", rel: "noopener", class: "file" }, ctype.includes("pdf") ? "PDF" : "Archivo"));
    }
    if (item.sensitive) {
      fig.appendChild(h("button", { type: "button", class: "reveal", onclick: (e) => { fig.classList.remove("sensitive"); e.currentTarget.remove(); } }, "Mostrar imagen sensible"));
    }
    const cap = h("figcaption", {});
    if (opts.selectable) {
      const cb = h("input", { type: "checkbox", value: item.id, "data-kind": opts.app ? "app" : "media" });
      cb.addEventListener("change", opts.onSelect);
      cap.appendChild(h("label", { class: "check" }, cb, " Usar como evidencia"));
    }
    if (opts.platform) {
      const toggle = h("button", { type: "button", class: "ghost small-btn" }, item.sensitive ? "Quitar marca sensible" : "Marcar sensible");
      toggle.addEventListener("click", async () => {
        toggle.disabled = true;
        try {
          const res = await api("/api/media/" + opts.platform + "/" + encodeURIComponent(opts.order) + "/" + encodeURIComponent(item.id), {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sensitive: !item.sensitive }),
          });
          item.sensitive = res.item.sensitive;
          fig.replaceWith(mediaTile(item, opts));
        } catch (err) {
          toggle.disabled = false;
          toggle.textContent = err.message;
        }
      });
      cap.appendChild(toggle);
    }
    if (opts.app && item.created_at) cap.appendChild(h("span", { class: "muted small", text: "Subida " + when(item.created_at) }));
    fig.appendChild(cap);
    return fig;
  }

  function gallery(items, opts, empty) {
    if (!items.length) return h("p", { class: "muted", text: empty });
    return h("div", { class: "gallery" }, items.map((it) => mediaTile(it, opts)));
  }

  function appEvidenceBlock(ev, selectOpts) {
    const wrap = h("div", { class: "block" }, h("h3", { text: "Fotos de la tienda (app delivery)" }));
    if (!ev || ev.status === "not_configured") {
      wrap.appendChild(h("p", { class: "state warn", text: (ev && ev.error) || "API de evidencia sin configurar." }));
      return wrap;
    }
    if (ev.status !== "ok") {
      wrap.appendChild(h("p", { class: "state " + (ev.auth ? "err" : "warn"), text: (ev.auth ? "La API de evidencia rechazó la clave. " : "") + (ev.error || "No se pudo leer la API de evidencia.") + " No significa que no haya fotos." }));
      return wrap;
    }
    wrap.appendChild(gallery(ev.images || [], { app: true, alt: "Foto subida por la tienda", ...(selectOpts || {}) }, "La tienda no subió fotos para este pedido en la app delivery."));
    return wrap;
  }

  async function openUber(orderId, row, refresh) {
    const body = openDrawer("Uber · cobro", "Pedido " + orderId);
    body.appendChild(h("p", { class: "state", text: refresh ? "Descargando fotos desde Uber…" : "Cargando ficha…" }));
    let data;
    try {
      const params = new URLSearchParams();
      if (refresh) params.set("refresh", "true");
      data = await api("/api/disputes/uber/" + encodeURIComponent(orderId) + (params.toString() ? "?" + params : ""));
    } catch (err) {
      body.innerHTML = "";
      body.appendChild(h("p", { class: "state err", text: err.message }));
      return;
    }
    body.innerHTML = "";
    const charge = data.charge || row || {};
    const meta = data.meta || {};
    body.appendChild(h("div", { class: "block" },
      h("h3", { text: "Datos del cobro" }),
      kv([
        ["Tienda", charge.store_name || meta.store],
        ["Fecha", charge.ordered_at],
        ["Importe", charge.amount_display || (charge.amount_clp != null ? clp(charge.amount_clp) : null)],
        ["Incidencia", charge.issue || meta.issue],
        ["Etiqueta", charge.tag || meta.tag],
        ["Estado", charge.state || meta.dispute_status],
        ["Comentario del cliente", meta.customer_comment],
        ["Explicación de Uber", meta.ai_explanation],
        ["Descargado", when(meta.fetched_at)],
      ]),
      fetchNote(data.platform_fetch),
      h("div", { class: "row" }, h("button", { type: "button", class: "ghost small-btn", onclick: () => openUber(orderId, row, true) }, "Volver a descargar desde Uber"))
    ));

    const selected = new Set();
    let form;
    const onSelect = (e) => {
      const key = e.target.dataset.kind + ":" + e.target.value;
      if (e.target.checked) {
        if (selected.size >= 3) { e.target.checked = false; alert("Uber acepta como máximo 3 archivos de evidencia."); return; }
        selected.add(key);
      } else selected.delete(key);
      if (form) form.querySelector("[data-count]").textContent = selected.size + " de 3 evidencias elegidas";
    };
    const pm = data.platform_media || [];
    body.appendChild(h("div", { class: "block" },
      h("h3", { text: "Fotos del cliente (Uber)" }),
      gallery(pm.filter((m) => m.group === "cliente"), { platform: "uber", order: orderId, alt: "Foto del cliente" }, "Sin fotos del cliente descargadas."),
      h("h3", { text: "Evidencia de la tienda ya enviada a Uber" }),
      gallery(pm.filter((m) => m.group === "tienda"), { platform: "uber", order: orderId, alt: "Evidencia de la tienda", selectable: true, onSelect }, "Sin evidencia de tienda en Uber.")
    ));
    body.appendChild(appEvidenceBlock(data.app_evidence, { selectable: true, onSelect }));

    const sub = data.submit || {};
    form = h("form", { class: "block dispute-form" },
      h("h3", { text: "Preparar disputa" }),
      h("p", { class: "muted small", text: "Primero se arma un dry-run con uber.py: nada se envía a Uber. " + (sub.note || "") }),
      h("label", {}, "Motivo",
        h("select", { name: "reason", required: true }, (sub.reasons || []).map((r) => h("option", { value: r, text: r })))),
      h("label", {}, "Descripción", h("textarea", { name: "description", rows: 3, maxlength: 2000, placeholder: "Obligatoria con OTHER" })),
      h("p", { class: "muted small", "data-count": true, text: "0 de 3 evidencias elegidas" }),
      !sub.can_prepare ? h("p", { class: "state warn", text: "Faltan datos internos del cobro (" + (sub.missing || []).join(", ") + "). Consulte Uber ahora en el listado para completarlos." }) : null,
      h("div", { class: "row" },
        h("button", { type: "submit", disabled: !sub.can_prepare }, "Preparar (dry-run)"),
        h("button", { type: "button", class: "danger", "data-confirm": true, disabled: true, title: sub.real_submit_enabled ? "" : "Envío real deshabilitado en el servidor" }, "Enviar a Uber")
      ),
      h("p", { class: "muted small", text: sub.real_submit_enabled ? "El envío real está habilitado en el servidor; exige un dry-run previo." : "Envío real deshabilitado (ALLOW_UBER_DISPUTE_SUBMIT apagado)." }),
      h("div", { "data-result": true })
    );
    const payload = (confirm) => ({
      reason: form.elements.namedItem("reason").value,
      description: form.elements.namedItem("description").value,
      evidence_ids: [...selected].filter((k) => k.startsWith("media:")).map((k) => k.slice(6)),
      app_evidence_ids: [...selected].filter((k) => k.startsWith("app:")).map((k) => k.slice(4)),
      confirm,
    });
    const result = form.querySelector("[data-result]");
    const confirmBtn = form.querySelector("[data-confirm]");
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = form.querySelector("button[type=submit]");
      const done = busy(btn, "Preparando…");
      result.innerHTML = "";
      try {
        const res = await api("/api/disputes/uber/" + encodeURIComponent(orderId) + "/submit", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload(false)),
        });
        result.appendChild(planView(res));
        confirmBtn.disabled = !sub.real_submit_enabled || (res.results[0].problems || []).length > 0;
      } catch (err) {
        result.appendChild(h("p", { class: "state err", text: err.message }));
      } finally {
        done();
      }
    });
    confirmBtn.addEventListener("click", async () => {
      if (!window.confirm("Esto envía la disputa a Uber de verdad. El envío no está verificado en vivo. ¿Continuar?")) return;
      const done = busy(confirmBtn, "Enviando…");
      try {
        const res = await api("/api/disputes/uber/" + encodeURIComponent(orderId) + "/submit", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload(true)),
        });
        result.appendChild(h("p", { class: "state warn", text: "Enviado, sin verificar: " + (res.note || "") }));
      } catch (err) {
        result.appendChild(h("p", { class: "state err", text: err.message }));
      } finally {
        done();
        confirmBtn.disabled = true;
      }
    });
    body.appendChild(form);
  }

  function planView(res) {
    const r = (res.results || [])[0] || {};
    const problems = r.problems || [];
    const files = r.evidence_files || [];
    return h("div", { class: "plan" },
      h("p", { class: "state " + (problems.length ? "warn" : "ok"), text: problems.length ? "El dry-run encontró problemas: Uber probablemente rechazaría el envío." : "Dry-run listo: nada se envió a Uber." }),
      kv([
        ["Pedido", r.order],
        ["Tienda", r.store],
        ["Elegibilidad", r.eligibility ? JSON.stringify(r.eligibility) : null],
        ["Transporte", r.transport],
        ["Evidencias", files.length ? files.map((f) => (f.path || "archivo") + (f.bytes ? " (" + Math.round(f.bytes / 1024) + " KB)" : "")).join(", ") : "ninguna"],
      ]),
      problems.length ? h("ul", { class: "problems" }, problems.map((p) => h("li", { text: typeof p === "string" ? p : JSON.stringify(p) }))) : null,
      h("p", { class: "muted small", text: res.note || "" })
    );
  }

  async function openPya(orderId, storeId, photos) {
    const body = openDrawer("PedidosYa · pedido", "Pedido " + orderId);
    body.appendChild(h("p", { class: "state", text: photos ? "Consultando el pedido y sus fotos…" : "Consultando el pedido…" }));
    let data;
    try {
      const params = new URLSearchParams({ store_id: storeId });
      if (photos) params.set("photos", "true");
      data = await api("/api/orders/pedidosya/" + encodeURIComponent(orderId) + "?" + params.toString());
    } catch (err) {
      body.innerHTML = "";
      body.appendChild(h("p", { class: "state err", text: err.message }));
      return;
    }
    body.innerHTML = "";
    const o = data.order || {};
    body.appendChild(h("div", { class: "block" },
      h("h3", { text: "Datos del pedido" }),
      fetchNote(data.platform_fetch),
      data.order ? kv([
        ["Local", o.vendor_name],
        ["Fecha", o.placed],
        ["Estado", o.status],
        ["Valor", o.order_value_display],
        ["Reclamos", (o.order_issues || []).map((i) => [i.issue, i.reason, i.amount].filter(Boolean).join(" · ")).join("; ")],
        ["Reembolsos", (o.refunds || []).map((r) => [r.amount, r.status, r.issue].filter(Boolean).join(" · ")).join("; ")],
        ["Estado de disputa", o.dispute_status],
      ]) : null,
      (o.items || []).length ? h("ul", { class: "items" }, o.items.map((it) => h("li", { text: (it.quantity || 1) + " × " + (it.name || "—") + ((it.options || []).length ? " (" + it.options.join(", ") + ")" : "") }))) : null
    ));
    const pics = data.pictures;
    body.appendChild(h("div", { class: "block" },
      h("h3", { text: "Fotos del reclamo (PedidosYa)" }),
      pics ? h("p", { class: "muted small", text: pics.count + " fotos informadas, " + pics.downloaded + " descargadas" + (pics.failed ? ", " + pics.failed + " fallaron" : "") }) : null,
      gallery((data.platform_media || []), { platform: "pedidosya", order: orderId, alt: "Foto del reclamo" }, photos ? "Sin fotos del reclamo." : "No se pidieron fotos.")
    ));
    body.appendChild(appEvidenceBlock(data.app_evidence, null));
    body.appendChild(h("div", { class: "block" },
      h("h3", { text: "Disputa" }),
      h("p", { class: "note", text: (data.dispute_submit && data.dispute_submit.note) || "Envío de disputa no disponible por API." }),
      h("button", { type: "button", disabled: true }, "Enviar disputa (no disponible por API)")
    ));
  }

  // ---------- credenciales ----------
  async function loadCredentials(check) {
    const box = $("c-cards");
    if (check || !box.children.length) {
      box.innerHTML = "";
      box.appendChild(h("p", { class: "state", text: check ? "Probando cada sesión con una lectura mínima…" : "Cargando estado…" }));
    }
    try {
      const data = await api("/api/credentials/status" + (check ? "?check=true" : ""));
      box.innerHTML = "";
      data.sources.forEach((s) => {
        box.appendChild(h("article", { class: "card cred" },
          h("div", { class: "cred-head" },
            h("span", { class: "light light-" + s.status, "aria-hidden": "true" }),
            h("h3", { text: s.label })
          ),
          h("p", { class: "status status-" + s.status, text: STATUS_TEXT[s.status] || s.status }),
          h("p", { class: "muted small", text: s.detail || "" }),
          h("p", { class: "muted small", text: s.checked_at ? "Chequeado " + when(s.checked_at) : "Sin chequeo" })
        ));
      });
    } catch (err) {
      box.innerHTML = "";
      box.appendChild(h("p", { class: "state err", text: err.message }));
    }
  }

  $("c-check").addEventListener("click", async (e) => {
    const done = busy(e.currentTarget, "Chequeando…");
    await loadCredentials(true);
    done();
  });

  ["uber", "pedidosya"].forEach((source) => {
    const form = $("c-" + source);
    const out = form.querySelector("[data-result]");
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData();
      const file = form.elements.namedItem("file").files[0];
      const pasted = form.elements.namedItem("value").value;
      if (file) fd.append("file", file);
      else if (pasted.trim()) fd.append("value", pasted);
      else { setState(out, "Pegue el valor o elija un archivo.", "warn"); return; }
      const done = busy(form.querySelector("button[type=submit]"), "Probando…");
      setState(out, "Probando la sesión nueva sin tocar la vigente…", "");
      try {
        const res = await api("/api/credentials/" + source, { method: "PUT", body: fd });
        setState(out, "Guardada. " + res.detail + " (" + res.length + ").", "ok");
        loadCredentials(false);
      } catch (err) {
        setState(out, err.message, "err");
      } finally {
        form.reset();
        done();
      }
    });
    form.querySelector("[data-delete]").addEventListener("click", async () => {
      try {
        const plan = await api("/api/credentials/" + source, { method: "DELETE" });
        const exists = plan.results && plan.results[0] && plan.results[0].would_delete;
        if (!exists) { setState(out, "No hay archivo de sesión guardado por el panel.", "warn"); return; }
        if (!window.confirm("¿Borrar la sesión guardada? Las consultas a esta plataforma dejarán de funcionar hasta reponerla.")) return;
        const res = await api("/api/credentials/" + source + "?confirm=true", { method: "DELETE" });
        setState(out, res.results[0].deleted ? "Sesión borrada." : "No había nada que borrar.", "warn");
        loadCredentials(false);
      } catch (err) {
        setState(out, err.message, "err");
      }
    });
  });

  showView();
})();
