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

  function table(el, headers, rows, empty) {
    el.textContent = "";
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

  function lines(value) {
    return String(value || "").split("\n").map((s) => s.trim()).filter(Boolean);
  }

  function cell(value) {
    if (value === null || value === undefined) return "—";
    if (typeof value === "boolean") return value ? "Sí" : "No";
    if (typeof value === "object") return JSON.stringify(value);
    return String(when(value));
  }

  function showResult(pre, data) {
    const parts = [];
    parts.push(data.dry_run ? "DRY-RUN: no se envió nada a la plataforma." : "ENVIADO a la plataforma.");
    if (data.note) parts.push(data.note);
    if (Array.isArray(data.results)) {
      parts.push(data.results.length + " fila(s):");
      parts.push(JSON.stringify(data.results.slice(0, 50), null, 2));
      if (data.results.length > 50) parts.push("… " + (data.results.length - 50) + " más");
    } else if (data.results && typeof data.results === "object") {
      parts.push(JSON.stringify(data.results, null, 2));
    }
    if (data.output) parts.push(data.output);
    if (data.log) parts.push("— log —\n" + data.log);
    pre.textContent = parts.join("\n");
  }

  function confirmLive(summary) {
    return window.confirm(summary + "\n\nEsto se ejecuta EN VIVO en la plataforma. ¿Revisó el dry-run y desea continuar?");
  }

  // ---------- tiendas ----------
  const st = { rows: [], selected: new Set(), options: null };

  function stKey(r) { return r.platform + ":" + r.store_id; }

  function renderStores() {
    const q = $("st-q").value.trim().toLowerCase();
    const rows = st.rows.filter((r) => !q || (r.name || "").toLowerCase().includes(q));
    table($("st-table"), ["", "Tienda", "Marca", "Estado", "Abierta ahora", "Motivo", "Hasta", "Excluida"], rows.map((r) => {
      const key = stKey(r);
      const box = h("input", { type: "checkbox", "aria-label": "Seleccionar " + (r.name || r.store_id) });
      box.checked = st.selected.has(key);
      box.addEventListener("change", () => { if (box.checked) st.selected.add(key); else st.selected.delete(key); });
      return h("tr", {},
        h("td", {}, box),
        h("td", { text: r.name || r.store_id }),
        h("td", { text: r.brand || "—" }),
        h("td", { text: r.status || "—" }),
        h("td", { text: cell(r.open_now) }),
        h("td", { text: r.reason || "—" }),
        h("td", { text: cell(r.until) }),
        h("td", { text: cell(r.excluded) }));
    }), "Sin tiendas para este filtro.");
    $("st-sel-all").checked = rows.length > 0 && rows.every((r) => st.selected.has(stKey(r)));
    return rows;
  }

  function fillReasons() {
    const plat = $("st-plat").value;
    const reasons = (st.options && st.options[plat] && st.options[plat].reasons) || [];
    const sel = $("st-reason");
    sel.textContent = "";
    reasons.forEach((r) => sel.appendChild(h("option", { value: r, text: r })));
    $("st-uber-dur-wrap").hidden = plat !== "uber";
    $("st-pya-min-wrap").hidden = plat !== "pedidosya";
  }

  async function loadStores() {
    const plat = $("st-plat").value;
    setState($("st-state"), "Cargando tiendas…");
    try {
      const data = await api("/api/stores?platform=" + encodeURIComponent(plat));
      st.rows = data.stores || [];
      st.selected = new Set([...st.selected].filter((k) => k.startsWith(plat + ":")));
      renderStores();
      setState($("st-state"), data.note || (data.count + " tienda(s) en el snapshot."), data.note ? "warn" : "");
    } catch (e) {
      setState($("st-state"), e.message, "bad");
    }
  }

  function storeBody(confirm) {
    const plat = $("st-plat").value;
    const ids = [...st.selected].filter((k) => k.startsWith(plat + ":")).map((k) => k.slice(plat.length + 1));
    return { platform: plat, store_ids: ids, names: lines($("st-names").value), confirm };
  }

  async function storeAction(action, confirm, btn) {
    const body = storeBody(confirm);
    if (!body.store_ids.length && !body.names.length) {
      setState($("st-state"), "Seleccione al menos una tienda o escriba un nombre.", "warn");
      return;
    }
    if (action === "pause") {
      body.reason = $("st-reason").value;
      if (body.platform === "uber") body.duration = $("st-duration").value;
      else if ($("st-minutes").value) body.minutes = Number($("st-minutes").value);
    }
    const count = body.store_ids.length + body.names.length;
    if (confirm && !confirmLive((action === "pause" ? "Pausar " : "Prender ") + count + " tienda(s) en " + body.platform + ".")) return;
    const done = busy(btn, confirm ? "Enviando…" : "Simulando…");
    $("st-result").textContent = "";
    try {
      const data = await api("/api/stores/" + action, { json: body });
      showResult($("st-result"), data);
      setState($("st-state"), data.dry_run ? "Dry-run listo: revise el resultado antes de confirmar." : "Enviado. Actualice el snapshot para ver el estado final.", data.dry_run ? "" : "good");
    } catch (e) {
      setState($("st-state"), e.message, "bad");
    } finally {
      done();
    }
  }

  async function initStores() {
    $("st-plat").addEventListener("change", () => { fillReasons(); loadStores(); });
    $("st-q").addEventListener("input", renderStores);
    $("st-reload").addEventListener("click", loadStores);
    $("st-sel-all").addEventListener("change", () => {
      const rows = renderStores();
      rows.forEach((r) => { if ($("st-sel-all").checked) st.selected.add(stKey(r)); else st.selected.delete(stKey(r)); });
      renderStores();
    });
    $("st-activate-dry").addEventListener("click", (ev) => storeAction("activate", false, ev.currentTarget));
    $("st-activate-go").addEventListener("click", (ev) => storeAction("activate", true, ev.currentTarget));
    $("st-pause-dry").addEventListener("click", (ev) => storeAction("pause", false, ev.currentTarget));
    $("st-pause-go").addEventListener("click", (ev) => storeAction("pause", true, ev.currentTarget));
    try {
      st.options = await api("/api/stores/meta/options");
    } catch (e) {
      st.options = null;
    }
    fillReasons();
    loadStores();
  }

  // ---------- catálogo ----------
  const UNTIL = {
    uber: [["today", "Hasta mañana (hoy)"], ["indefinite", "Indefinido"]],
    pedidosya: [["indefinite", "Indefinido"], ["tomorrow", "Hasta mañana"], ["60", "60 minutos"], ["240", "4 horas"]],
  };

  function fillUntil() {
    const sel = $("cat-until");
    sel.textContent = "";
    UNTIL[$("cat-plat").value].forEach(([v, t]) => sel.appendChild(h("option", { value: v, text: t })));
  }

  async function loadSoldout(btn) {
    const plat = $("cat-plat").value;
    const store = $("cat-store").value.trim();
    const done = busy(btn, "Consultando…");
    setState($("cat-state"), "Consultando agotados en la plataforma (puede tardar varios minutos)…");
    try {
      const data = await api("/api/catalog/soldout?platform=" + encodeURIComponent(plat) + (store ? "&store=" + encodeURIComponent(store) : ""));
      const items = data.items || [];
      const keys = items.length ? Object.keys(items[0]).slice(0, 7) : ["Resultado"];
      table($("cat-table"), keys, items.map((r) => h("tr", {}, keys.map((k) => h("td", { text: cell(r[k]) })))), "Sin productos agotados.");
      setState($("cat-state"), data.count + " producto(s) agotado(s).", data.count ? "warn" : "good");
    } catch (e) {
      setState($("cat-state"), e.message, "bad");
    } finally {
      done();
    }
  }

  async function itemAction(mode, confirm, btn) {
    const item = $("cat-item").value.trim();
    if (!item) {
      setState($("cat-state"), "Escriba el producto.", "warn");
      $("cat-item").focus();
      return;
    }
    const names = lines($("cat-names").value);
    const body = { platform: $("cat-plat").value, item, names, confirm };
    if ($("cat-contains").checked) body.match = "contains";
    if (mode === "soldout") body.until = $("cat-until").value;
    const scope = names.length ? names.length + " tienda(s)" : "TODAS las tiendas";
    if (confirm && !confirmLive((mode === "soldout" ? "Agotar" : "Reponer") + " «" + item + "» en " + scope + " de " + body.platform + ".")) return;
    await runCatalog("/api/catalog/" + mode, body, btn, confirm);
  }

  async function menuAction(confirm, btn) {
    const names = lines($("cat-names").value);
    const body = { platform: $("cat-plat").value, names, extra_excludes: lines($("cat-excludes").value), confirm };
    const scope = names.length ? names.length + " tienda(s)" : "TODAS las tiendas";
    if (confirm && !confirmLive("Activar el menú completo (con exclusiones del CLI) en " + scope + " de " + body.platform + ".")) return;
    await runCatalog("/api/catalog/activate-menu", body, btn, confirm);
  }

  async function runCatalog(url, body, btn, confirm) {
    const done = busy(btn, confirm ? "Enviando…" : "Simulando…");
    $("cat-result").textContent = "";
    setState($("cat-state"), confirm ? "Enviando a la plataforma…" : "Simulando (dry-run)…");
    try {
      const data = await api(url, { json: body });
      showResult($("cat-result"), data);
      setState($("cat-state"), data.dry_run ? "Dry-run listo: revise antes de confirmar." : "Enviado a la plataforma.", data.dry_run ? "" : "good");
    } catch (e) {
      setState($("cat-state"), e.message, "bad");
    } finally {
      done();
    }
  }

  function initCatalog() {
    fillUntil();
    $("cat-plat").addEventListener("change", fillUntil);
    $("cat-load").addEventListener("click", (ev) => loadSoldout(ev.currentTarget));
    $("cat-item-form").addEventListener("submit", (ev) => {
      ev.preventDefault();
      itemAction("soldout", false, ev.submitter || ev.currentTarget.querySelector("button[type=submit]"));
    });
    $("cat-soldout-go").addEventListener("click", (ev) => itemAction("soldout", true, ev.currentTarget));
    $("cat-instock").addEventListener("click", (ev) => itemAction("instock", false, ev.currentTarget));
    $("cat-instock-go").addEventListener("click", (ev) => itemAction("instock", true, ev.currentTarget));
    $("cat-menu").addEventListener("click", (ev) => menuAction(false, ev.currentTarget));
    $("cat-menu-go").addEventListener("click", (ev) => menuAction(true, ev.currentTarget));
  }

  // ---------- reportes ----------
  let reportCatalog = null;

  async function getReportCatalog() {
    if (!reportCatalog) reportCatalog = (await api("/api/reports")).reports || [];
    return reportCatalog;
  }

  function fillReportSelect(sel, reports) {
    sel.textContent = "";
    const groups = { both: "General", uber: "Uber", pedidosya: "PedidosYa" };
    Object.entries(groups).forEach(([plat, label]) => {
      const og = h("optgroup", { label });
      reports.filter((r) => r.platform === plat).forEach((r) => og.appendChild(h("option", { value: r.id, text: r.title })));
      if (og.children.length) sel.appendChild(og);
    });
  }

  function syncReportForm() {
    const meta = (reportCatalog || []).find((r) => r.id === $("rep-id").value);
    if (!meta) return;
    const params = meta.params || [];
    const dated = params.includes("start");
    $("rep-start").closest("label").hidden = !dated;
    $("rep-end").closest("label").hidden = !dated;
    document.querySelectorAll("#view-reportes [data-param]").forEach((el) => {
      const p = el.dataset.param;
      el.hidden = !(params.includes(p) || (p === "by_store" && meta.id === "pya_issues"));
    });
    const fmt = $("rep-fmt");
    Array.from(fmt.options).forEach((o) => { o.disabled = !meta.formats.includes(o.value); });
    if (!meta.formats.includes(fmt.value)) fmt.value = meta.formats[0];
    $("rep-desc").textContent = (meta.platform === "both" ? "Snapshot local" : meta.platform === "uber" ? "Uber" : "PedidosYa") +
      (dated ? " · sin fechas usa la ventana por defecto del CLI" : "");
  }

  async function previewJob(job) {
    const prev = $("rep-preview");
    prev.textContent = "";
    if (!job.download_url || !String(job.artifact || "").endsWith(".json")) return;
    try {
      const res = await fetch(job.download_url, { credentials: "same-origin" });
      const data = await res.json();
      const rows = Array.isArray(data) ? data : (Array.isArray(data.rows) ? data.rows : null);
      if (!rows || !rows.length || typeof rows[0] !== "object") return;
      const keys = Object.keys(rows[0]).slice(0, 8);
      table(prev, keys, rows.slice(0, 20).map((r) => h("tr", {}, keys.map((k) => h("td", { text: cell(r[k]) })))), "Sin filas.");
    } catch (e) {
      prev.textContent = "";
    }
  }

  async function runReport(btn) {
    const meta = reportCatalog.find((r) => r.id === $("rep-id").value);
    const body = { report: meta.id, format: $("rep-fmt").value };
    if ((meta.params || []).includes("start")) {
      if ($("rep-start").value) body.start = $("rep-start").value;
      if ($("rep-end").value) body.end = $("rep-end").value;
    }
    if (meta.params.includes("store") && $("rep-store").value.trim()) body.store = $("rep-store").value.trim();
    if (meta.params.includes("status") && $("rep-status").value) body.status = $("rep-status").value;
    if (meta.params.includes("days")) body.days = Number($("rep-days").value || 30);
    if (meta.id === "pya_issues" && $("rep-bystore").checked) body.by_store = true;
    const done = busy(btn, "Generando…");
    $("rep-link").textContent = "";
    $("rep-preview").textContent = "";
    setState($("rep-state"), "Consultando la plataforma (puede tardar varios minutos)…");
    try {
      const job = await api("/api/reports/run", { json: body });
      if (job.status === "done") {
        setState($("rep-state"), job.result_summary || "Reporte listo.", "good");
        $("rep-link").appendChild(h("a", { href: job.download_url, download: job.artifact || "", text: "Descargar " + (job.artifact || "archivo") }));
        previewJob(job);
      } else {
        setState($("rep-state"), job.error || ("Estado: " + job.status), "bad");
      }
    } catch (e) {
      setState($("rep-state"), e.message, "bad");
    } finally {
      done();
    }
  }

  async function initReports() {
    try {
      fillReportSelect($("rep-id"), await getReportCatalog());
      syncReportForm();
    } catch (e) {
      setState($("rep-state"), e.message, "bad");
    }
    $("rep-id").addEventListener("change", syncReportForm);
    $("rep-run").addEventListener("click", (ev) => runReport(ev.currentTarget));
  }

  // ---------- automatizaciones ----------
  const KIND_TEXT = { refresh_snapshot: "Refresh snapshot", report: "Reporte" };

  async function loadAutomations() {
    const list = $("auto-list");
    try {
      const data = await api("/api/automations");
      list.textContent = "";
      if (!(data.automations || []).length) {
        list.appendChild(h("p", { class: "muted", text: "Aún no hay automatizaciones." }));
        return;
      }
      data.automations.forEach((a) => {
        const report = a.kind === "report" && a.payload ? " · " + a.payload.report + " (" + (a.payload.format || "json") + ")" : "";
        const statusKind = a.last_status === "ok" ? "good" : a.last_status === "error" ? "bad" : a.last_status ? "warn" : "";
        list.appendChild(h("article", { class: "card" },
          h("h3", { text: a.name }),
          h("p", { class: "muted small", text: (KIND_TEXT[a.kind] || a.kind) + report }),
          h("p", { text: a.schedule ? "Cron " + a.schedule + " (hora de Chile)" : "Solo manual" }),
          h("p", { class: "small", text: a.enabled ? "Activa" : "Pausada" }),
          h("p", { class: "state " + statusKind, text: a.running ? "Corriendo…" : a.last_run_at ? "Última: " + when(a.last_run_at) + " · " + a.last_status + (a.last_error ? " · " + a.last_error : "") : "Nunca ejecutada" }),
          h("div", { class: "row" },
            h("button", { type: "button", text: "Ejecutar ahora", onclick: (ev) => runAutomation(a.id, ev.currentTarget) }),
            h("button", { type: "button", class: "ghost", text: a.enabled ? "Pausar" : "Activar", onclick: () => patchAutomation(a.id, { enabled: !a.enabled }) }),
            h("button", { type: "button", class: "ghost danger", text: "Eliminar", onclick: () => deleteAutomation(a.id, a.name) }))));
      });
    } catch (e) {
      list.textContent = "";
      list.appendChild(h("p", { class: "state bad", text: e.message }));
    }
  }

  async function runAutomation(id, btn) {
    const done = busy(btn, "Ejecutando…");
    try {
      const data = await api("/api/automations/" + id + "/run", { method: "POST" });
      setState($("auto-state"), data.summary || "Listo.", data.ok ? "good" : "warn");
    } catch (e) {
      setState($("auto-state"), e.message, "bad");
    } finally {
      done();
      loadAutomations();
    }
  }

  async function patchAutomation(id, patch) {
    try {
      await api("/api/automations/" + id, { method: "PATCH", json: patch });
    } catch (e) {
      setState($("auto-state"), e.message, "bad");
    }
    loadAutomations();
  }

  async function deleteAutomation(id, name) {
    if (!window.confirm("¿Eliminar la automatización «" + name + "»?")) return;
    try {
      await api("/api/automations/" + id, { method: "DELETE" });
    } catch (e) {
      setState($("auto-state"), e.message, "bad");
    }
    loadAutomations();
  }

  async function initAutomations() {
    const kind = $("auto-kind");
    kind.addEventListener("change", () => { $("auto-report-wrap").hidden = kind.value !== "report"; });
    try {
      fillReportSelect($("auto-report-id"), await getReportCatalog());
    } catch (e) {
      setState($("auto-state"), e.message, "bad");
    }
    $("auto-form").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const btn = ev.currentTarget.querySelector("button[type=submit]");
      const body = { name: $("auto-name").value.trim(), kind: kind.value, schedule: $("auto-cron").value.trim() };
      if (kind.value === "report") body.payload = { report: $("auto-report-id").value, format: $("auto-report-fmt").value };
      const done = busy(btn, "Guardando…");
      try {
        await api("/api/automations", { json: body });
        ev.target.reset();
        $("auto-report-wrap").hidden = true;
        setState($("auto-state"), "Automatización guardada.", "good");
        loadAutomations();
      } catch (e) {
        setState($("auto-state"), e.message, "bad");
      } finally {
        done();
      }
    });
    loadAutomations();
  }

  // ---------- agentes ----------
  async function loadAgents() {
    const list = $("ag-list");
    try {
      const data = await api("/api/agents");
      const box = $("ag-scopes");
      if (!box.querySelector("input")) {
        (data.available_scopes || []).forEach((s) => box.appendChild(h("label", { class: "check" }, h("input", { type: "checkbox", value: s }), s)));
      }
      list.textContent = "";
      if (!(data.agents || []).length) {
        list.appendChild(h("p", { class: "muted", text: "Aún no hay agentes." }));
        return;
      }
      data.agents.forEach((a) => {
        list.appendChild(h("article", { class: "card" },
          h("h3", { text: a.name }),
          h("p", { class: "muted small", text: "Clave " + (a.prefix || "") + "…" }),
          h("p", { class: "small", text: (a.scopes || []).join(", ") || "Sin scopes (no puede llamar a nada)" }),
          h("p", { class: "small muted", text: "Creado " + when(a.created_at) + (a.last_used_at ? " · último uso " + when(a.last_used_at) : " · sin uso") }),
          h("div", { class: "row" },
            h("button", { type: "button", class: "ghost danger", text: "Revocar", onclick: () => revokeAgent(a.id, a.name) }))));
      });
    } catch (e) {
      list.textContent = "";
      list.appendChild(h("p", { class: "state bad", text: e.message }));
    }
  }

  async function revokeAgent(id, name) {
    if (!window.confirm("¿Revocar la clave del agente «" + name + "»? Dejará de funcionar de inmediato.")) return;
    try {
      await api("/api/agents/" + id, { method: "DELETE" });
    } catch (e) {
      setState($("ag-created"), e.message, "bad");
    }
    loadAgents();
  }

  function initAgents() {
    $("ag-form").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const form = ev.currentTarget;
      const btn = form.querySelector("button[type=submit]");
      const scopes = Array.from($("ag-scopes").querySelectorAll("input:checked")).map((i) => i.value);
      const out = $("ag-created");
      const done = busy(btn, "Creando…");
      try {
        const data = await api("/api/agents", { json: { name: $("ag-name").value.trim(), scopes } });
        $("ag-name").value = "";
        $("ag-scopes").querySelectorAll("input").forEach((i) => { i.checked = false; });
        out.className = "state warn";
        out.textContent = "";
        out.appendChild(h("span", { text: data.note + " " }));
        out.appendChild(h("div", { class: "secret-once", text: data.api_key }));
        out.appendChild(h("button", { type: "button", class: "ghost small-btn", text: "Ocultar", onclick: () => { out.textContent = ""; } }));
        loadAgents();
      } catch (e) {
        setState(out, e.message, "bad");
      } finally {
        done();
      }
    });
    loadAgents();
  }

  window.panelExtra = { initStores, initCatalog, initReports, initAutomations, initAgents };
})();
