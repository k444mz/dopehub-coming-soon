(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const NS = "http://www.w3.org/2000/svg";
  const svgEl = (tag, attrs) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; };
  const fmtDay = (d) => new Date(d + "T12:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  const fmtWhen = (iso) => new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  const WHO = { patient: "Patient", carer: "Carer or family", professional: "Healthcare professional", curious: "Just curious", "not given": "Not given" };
  const tip = $("#tip");
  let apps = [], statuses = [];

  async function api(path, opts) {
    const r = await fetch(path, Object.assign({ credentials: "same-origin", headers: { "Content-Type": "application/json" } }, opts || {}));
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `Error ${r.status}`);
    return r.json();
  }

  function showTip(e, html) {
    tip.replaceChildren(...html);
    tip.hidden = false;
    const x = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8);
    tip.style.left = x + "px"; tip.style.top = (e.clientY - tip.offsetHeight - 12) + "px";
  }
  const hideTip = () => { tip.hidden = true; };

  /* column chart: one series, one hue, 4px rounded tops, 2px gaps, hover tooltip */
  function columns(host, data, key, unit) {
    host.replaceChildren();
    const total = data.reduce((a, d) => a + d[key], 0);
    host.appendChild(el("div", "total", `${total.toLocaleString("en-GB")} total`));
    const W = Math.max(300, host.clientWidth), H = host.clientHeight, padL = 28, padB = 22, padT = 6;
    const max = Math.max(1, ...data.map((d) => d[key]));
    const nice = max <= 4 ? max : Math.ceil(max / 4) * 4;
    const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `${unit} per day, ${total} in total over ${data.length} days` });
    const g = svgEl("g", { class: "grid" }), ax = svgEl("g", { class: "axis" });
    const ticks = nice <= 4 ? nice : 4;
    for (let i = 0; i <= ticks; i++) {
      const v = Math.round((nice / ticks) * i), y = H - padB - (v / nice) * (H - padB - padT);
      g.appendChild(svgEl("line", { x1: padL, x2: W, y1: y, y2: y }));
      const t = svgEl("text", { x: padL - 6, y: y + 4, "text-anchor": "end" }); t.textContent = v; ax.appendChild(t);
    }
    svg.append(g, ax);
    const slot = (W - padL) / data.length, bw = Math.max(2, slot - 2);
    data.forEach((d, i) => {
      const v = d[key], h = (v / nice) * (H - padB - padT), x = padL + i * slot + 1, y = H - padB - h;
      const hit = svgEl("rect", { class: "hit", x: padL + i * slot, y: padT, width: slot, height: H - padB - padT });
      let bar;
      if (v > 0) {
        const r = Math.min(4, bw / 2, h);
        bar = svgEl("path", { class: "bar", d: `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + bw - r} Q${x + bw},${y} ${x + bw},${y + r} V${y + h} Z` });
      } else bar = svgEl("rect", { class: "bar dim", x, y: H - padB - 1, width: bw, height: 1 });
      hit.addEventListener("pointermove", (e) => { bar.classList.add("hl"); showTip(e, [document.createTextNode(`${v} ${unit}`), el("small", "", fmtDay(d.d))]); });
      hit.addEventListener("pointerleave", () => { bar.classList.remove("hl"); hideTip(); });
      svg.append(hit, bar);
      if (i === 0 || i === data.length - 1 || i === Math.floor(data.length / 2)) {
        const t = svgEl("text", { x: x + bw / 2, y: H - 5, "text-anchor": i === 0 ? "start" : i === data.length - 1 ? "end" : "middle" });
        t.textContent = fmtDay(d.d); ax.appendChild(t);
      }
    });
    host.appendChild(svg);
  }

  function hbars(host, rows, emptyText) {
    host.replaceChildren();
    const max = Math.max(0, ...rows.map((r) => r.n));
    if (!rows.length || max === 0) { host.appendChild(el("p", "empty", emptyText || "Nothing yet.")); return; }
    rows.forEach((r) => {
      const row = el("div", "hrow");
      const tr = el("div", "track"), fill = el("div", "fill");
      tr.appendChild(fill);
      row.append(el("span", "k", r.label), el("span", "v", r.n.toLocaleString("en-GB")), tr);
      host.appendChild(row);
      requestAnimationFrame(() => { fill.style.width = `${(r.n / max) * 100}%`; });
    });
  }

  function alerts(s) {
    const box = $("#alerts"); box.replaceChildren();
    const add = (kind, title, text) => {
      const a = el("div", `alert ${kind}`);
      const body = el("div"); body.append(el("b", "", title), el("span", "", text));
      a.append(el("span", "ic", kind === "crit" ? "!" : "i"), body); box.appendChild(a);
    };
    if (!s.smtp_configured) add("warn", "Emails aren't being sent yet", `Add the no-reply@dopehub.net password on the server (see README). ${s.outbox.queued} email(s) are waiting and will go out once it's set.`);
    else if (s.outbox.failed) add("crit", `${s.outbox.failed} email(s) failed to send`, `Last error: ${s.outbox.last_error || "unknown"}. Run "dopehub-signups retry" on the server after fixing it.`);
    else if (s.outbox.last_error && s.outbox.queued) add("warn", "Emails are retrying", `Last error: ${s.outbox.last_error}`);
  }

  function renderApps() {
    const host = $("#apps"); host.replaceChildren();
    const fs = $("#f-status").value, fr = $("#f-role").value;
    const list = apps.filter((a) => (!fs || a.status === fs) && (!fr || a.role === fr));
    $("#apps-n").textContent = `${list.length} of ${apps.length}`;
    if (!list.length) { host.appendChild(el("p", "empty", apps.length ? "No applications match these filters." : "No applications yet. Share the Join the team link to get some!")); return; }
    list.forEach((a) => {
      const card = el("article", "app");
      const main = el("div");
      const meta = el("div", "meta");
      meta.append(el("span", "role", a.role_label), el("span", "", a.availability_label), el("span", "", fmtWhen(a.created_at)));
      if (a.link) { const l = el("a", "", a.link.replace(/^https?:\/\//, "").slice(0, 48)); l.href = a.link; l.target = "_blank"; l.rel = "noopener noreferrer"; meta.appendChild(l); }
      main.append(el("div", "who", `${a.name}  ·  ${a.email}`), meta);
      const side = el("div", "side");
      const pill = el("span", `pill ${a.status === "new" ? "new" : ""}`, a.status);
      const sel = el("select"); sel.setAttribute("aria-label", `Status for ${a.name}`);
      statuses.forEach((s) => { const o = el("option", "", s[0].toUpperCase() + s.slice(1)); o.value = s; if (s === a.status) o.selected = true; sel.appendChild(o); });
      sel.addEventListener("change", async () => {
        try { await api(`/admin/api/applications/${a.id}`, { method: "POST", body: JSON.stringify({ status: sel.value }) }); a.status = sel.value; pill.textContent = a.status; pill.className = `pill ${a.status === "new" ? "new" : ""}`; load(true); }
        catch (e) { alert(e.message); sel.value = a.status; }
      });
      const reply = el("a", "btn ghost", "Reply");
      reply.href = `mailto:${encodeURIComponent(a.email)}?subject=${encodeURIComponent("Your DopeHub application")}&body=${encodeURIComponent(`Hi ${a.name.split(" ")[0]},\n\nThanks for applying to join the DopeHub team as a ${a.role_label.toLowerCase()}.\n\n`)}`;
      side.append(pill, sel, reply);
      card.append(main, side, el("div", "msgtxt", a.message));
      host.appendChild(card);
    });
  }

  async function load(quiet) {
    try {
      const [s, a] = await Promise.all([api("/admin/api/summary"), api("/admin/api/applications")]);
      alerts(s);
      $("#t-subs").textContent = s.subscribers.total.toLocaleString("en-GB");
      $("#t-subs-sub").textContent = `${s.subscribers.confirmed} confirmed their email`;
      $("#t-apps").textContent = s.applications.new;
      $("#t-apps-sub").textContent = `${s.applications.total} in total`;
      $("#t-vis").textContent = s.visits.visitors30.toLocaleString("en-GB");
      $("#t-vis-sub").textContent = `${s.visits.pageviews30.toLocaleString("en-GB")} page views`;
      $("#t-conv").textContent = s.visits.conversion30 == null ? "–" : `${s.visits.conversion30}%`;
      columns($("#c-visitors"), s.daily, "visitors", "visitors");
      columns($("#c-subs"), s.daily, "subs", "sign-ups");
      const counts = s.survey.counts.slice().sort((x, y) => y.n - x.n);
      $("#sv-n").textContent = `${s.survey.responses} answer${s.survey.responses === 1 ? "" : "s"}`;
      hbars($("#c-survey"), counts, "No survey answers yet.");
      const other = $("#sv-other"); other.replaceChildren();
      if (s.survey.other.length) {
        other.appendChild(el("h3", "", "In their own words"));
        const ul = el("ul"); s.survey.other.forEach((t) => ul.appendChild(el("li", "", t))); other.appendChild(ul);
      }
      hbars($("#c-who"), Object.entries(s.subscribers.who).map(([k, n]) => ({ label: WHO[k] || k, n })).sort((x, y) => y.n - x.n), "No sign-ups yet.");
      hbars($("#c-ref"), s.visits.referrers.map((r) => ({ label: r.k, n: r.n })), "No visits counted yet.");
      hbars($("#c-dev"), s.visits.devices.map((r) => ({ label: r.k[0].toUpperCase() + r.k.slice(1), n: r.n })), "No visits counted yet.");
      apps = a.applications; statuses = a.statuses;
      if (!quiet) {
        const fs = $("#f-status"), fr = $("#f-role");
        if (fs.options.length === 1) statuses.forEach((st) => { const o = el("option", "", st[0].toUpperCase() + st.slice(1)); o.value = st; fs.appendChild(o); });
        const roles = [...new Map(apps.map((x) => [x.role, x.role_label])).entries()];
        fr.replaceChildren(el("option", "", "All roles")); fr.options[0].value = "";
        roles.forEach(([k, l]) => { const o = el("option", "", l); o.value = k; fr.appendChild(o); });
      }
      renderApps();
      $("#updated").textContent = `Updated ${new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`;
    } catch (e) {
      $("#alerts").replaceChildren(Object.assign(el("div", "alert crit"), { textContent: `Couldn't load data: ${e.message}` }));
    }
  }

  $("#refresh").addEventListener("click", () => load());
  $("#f-status").addEventListener("change", renderApps);
  $("#f-role").addEventListener("change", renderApps);
  $("#forget").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("input", e.target), msg = $("#forget-msg");
    if (!confirm(`Permanently delete all data for ${input.value}?`)) return;
    try {
      const r = await api("/admin/api/forget", { method: "POST", body: JSON.stringify({ email: input.value }) });
      msg.textContent = `Deleted ${r.subscribers} subscription(s) and ${r.applications} application(s).`;
      input.value = ""; load(true);
    } catch (err) { msg.textContent = err.message; }
  });
  let rs; addEventListener("resize", () => { clearTimeout(rs); rs = setTimeout(() => load(true), 250); });
  load();
  setInterval(() => { if (!document.hidden) load(true); }, 120000);
})();
