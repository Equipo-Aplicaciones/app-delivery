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
    const opts = { credentials: "same-origin", ...(options || {}) };
    if (opts.json !== undefined) {
      opts.method = opts.method || "POST";
      opts.headers = { "Content-Type": "application/json" };
      opts.body = JSON.stringify(opts.json);
      delete opts.json;
    }
    const res = await fetch(url, opts);
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

  const ISO_TS = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$/;
  function when(value) {
    if (!value) return "—";
    if (!ISO_TS.test(String(value))) return String(value);
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    return d.toLocaleString("es-CL", { timeZone: "America/Santiago", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  }
  function clp(n) {
    if (n === null || n === undefined || n === "") return "—";
    const num = Number(n);
    if (Number.isNaN(num)) return String(n);
    return "$" + Math.round(num).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
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

  const PLAT_LABEL = { uber: "Uber Eats", pedidosya: "PedidosYa" };
  const STATE_LABEL = { pendiente: "Pendiente", abierta: "Abierta", ganada: "Ganada", perdida: "Perdida", preparada: "Request armado" };
  const ISSUE_LABEL = {
    ISSUE_WITH_ITEMS: "Problema con productos", WRONG_ORDER: "Pedido equivocado", FOOD_QUALITY: "Calidad",
    MISSING_ITEMS: "Faltan productos", CUSTOMER_COMPLAINTS: "Reclamo del cliente", AVOIDABLE_CANCELLATIONS: "Cancelación evitable",
    ORDERS_WITH_DEDUCTION: "Descuento", MISSING_ITEM: "Falta producto", WRONG_ITEM: "Producto equivocado",
  };
  const issueText = (v) => (v ? String(v).split(", ").map((x) => ISSUE_LABEL[x] || x).join(", ") : "—");

  const st = { view: "uber", plat: "uber", estado: "pendiente", meta: null, polling: {}, autoRefreshed: {} };

  // ---------- menú hamburguesa ----------
  function openMenu(open) {
    $("menu").hidden = !open;
    $("burger").setAttribute("aria-expanded", open ? "true" : "false");
    document.body.classList.toggle("no-scroll", open);
  }
  $("burger").addEventListener("click", () => openMenu($("menu").hidden));
  $("menu").addEventListener("click", (ev) => {
    if (ev.target.closest("[data-close]") || ev.target.closest("a")) openMenu(false);
  });

  function route() {
    const name = (location.hash || "#uber").slice(1);
    st.view = ["uber", "pedidosya", "credenciales"].includes(name) ? name : "uber";
    document.querySelectorAll(".dp-menu a").forEach((a) => a.classList.toggle("active", a.dataset.view === st.view));
    const isCred = st.view === "credenciales";
    $("view-disputas").hidden = isCred;
    $("view-credenciales").hidden = !isCred;
    $("refresh").hidden = isCred;
    $("period").closest("label").hidden = isCred;
    if (isCred) {
      document.body.dataset.plat = "";
      $("title").textContent = "Credenciales";
      $("subtitle").textContent = "Uber, PedidosYa y fotos de la app";
      loadCreds(false);
      return;
    }
    st.plat = st.view;
    document.body.dataset.plat = st.plat;
    $("title").textContent = (window.matchMedia("(max-width: 640px)").matches ? "" : "Disputas · ") + PLAT_LABEL[st.plat];
    $("period").value = String(st.plat === "uber" ? (st.uberDays || 30) : (st.pyaDays || 7));
    $("manual-plat").value = st.plat;
    $("q").value = "";
    loadAll();
  }
  window.addEventListener("hashchange", route);

  // ---------- estadísticas ----------
  function stat(cls, label, value, foot) {
    return h("div", { class: "stat " + cls }, h("span", { text: label }), h("strong", { text: value }), foot ? h("small", { text: foot }) : null);
  }

  function renderStats(s) {
    const box = $("stats");
    box.textContent = "";
    const b = s.by_state || {};
    const n = (k) => (b[k] ? b[k].count : 0);
    const amt = (k) => (b[k] ? clp(b[k].amount_clp) : "—");
    document.querySelectorAll(".chip[data-estado]").forEach((c) => {
      const k = c.dataset.estado;
      const span = c.querySelector("span");
      if (span) span.textContent = s.fetched_at || n(k) ? String(n(k)) : "";
    });
    const rate = s.success_rate === null || s.success_rate === undefined ? "—" : s.success_rate + "%";
    if (s.platform === "uber") {
      box.append(
        stat("pend", "Cobros sin disputar", String(n("pendiente")), amt("pendiente") + " cobrados"),
        stat("open", "Disputas abiertas", String(n("abierta")), amt("abierta") + " en revisión"),
        stat("won", "Ganadas", String(n("ganada")), amt("ganada") + " recuperados"),
        stat("lost", "Perdidas", String(n("perdida")), amt("perdida") + " no recuperados"),
        stat("plat", "Tasa de éxito", rate, "ganadas / cerradas"),
        stat("plat", "Requests armados", String(s.prepared || 0), "listos para enviar"),
      );
      const c = s.uber_counters || {};
      const extra = h("div", { class: "stat-wide" });
      if (s.uber_counters) {
        extra.append(
          h("span", {}, "Con incidencia reportada: ", h("b", { text: String(c.issueReported ?? "—") })),
          h("span", {}, "No entregados: ", h("b", { text: String(c.missed ?? "—") })),
          h("span", {}, "Cancelados: ", h("b", { text: String(c.canceled ?? "—") })),
        );
      }
      if ((s.top_stores_pending || []).length) {
        extra.append(h("span", {}, "Más cobros pendientes: ", h("b", { text: s.top_stores_pending.slice(0, 3).map((t) => t.name + " (" + t.count + ")").join(" · ") })));
      }
      if (extra.children.length) box.append(extra);
    } else {
      const tile = (type) => (s.tiles || []).find((t) => t.type === type) || null;
      const comp = tile("CUSTOMER_COMPLAINTS");
      const ded = tile("ORDERS_WITH_DEDUCTION");
      const canc = tile("AVOIDABLE_CANCELLATIONS");
      const wait = tile("AVOIDABLE_WAIT_TIME");
      box.append(
        stat("pend", "Pedidos con problemas", comp ? String(comp.orders) : "—", comp ? clp(comp.amount_clp) + " descontados" : "reclamos de clientes"),
        stat("plat", "Pedidos con descuento", ded ? String(ded.orders) : "—", ded ? clp(ded.amount_clp) + " en total" : ""),
        stat("lost", "Cancelaciones evitables", canc ? String(canc.orders) : "—", canc ? clp(canc.amount_clp) + " en cargos" : ""),
        stat("open", "Reclamos abiertos", String(n("abierta")), "registrados en el panel"),
        stat("won", "Ganados", String(n("ganada")), amt("ganada")),
        stat("lost", "Perdidos", String(n("perdida")), "tasa de éxito " + rate),
      );
      const extra = h("div", { class: "stat-wide" });
      if (wait) extra.append(h("span", {}, "Espera evitable del repartidor: ", h("b", { text: String(wait.orders) + " pedidos" })));
      if ((s.top_stores_problems || []).length) {
        extra.append(h("span", {}, "Más reclamos: ", h("b", { text: s.top_stores_problems.slice(0, 3).map((t) => t.name + " (" + t.count + ")").join(" · ") })));
      }
      extra.append(h("span", { text: s.note }));
      box.append(extra);
    }
    const win = s.window && s.window.label ? " · " + s.window.label : "";
    $("subtitle").textContent = s.fetched_at ? "Actualizado " + when(s.fetched_at) + win : "Sin datos todavía";
    const job = s.refresh || {};
    if (job.running) setState($("stats-state"), "Consultando " + PLAT_LABEL[s.platform] + "… puede tardar un par de minutos.");
    else if (s.status === "missing_credentials") setState($("stats-state"), (s.error || "Faltan credenciales") + " ", "warn");
    else if (s.error) setState($("stats-state"), s.error, "err");
    else if (!s.fetched_at) setState($("stats-state"), "Aún no hay datos de " + PLAT_LABEL[s.platform] + ". Pulse «Actualizar».", "warn");
    else setState($("stats-state"), "");
  }

  async function loadStats() {
    const plat = st.plat;
    try {
      const s = await api("/api/panel/stats?platform=" + plat);
      if (plat !== st.plat) return null;
      renderStats(s);
      return s;
    } catch (e) {
      setState($("stats-state"), e.message, "err");
      return null;
    }
  }

  // ---------- listado ----------
  function badge(state) {
    return h("span", { class: "badge " + state, text: STATE_LABEL[state] || state });
  }

  async function loadList() {
    const plat = st.plat;
    const q = $("q").value.trim();
    setState($("list-state"), "Cargando…");
    try {
      const d = await api("/api/panel/disputes?platform=" + plat + "&estado=" + st.estado + (q ? "&q=" + encodeURIComponent(q) : ""));
      if (plat !== st.plat) return;
      const headers = ["Pedido", "Tienda", "Fecha", "Problema", "Monto", "Estado", ""];
      const tbl = $("list");
      tbl.textContent = "";
      tbl.classList.add("stack");
      tbl.appendChild(h("thead", {}, h("tr", {}, headers.map((t) => h("th", { text: t })))));
      const tb = h("tbody");
      d.rows.forEach((r) => {
        const rec = r.record && r.record.state === "preparada" ? badge("preparada") : null;
        const tr = h("tr", {},
          h("td", { "data-label": "Pedido" }, h("strong", { class: "mono", text: r.order_id }), r.manual ? h("div", { class: "muted small", text: "agregado a mano" }) : null),
          h("td", { "data-label": "Tienda", text: r.store_name || "—" }),
          h("td", { "data-label": "Fecha", text: when(r.ordered_at) }),
          h("td", { "data-label": "Problema", text: issueText(r.issue) }),
          h("td", { "data-label": "Monto", class: "num", text: r.amount_clp !== null && r.amount_clp !== undefined ? clp(r.amount_clp) : (r.amount_display || "—") }),
          h("td", { "data-label": "Estado" }, badge(r.state), rec ? " " : null, rec),
          h("td", {}, h("button", { type: "button", class: "small-btn", text: r.state === "pendiente" ? "Armar disputa" : "Ver", onclick: () => openOrder(plat, r.order_id) })));
        tb.appendChild(tr);
      });
      if (!d.rows.length) {
        let msg = "No hay pedidos en este estado.";
        if (d.status === "pending" && !d.fetched_at) msg = "Aún no hay datos: pulse «Actualizar».";
        tb.appendChild(h("tr", { class: "empty" }, h("td", { colspan: headers.length, class: "muted", text: msg })));
      }
      tbl.appendChild(tb);
      const parts = [d.count + " pedido(s)" + (d.truncated ? " (se muestran 1000)" : "")];
      let kind = "";
      if (plat === "pedidosya" && d.orders_error) { parts.push(d.orders_error); kind = "warn"; }
      setState($("list-state"), parts.join(" · "), kind);
    } catch (e) {
      setState($("list-state"), e.message, "err");
    }
  }

  async function loadAll() {
    const s = await loadStats();
    loadList();
    if (s && !s.fetched_at && !(s.refresh || {}).running && !st.autoRefreshed[s.platform] && s.status !== "missing_credentials") {
      st.autoRefreshed[s.platform] = true;
      startRefresh();
    } else if (s && (s.refresh || {}).running) {
      poll(s.platform);
    }
  }

  document.querySelectorAll(".chip[data-estado]").forEach((c) => c.addEventListener("click", () => {
    st.estado = c.dataset.estado;
    document.querySelectorAll(".chip[data-estado]").forEach((x) => x.classList.toggle("active", x === c));
    loadList();
  }));
  let qTimer = null;
  $("q").addEventListener("input", () => { clearTimeout(qTimer); qTimer = setTimeout(loadList, 250); });
  $("period").addEventListener("change", () => {
    if (st.plat === "uber") st.uberDays = Number($("period").value);
    else st.pyaDays = Number($("period").value);
  });

  // ---------- actualizar ----------
  async function startRefresh() {
    const plat = st.plat;
    const btn = $("refresh");
    btn.disabled = true;
    try {
      await api("/api/panel/refresh", { json: { platform: plat, days: Number($("period").value) } });
      setState($("stats-state"), "Consultando " + PLAT_LABEL[plat] + "… puede tardar un par de minutos.");
      poll(plat);
    } catch (e) {
      btn.disabled = false;
      setState($("stats-state"), e.message, "err");
    }
  }
  function poll(plat) {
    if (st.polling[plat]) return;
    $("refresh").disabled = true;
    st.polling[plat] = setInterval(async () => {
      try {
        const job = await api("/api/panel/refresh?platform=" + plat);
        if (job.running) return;
        clearInterval(st.polling[plat]);
        delete st.polling[plat];
        if (plat === st.plat) {
          $("refresh").disabled = false;
          await loadStats();
          loadList();
          if (job.status === "error") setState($("stats-state"), job.error || "La consulta falló", "err");
        }
      } catch (e) {
        clearInterval(st.polling[plat]);
        delete st.polling[plat];
        $("refresh").disabled = false;
      }
    }, 3000);
  }
  $("refresh").addEventListener("click", startRefresh);

  // ---------- ficha y request ----------
  function closeAll(id) {
    $(id).hidden = true;
    document.body.classList.remove("no-scroll");
  }
  ["sheet", "manual-dlg"].forEach((id) => {
    $(id).addEventListener("click", (ev) => { if (ev.target.closest("[data-close]")) closeAll(id); });
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    ["sheet", "manual-dlg"].forEach((id) => { if (!$(id).hidden) closeAll(id); });
    if (!$("menu").hidden) openMenu(false);
  });

  $("manual").addEventListener("click", () => {
    $("manual-plat").value = st.plat;
    $("manual-dlg").hidden = false;
    $("manual-order").focus();
  });
  $("manual-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const order = $("manual-order").value.trim().replace(/^#/, "");
    if (!order) return;
    closeAll("manual-dlg");
    openOrder($("manual-plat").value, order);
  });

  function gallery(items, picks, max, onChange) {
    const g = h("div", { class: "gallery" });
    items.forEach((it) => {
      const box = h("input", { type: "checkbox", "aria-label": "Usar como evidencia" });
      const fig = h("figure", { class: "tile" + (it.sensitive ? " sensitive" : "") },
        it.content_type && !String(it.content_type).startsWith("image/")
          ? h("a", { class: "file", href: it.url, target: "_blank", rel: "noopener", text: "Archivo" })
          : h("a", { href: it.url, target: "_blank", rel: "noopener" }, h("img", { src: it.url, alt: it.alt || "Foto del pedido", loading: "lazy" })),
        h("label", { class: "pick" }, box),
        h("figcaption", {}, h("span", { class: "muted", text: it.caption || "" }), h("a", { href: it.url, download: "", text: "Descargar" })));
      box.addEventListener("change", () => {
        if (box.checked && picks.size >= max) {
          box.checked = false;
          window.alert("Puede elegir como máximo " + max + " archivo(s).");
          return;
        }
        if (box.checked) picks.add(it.key); else picks.delete(it.key);
        fig.classList.toggle("picked", box.checked);
        onChange();
      });
      g.appendChild(fig);
    });
    return g;
  }

  async function openOrder(plat, order) {
    const sheet = $("sheet");
    const body = $("sheet-body");
    $("sheet-title").textContent = "Pedido " + order;
    $("sheet-sub").textContent = PLAT_LABEL[plat] + " · buscando fotos…";
    body.textContent = "";
    body.appendChild(h("p", { class: "state", text: "Buscando el pedido y sus fotos en la base de la app…" }));
    sheet.hidden = false;
    document.body.classList.add("no-scroll");
    let v;
    try {
      v = await api("/api/panel/order/" + plat + "/" + encodeURIComponent(order));
    } catch (e) {
      body.textContent = "";
      body.appendChild(h("p", { class: "state err", text: e.message }));
      return;
    }
    renderOrder(v);
  }

  function renderOrder(v) {
    const body = $("sheet-body");
    const plat = v.platform;
    const row = v.row || {};
    const rec = v.record || null;
    const state = row.state || (rec && ["abierta", "ganada", "perdida"].includes(rec.state) ? rec.state : "pendiente");
    $("sheet-title").textContent = "Pedido " + v.order_id;
    $("sheet-sub").textContent = PLAT_LABEL[plat] + (row.store_name ? " · " + row.store_name : "");
    body.textContent = "";

    const kv = h("dl", { class: "kv" },
      h("dt", { text: "Estado" }), h("dd", {}, badge(state), rec && rec.state === "preparada" ? [" ", badge("preparada")] : null),
      h("dt", { text: "Tienda" }), h("dd", { text: row.store_name || "—" }),
      h("dt", { text: "Fecha" }), h("dd", { text: when(row.ordered_at) }),
      h("dt", { text: "Problema" }), h("dd", { text: issueText(row.issue) }),
      h("dt", { text: "Monto" }), h("dd", { text: row.amount_clp !== null && row.amount_clp !== undefined ? clp(row.amount_clp) : (row.amount_display || "—") }));
    if (rec && rec.updated_at) kv.append(h("dt", { text: "Último movimiento" }), h("dd", { text: (STATE_LABEL[rec.state] || rec.state) + " · " + when(rec.updated_at) }));
    body.appendChild(h("div", { class: "block" }, h("h3", { text: "Resumen" }), kv,
      v.row ? null : h("p", { class: "muted small", text: plat === "uber"
        ? "Este pedido no está en los cobros de Uber guardados."
        : "Este pedido no está en el listado de PedidosYa; puede armar igual el reclamo con las fotos de la app." })));

    const max = (v.submit && v.submit.max_evidence) || 3;
    const picks = new Set();
    const counter = h("span", { class: "muted small" });
    const updateCounter = () => { counter.textContent = picks.size + " de " + max + " archivo(s) elegidos"; };
    updateCounter();

    const ev = v.app_evidence || {};
    const appBlock = h("div", { class: "block" }, h("h3", { text: "Fotos de la tienda (app delivery)" }));
    if (ev.status === "not_configured") {
      appBlock.append(h("p", { class: "state warn", text: "Falta la clave de la base de fotos de la app. " }),
        h("a", { href: "#credenciales", onclick: () => closeAll("sheet"), text: "Cargarla en Credenciales" }));
    } else if (ev.status !== "ok") {
      appBlock.append(h("p", { class: "state err", text: ev.error || "No se pudo consultar la base de fotos." }));
    } else if (!(ev.images || []).length) {
      appBlock.append(h("p", { class: "muted", text: "La base de la app no tiene fotos para este pedido." }));
    } else {
      appBlock.append(h("p", { class: "muted small", text: ev.images.length + " foto(s) encontradas. Marque las que quiere adjuntar." }),
        gallery(ev.images.map((i) => ({ ...i, key: "app:" + i.id, caption: "Tomada " + when(i.created_at) })), picks, max, updateCounter));
    }
    body.appendChild(appBlock);

    const platBlock = h("div", { class: "block" }, h("h3", { text: "Fotos de " + PLAT_LABEL[plat] }));
    const pm = v.platform_media || [];
    if (pm.length) {
      platBlock.appendChild(gallery(pm.map((m) => ({ ...m, key: "plat:" + m.id, caption: m.group === "tienda" ? "Evidencia de la tienda" : "Foto del cliente" })), picks, max, updateCounter));
    } else {
      platBlock.appendChild(h("p", { class: "muted small", text: "Aún no se trajeron fotos de la plataforma para este pedido." }));
    }
    const canFetch = plat === "uber" || row.store_id;
    if (canFetch) {
      platBlock.appendChild(h("div", { class: "dp-actions" }, h("button", { type: "button", class: "ghost", text: "Traer fotos de " + PLAT_LABEL[plat], onclick: async (e) => {
        const done = busy(e.currentTarget, "Trayendo…");
        try {
          const url = plat === "uber"
            ? "/api/disputes/uber/" + encodeURIComponent(v.order_id) + "?refresh=true"
            : "/api/orders/pedidosya/" + encodeURIComponent(v.order_id) + "?store_id=" + encodeURIComponent(row.store_id) + "&photos=true";
          const r = await api(url);
          const f = r.platform_fetch || {};
          if (f.status && !["ok", "cached"].includes(f.status)) window.alert(f.error || "La plataforma no devolvió fotos.");
          renderOrder(await api("/api/panel/order/" + plat + "/" + encodeURIComponent(v.order_id)));
        } catch (err) {
          window.alert(err.message);
        } finally {
          done();
        }
      } })));
    }
    body.appendChild(platBlock);

    const reasons = v.reasons || {};
    const reason = h("select", {}, Object.entries(reasons).map(([k, t]) => h("option", { value: k, text: t })));
    if (rec && rec.reason && reasons[rec.reason]) reason.value = rec.reason;
    const desc = h("textarea", { rows: "3", maxlength: "2000", placeholder: "Qué pasó y por qué la tienda no es responsable" });
    if (rec && rec.description) desc.value = rec.description;
    const out = h("div");
    const build = h("button", { type: "button", text: "Armar request de disputa" });
    const sub = v.submit || {};
    const form = h("div", { class: "block dispute-form" },
      h("h3", { text: "Armar la disputa" }),
      sub.can_prepare === false ? h("p", { class: "state warn", text: sub.missing_note }) : null,
      h("label", {}, "Motivo", reason),
      h("label", {}, "Descripción", desc),
      counter,
      h("div", { class: "dp-actions" }, build),
      out);
    if (sub.can_prepare === false) build.disabled = true;
    build.addEventListener("click", async () => {
      const app = [...picks].filter((k) => k.startsWith("app:")).map((k) => k.slice(4));
      const media = [...picks].filter((k) => k.startsWith("plat:")).map((k) => k.slice(5));
      const done = busy(build, "Armando…");
      out.textContent = "";
      try {
        const r = await api("/api/panel/request/" + plat + "/" + encodeURIComponent(v.order_id), {
          json: { reason: reason.value, description: desc.value.trim(), app_evidence_ids: app, evidence_ids: media, confirm: false },
        });
        renderRequest(out, v, r, { reason: reason.value, description: desc.value.trim(), app_evidence_ids: app, evidence_ids: media });
        loadStats();
        loadList();
      } catch (e) {
        out.appendChild(h("p", { class: "state err", text: e.message }));
      } finally {
        done();
      }
    });
    body.appendChild(form);

    if (plat === "pedidosya" && rec && ["abierta", "ganada", "perdida"].includes(rec.state)) {
      body.appendChild(resultBlock(v, rec));
    } else if (plat === "uber" && state !== "pendiente") {
      body.appendChild(h("div", { class: "block" }, h("h3", { text: "Resultado" }),
        h("p", { class: "muted", text: "En Uber el estado (abierta, ganada o perdida) lo informa Uber. Pulse «Actualizar» para traer el último." })));
    }
  }

  function resultBlock(v, rec) {
    const box = h("div", { class: "block" }, h("h3", { text: "Resultado del reclamo" }),
      h("p", { class: "muted small", text: "Estado actual: " + (STATE_LABEL[rec.state] || rec.state) + ". Márquelo cuando PedidosYa responda." }));
    const actions = h("div", { class: "dp-actions" });
    [["ganada", "Marcar ganada", ""], ["perdida", "Marcar perdida", "ghost danger"], ["abierta", "Volver a abierta", "ghost"]].forEach(([s, label, cls]) => {
      if (s === rec.state) return;
      actions.appendChild(h("button", { type: "button", class: cls, text: label, onclick: () => mark(v, s) }));
    });
    box.appendChild(actions);
    return box;
  }

  async function mark(v, state) {
    try {
      await api("/api/panel/record/" + v.platform + "/" + encodeURIComponent(v.order_id), { json: { state } });
      loadStats();
      loadList();
      renderOrder(await api("/api/panel/order/" + v.platform + "/" + encodeURIComponent(v.order_id)));
    } catch (e) {
      window.alert(e.message);
    }
  }

  function renderRequest(out, v, r, body) {
    out.textContent = "";
    if (v.platform === "uber") {
      const res = ((r.result || {}).results || [])[0] || {};
      const problems = res.problems || [];
      const elig = res.eligibility || {};
      const flow = { DISPUTE_WITH_EVIDENCE_OPTIONAL: "evidencia opcional", DISPUTE_WITH_EVIDENCE_REQUIRED: "evidencia obligatoria" }[elig.disputeFlow] || elig.disputeFlow;
      const eligText = !res.eligibility ? "—" : (elig.disputeEligibility === "ELIGIBLE" ? "Elegible" : (elig.disputeEligibility || "Sin dato")) + (flow ? " · " + flow : "");
      out.appendChild(h("div", {},
        h("p", { class: "state ok", text: "Request armado (dry-run): no se envió nada a Uber." }),
        h("dl", { class: "kv" },
          h("dt", { text: "Elegibilidad" }), h("dd", { text: eligText }),
          h("dt", { text: "Evidencia" }), h("dd", { text: (res.evidence_files || []).length + " archivo(s)" })),
        problems.length ? h("div", {}, h("p", { class: "state warn", text: "Uber podría rechazarlo:" }), h("ul", { class: "problems" }, problems.map((p) => h("li", { text: String(p) })))) : null,
        h("details", {}, h("summary", { text: "Ver request completo" }), h("pre", { class: "dp-request", text: JSON.stringify(res.payload || res, null, 2) }))));
      const send = h("button", { type: "button", class: "danger", text: "Enviar disputa a Uber" });
      if (!(v.submit || {}).real_submit_enabled) {
        send.disabled = true;
        out.append(h("div", { class: "dp-actions" }, send),
          h("p", { class: "muted small", text: "El envío real está apagado en el servidor hasta una prueba autorizada (ALLOW_UBER_DISPUTE_SUBMIT). El request queda guardado como «Request armado»." }));
      } else {
        send.addEventListener("click", async () => {
          if (!window.confirm("Se enviará la disputa del pedido " + v.order_id + " a Uber. ¿Continuar?")) return;
          const done = busy(send, "Enviando…");
          try {
            const rr = await api("/api/panel/request/uber/" + encodeURIComponent(v.order_id), { json: { ...body, confirm: true } });
            out.append(h("p", { class: "state ok", text: "Enviada. " + ((rr.result || {}).note || "") }));
            loadStats();
            loadList();
          } catch (e) {
            out.append(h("p", { class: "state err", text: e.message }));
          } finally {
            done();
          }
        });
        out.append(h("div", { class: "dp-actions" }, send), h("p", { class: "muted small", text: (v.submit || {}).note || "" }));
      }
      return;
    }
    const pkg = r.request || {};
    const text = h("pre", { class: "dp-request", text: pkg.texto_para_portal || "" });
    const copy = h("button", { type: "button", class: "ghost", text: "Copiar texto", onclick: async () => {
      try { await navigator.clipboard.writeText(pkg.texto_para_portal || ""); copy.textContent = "Copiado"; } catch (e) { window.getSelection().selectAllChildren(text); }
    } });
    out.append(
      h("p", { class: "state ok", text: "Request armado. PedidosYa no recibe disputas por API: envíelo desde el Portal de Socios." }),
      text,
      (pkg.evidencia || []).length ? h("ul", { class: "items" }, pkg.evidencia.map((e, i) => h("li", {}, h("a", { href: e.url, download: "", text: "Foto " + (i + 1) }), " · " + e.origen))) : h("p", { class: "muted small", text: "Sin fotos adjuntas." }),
      h("p", { class: "muted small", text: pkg.como_enviar || "" }),
      h("div", { class: "dp-actions" }, copy, h("button", { type: "button", text: "Marcar como enviada", onclick: () => mark(v, "abierta") })));
  }

  // ---------- credenciales ----------
  const CRED_STATUS = { configured: "Vigente", missing: "Sin cargar", expired: "Caducada", unknown: "Sin confirmar", pending: "Pendiente" };
  const CRED_HELP = {
    uber: "Pegue el header Cookie de Uber Eats Manager (una línea) o suba el archivo.",
    pedidosya: "Pegue el contenido de pya_tokens.json o suba el archivo.",
    evidencia: "Clave de la API de evidencia de la app delivery (tabla evidencia_clave).",
  };

  async function loadCreds(check) {
    setState($("cred-state"), check ? "Verificando con cada plataforma…" : "Cargando…");
    try {
      const d = await api("/api/credentials/status" + (check ? "?check=true" : ""));
      const box = $("creds");
      box.textContent = "";
      d.sources.forEach((s) => box.appendChild(credCard(s)));
      setState($("cred-state"), "");
    } catch (e) {
      setState($("cred-state"), e.message, "err");
    }
  }

  function credCard(s) {
    const card = h("article", { class: "card" },
      h("div", { class: "cred-head" }, h("span", { class: "light light-" + s.status }), h("h3", { text: s.label })),
      h("p", { class: "status status-" + s.status, text: CRED_STATUS[s.status] || s.status }),
      h("p", { class: "muted small", text: s.detail || "" }),
      s.checked_at ? h("p", { class: "muted small", text: "Revisado " + when(s.checked_at) }) : null);
    if (!CRED_HELP[s.source]) return card;
    const ta = h("textarea", { rows: "3", autocomplete: "off", spellcheck: "false", placeholder: CRED_HELP[s.source] });
    const file = h("input", { type: "file", accept: s.source === "pedidosya" ? ".json,application/json,text/plain" : ".txt,text/plain" });
    const msg = h("p", { class: "state" });
    const save = h("button", { type: "submit", text: s.file_present ? "Probar y reemplazar" : "Probar y guardar" });
    const form = h("form", {}, ta, s.source === "evidencia" ? null : file, save, msg);
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const fd = new FormData();
      if (file.files && file.files[0]) fd.append("file", file.files[0]);
      else if (ta.value.trim()) fd.append("value", ta.value.trim());
      else { setState(msg, "Pegue el valor o elija un archivo.", "warn"); return; }
      const done = busy(save, "Probando…");
      try {
        const r = await api("/api/credentials/" + s.source, { method: "PUT", body: fd });
        ta.value = "";
        file.value = "";
        setState(msg, r.detail || "Guardada.", "ok");
        setTimeout(() => loadCreds(false), 900);
      } catch (e) {
        setState(msg, e.message, "err");
      } finally {
        done();
      }
    });
    card.appendChild(form);
    return card;
  }
  $("cred-check").addEventListener("click", () => loadCreds(true));

  // ---------- inicio ----------
  (async () => {
    try { st.meta = await api("/api/panel/meta"); } catch (e) { st.meta = null; }
    route();
  })();
})();
