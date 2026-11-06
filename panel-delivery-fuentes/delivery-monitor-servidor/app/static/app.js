(() => {
  const PAGE = 40;
  const state = {
    payload: null,
    plat: "todas",
    brand: "todas",
    view: "todas",
    hideEx: true,
    q: "",
    storePage: 0,
    dispPage: 0,
  };

  const $ = (id) => document.getElementById(id);

  function clp(n) {
    if (n === null || n === undefined || n === "") return "—";
    const num = Number(n);
    if (Number.isNaN(num)) return String(n);
    return "$" + Math.round(num).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  }

  function fmt(n) {
    if (n === null || n === undefined) return "—";
    return Number(n).toString();
  }

  function statusLabel(code, labels) {
    return (labels && labels[code]) || code || "—";
  }

  function statusClass(status) {
    if (status === "ok") return "status-ok";
    if (status === "error") return "status-error";
    if (status === "pending" || status === "no_direct_list") return "status-pending";
    return "";
  }

  function platformName(p) {
    if (p === "uber") return "Uber";
    if (p === "pedidosya") return "PedidosYa";
    if (p === "rappi") return "Rappi";
    return p || "—";
  }

  async function fetchJSON(url, options) {
    const res = await fetch(url, { credentials: "same-origin", ...options });
    if (res.status === 401) {
      window.location.href = "/login";
      throw new Error("No autenticado");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || "Error de red");
    }
    return data;
  }

  function showBanner(text, kind) {
    const el = $("banner");
    if (!text) {
      el.hidden = true;
      el.className = "banner hidden";
      el.textContent = "";
      return;
    }
    el.hidden = false;
    el.className = "banner " + (kind || "info");
    el.textContent = text;
  }

  function setSubtitle(payload) {
    const el = $("subtitle");
    if (!payload.available) {
      el.textContent = payload.message || "Sin snapshot todavía.";
      return;
    }
    el.textContent = "Snapshot del " + (payload.generated_at || "—") + " (" + (payload.timezone || "America/Santiago") + "). Los filtros no consultan las plataformas.";
  }

  function renderSources(payload) {
    const box = $("sources");
    box.innerHTML = "";
    const sources = payload.sources || {};
    const names = ["uber", "pedidosya", "rappi"];
    names.forEach((name) => {
      const src = sources[name] || { status: "pending", error: "sin datos de esta fuente" };
      const card = document.createElement("article");
      card.className = "card";
      const stores = src.stores_count == null ? "—" : String(src.stores_count);
      let disp = "—";
      if (name === "pedidosya") disp = src.disputes_status === "no_direct_list" ? "sin listado directo" : (src.disputes_count == null ? "—" : String(src.disputes_count));
      else if (src.disputes_count != null) disp = String(src.disputes_count);
      else if (src.disputes_status) disp = String(src.disputes_status);
      const err = src.error ? src.error : "";
      card.innerHTML =
        "<h3>" + platformName(name) + "</h3>" +
        '<p class="status ' + statusClass(src.status) + '">' + (src.status || "pending") + "</p>" +
        "<p>Tiendas: " + stores + "</p>" +
        "<p>Disputas: " + disp + "</p>" +
        "<p>Hora (Chile): " + (src.fetched_at || "—") + "</p>" +
        (err ? "<p class='muted'>" + err + "</p>" : "");
      box.appendChild(card);
    });
  }

  function matchStore(store) {
    if (state.plat !== "todas" && store.platform !== state.plat) return false;
    if (state.brand !== "todas" && store.brand !== state.brand) return false;
    if (state.hideEx && store.excluded && !store.open_now) return false;
    if (state.view === "abiertas" && !store.open_now) return false;
    if (state.view === "atencion" && store.status === "abierta") return false;
    if (state.q) {
      const q = state.q.toLowerCase();
      const blob = ((store.name || "") + " " + (store.reason || "")).toLowerCase();
      if (!blob.includes(q)) return false;
    }
    return true;
  }

  function matchDisp(row) {
    if (state.plat === "pedidosya") return false;
    if (state.plat !== "todas" && row.platform !== state.plat) return false;
    if (state.brand !== "todas" && row.brand !== state.brand) return false;
    if (state.q) {
      const q = state.q.toLowerCase();
      const blob = ((row.store_name || "") + " " + (row.order_id || "")).toLowerCase();
      if (!blob.includes(q)) return false;
    }
    return true;
  }

  function filteredStores(payload) {
    return (payload.stores || []).filter(matchStore);
  }

  function filteredDisputes(payload) {
    if (state.plat === "pedidosya") return [];
    return (payload.disputes || []).filter(matchDisp);
  }

  function pageSlice(rows, page) {
    const start = page * PAGE;
    return { rows: rows.slice(start, start + PAGE), start, total: rows.length, pages: Math.max(1, Math.ceil(rows.length / PAGE)) };
  }

  function renderPager(el, page, pages, onChange) {
    el.innerHTML = "";
    if (pages <= 1) return;
    const prev = document.createElement("button");
    prev.textContent = "Anterior";
    prev.disabled = page <= 0;
    prev.className = "ghost";
    prev.onclick = () => onChange(page - 1);
    const info = document.createElement("span");
    info.textContent = (page + 1) + " / " + pages;
    const next = document.createElement("button");
    next.textContent = "Siguiente";
    next.disabled = page >= pages - 1;
    next.className = "ghost";
    next.onclick = () => onChange(page + 1);
    el.append(prev, info, next);
  }

  function renderMetrics(payload) {
    const box = $("metrics");
    box.innerHTML = "";
    if (!payload.available) {
      const p = document.createElement("p");
      p.className = "muted";
      p.textContent = payload.message || "Sin cifras: falta un snapshot.";
      box.appendChild(p);
      return;
    }
    const stores = filteredStores(payload);
    const openNow = stores.filter((s) => s.open_now).length;
    const hd = stores.filter((s) => s.status === "abierta_alta_demanda").length;
    const closed = stores.length - openNow;
    const disps = filteredDisputes(payload);
    const amount = disps.reduce((acc, d) => acc + (Number(d.amount_clp) || 0), 0);
    const items = [
      { value: String(openNow), label: "Abiertas ahora", detail: stores.length + " en este recorte" },
      { value: String(hd), label: "En alta demanda", detail: "Incluidas en las abiertas" },
      { value: String(closed), label: "No abiertas", detail: state.hideEx ? "Fuera de la lista de exclusión" : "Incluye exclusiones" },
      { value: state.plat === "pedidosya" ? "—" : String(disps.length), label: "Disputas Uber sin abrir", detail: state.plat === "pedidosya" ? "PedidosYa no lista disputas" : clp(amount) },
    ];
    items.forEach((item) => {
      const div = document.createElement("div");
      div.className = "metric";
      div.innerHTML = "<strong>" + item.value + "</strong><span>" + item.label + "</span><p class='muted'>" + item.detail + "</p>";
      box.appendChild(div);
    });
  }

  function fillTable(table, headers, rows, emptyText) {
    table.innerHTML = "";
    table.classList.add("stack");
    const thead = document.createElement("thead");
    const tr = document.createElement("tr");
    headers.forEach((h) => {
      const th = document.createElement("th");
      th.textContent = h;
      tr.appendChild(th);
    });
    thead.appendChild(tr);
    table.appendChild(thead);
    const tb = document.createElement("tbody");
    if (!rows.length) {
      const r = document.createElement("tr");
      r.className = "empty";
      const td = document.createElement("td");
      td.colSpan = headers.length;
      td.className = "muted";
      td.textContent = emptyText;
      r.appendChild(td);
      tb.appendChild(r);
    } else {
      rows.forEach((cols) => {
        const r = document.createElement("tr");
        cols.forEach((c, i) => {
          const td = document.createElement("td");
          if (headers[i]) td.setAttribute("data-label", headers[i]);
          if (c && typeof c === "object") {
            td.textContent = c.text;
            if (c.cls) td.className = c.cls;
          } else {
            td.textContent = c == null ? "" : String(c);
          }
          r.appendChild(td);
        });
        tb.appendChild(r);
      });
    }
    table.appendChild(tb);
  }

  function renderStores(payload) {
    const labels = payload.status_labels || {};
    const all = filteredStores(payload);
    $("stores-caption").textContent = payload.available
      ? ("Mostrando " + all.length + " locales de este recorte, incluidas las abiertas.")
      : "No hay listado todavía: falta un snapshot o la fuente no está configurada.";
    const slice = pageSlice(all, state.storePage);
    if (state.storePage > slice.pages - 1) state.storePage = 0;
    const rows = slice.rows.map((s) => [
      s.name,
      platformName(s.platform),
      s.brand,
      { text: statusLabel(s.status, labels), cls: s.open_now ? "status-ok" : "status-warning" },
      s.enabled ? "Habilitada" : "No habilitada",
      s.open_now ? "Sí" : "No",
      [s.reason, s.until, s.excluded ? "exclusión" : ""].filter(Boolean).join(" · "),
    ]);
    fillTable(
      $("stores-table"),
      ["Tienda", "Plataforma", "Marca", "Estado", "Habilitación", "Abierta ahora", "Detalle"],
      rows,
      payload.available ? "Ningún local coincide con el filtro." : "Fuente pendiente de configuración."
    );
    renderPager($("stores-pager"), state.storePage, slice.pages, (p) => { state.storePage = p; render(); });
  }

  function renderDisputes(payload) {
    const caption = $("disp-caption");
    const facts = $("disp-facts");
    facts.innerHTML = "";
    if (state.plat === "pedidosya") {
      caption.textContent = "PedidosYa no tiene un listado de disputas. Los mosaicos de abajo son reclamos, no disputas pendientes.";
      fillTable($("disp-table"), ["Tienda", "Pedido", "Fecha", "Importe", "Incidencia", "Estado"], [], "Sin listado directo de disputas en PedidosYa.");
      $("disp-pager").innerHTML = "";
    } else if (!payload.available) {
      caption.textContent = "Sin cobros listados: falta un snapshot o la sesión de Uber.";
      fillTable($("disp-table"), ["Tienda", "Marca", "Pedido", "Fecha", "Importe", "Incidencia", "Etiqueta", "Estado"], [], "Fuente pendiente de configuración.");
      $("disp-pager").innerHTML = "";
    } else {
      const rows = filteredDisputes(payload);
      const amount = rows.reduce((acc, d) => acc + (Number(d.amount_clp) || 0), 0);
      const window = rows[0] ? ((rows[0].window_start || "") + " – " + (rows[0].window_end || "")) : "";
      caption.textContent = "Uber: cobros pendientes sin disputa enviada. " + (window ? ("Ventana " + window + ". ") : "") + rows.length + " en este recorte, " + clp(amount) + ".";
      const slice = pageSlice(rows, state.dispPage);
      if (state.dispPage > slice.pages - 1) state.dispPage = 0;
      fillTable(
        $("disp-table"),
        ["Tienda", "Marca", "Pedido", "Fecha", "Importe", "Incidencia", "Etiqueta", "Estado"],
        slice.rows.map((d) => [d.store_name, d.brand, d.order_id, d.ordered_at, { text: d.amount_display || clp(d.amount_clp), cls: "num" }, d.issue, d.tag, d.state]),
        "Ningún cobro coincide con el filtro."
      );
      renderPager($("disp-pager"), state.dispPage, slice.pages, (p) => { state.dispPage = p; render(); });
      [["Ventana", window || "—"], ["Cobros", String(rows.length)], ["Importe", clp(amount)]].forEach((pair) => {
        const div = document.createElement("div");
        div.className = "fact";
        div.innerHTML = "<strong>" + pair[1] + "</strong><span>" + pair[0] + "</span>";
        facts.appendChild(div);
      });
    }

    const tiles = payload.complaint_tiles || [];
    fillTable(
      $("tiles-table"),
      ["Tienda / agregado", "Tipo", "Pedidos", "Monto", "Qué es"],
      tiles.map((t) => [t.store, t.type, fmt(t.orders), t.amount == null ? "—" : String(t.amount), t.note]),
      payload.available ? "No hay mosaicos de reclamo en este snapshot (o la lectura de issues falló)." : "Fuente pendiente de configuración."
    );
  }

  function renderCoverage(payload) {
    const box = $("coverage");
    const cov = payload.coverage || {};
    box.innerHTML = ["snapshot", "uber_disputas", "pedidosya_disputas", "rappi", "sesiones"].map((key) => {
      if (!cov[key]) return "";
      return "<p>" + cov[key] + "</p>";
    }).join("");
  }

  function fillBrandOptions(payload) {
    const sel = $("flt-brand");
    const current = state.brand;
    const brands = Array.from(new Set((payload.stores || []).map((s) => s.brand).filter(Boolean))).sort();
    sel.innerHTML = "";
    ["todas", ...brands].forEach((b) => {
      const opt = document.createElement("option");
      opt.value = b;
      opt.textContent = b === "todas" ? "Todas las marcas" : b;
      sel.appendChild(opt);
    });
    if (["todas", ...brands].includes(current)) sel.value = current;
    else { sel.value = "todas"; state.brand = "todas"; }
  }

  function render() {
    const payload = state.payload;
    if (!payload) return;
    setSubtitle(payload);
    renderSources(payload);
    fillBrandOptions(payload);
    renderMetrics(payload);
    renderStores(payload);
    renderDisputes(payload);
    renderCoverage(payload);
  }

  async function load() {
    const payload = await fetchJSON("/api/snapshot");
    state.payload = payload;
    state.storePage = 0;
    state.dispPage = 0;
    if (!payload.available) showBanner(payload.message, "warn");
    else showBanner("");
    render();
  }

  $("flt-plat").addEventListener("change", (e) => { state.plat = e.target.value; state.storePage = 0; state.dispPage = 0; render(); });
  $("flt-brand").addEventListener("change", (e) => { state.brand = e.target.value; state.storePage = 0; state.dispPage = 0; render(); });
  $("flt-view").addEventListener("change", (e) => { state.view = e.target.value; state.storePage = 0; render(); });
  $("flt-hideex").addEventListener("change", (e) => { state.hideEx = e.target.checked; state.storePage = 0; render(); });
  $("flt-q").addEventListener("input", (e) => { state.q = e.target.value.trim(); state.storePage = 0; state.dispPage = 0; render(); });

  $("btn-refresh").addEventListener("click", async () => {
    const btn = $("btn-refresh");
    btn.disabled = true;
    btn.textContent = "Actualizando…";
    try {
      const payload = await fetchJSON("/api/refresh", { method: "POST" });
      state.payload = payload;
      state.storePage = 0;
      state.dispPage = 0;
      if (!payload.available) showBanner(payload.message || "El refresh no dejó un snapshot usable.", "warn");
      else showBanner("Snapshot actualizado: " + (payload.generated_at || ""), "info");
      render();
    } catch (err) {
      showBanner(err.message || "No se pudo actualizar.", "err");
    } finally {
      btn.disabled = false;
      btn.textContent = "Actualizar snapshot";
    }
  });

  load().catch((err) => showBanner(err.message, "err"));
})();
