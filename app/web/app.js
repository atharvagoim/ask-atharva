/* Ask Atharva — web interface. Plain JavaScript, no build step. */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const app = $("#app");
const state = { status: null, threadId: null, pendingAsk: "", nav: 0 };
// Each render captures the navigation number; late responses for a page
// you've already left are ignored instead of touching a page that's gone.
const current = () => { const n = state.nav; return () => n === state.nav; };

// ---------- helpers ------------------------------------------------------
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
const icon = (name) => `<svg class="i" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const mark = (cls = "mk") => `<svg class="${cls}" aria-hidden="true"><use href="#cat-mark"/></svg>`;

// Voice input (browser speech recognition). Hidden where the browser can't do it.
const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
function bindVoice(btn, { onText, onDone }) {
  if (!SpeechRec) { btn.hidden = true; return; }
  let rec = null;
  const stop = () => { try { rec?.stop(); } catch { /* already stopped */ } };
  btn.addEventListener("click", () => {
    if (rec) return stop();
    rec = new SpeechRec();
    rec.lang = navigator.language || "en-US";
    rec.interimResults = true;
    rec.continuous = false;
    let text = "";
    rec.onstart = () => { btn.classList.add("listening"); btn.setAttribute("aria-pressed", "true"); };
    rec.onresult = (e) => { text = [...e.results].map((r) => r[0].transcript).join(" ").trim(); onText?.(text); };
    rec.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") toast("Allow the microphone to talk to me.", { error: true });
      else if (e.error === "no-speech") toast("I didn't catch that. Try again?");
      else if (e.error !== "aborted") toast("Voice isn't working right now.", { error: true });
    };
    rec.onend = () => { btn.classList.remove("listening"); btn.setAttribute("aria-pressed", "false"); rec = null; if (text) onDone?.(text); };
    try { rec.start(); } catch { rec = null; }
  });
}

// A tiny burst of confetti where you tick a todo off.
function confetti(el) {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches || !el?.animate) return;
  const r = el.getBoundingClientRect();
  const colors = ["#a98bf5", "#ffb95a", "#a8c7ff", "#f4a8ef", "#ffe27a", "#b5ebcf"];
  for (let i = 0; i < 16; i++) {
    const bit = document.createElement("i");
    bit.className = "confetti";
    bit.style.cssText = `left:${r.left + r.width / 2}px;top:${r.top + r.height / 2}px;background:${colors[i % colors.length]}`;
    document.body.append(bit);
    const a = (Math.PI * 2 * i) / 16 + Math.random() * 0.4, d = 40 + Math.random() * 40;
    bit.animate(
      [{ transform: "translate(-50%,-50%) scale(1)", opacity: 1 }, { transform: `translate(calc(-50% + ${Math.cos(a) * d}px), calc(-50% + ${Math.sin(a) * d + 24}px)) scale(0.3) rotate(220deg)`, opacity: 0 }],
      { duration: 650 + Math.random() * 250, easing: "cubic-bezier(.2,.8,.3,1)" },
    ).onfinish = () => bit.remove();
  }
}

async function api(path, { method = "GET", body, form } = {}) {
  const opts = { method, headers: {} };
  if (form) opts.body = form;
  else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(`/api${path}`, opts);
  } catch {
    throw Object.assign(new Error("Can't reach Ask Atharva. Is the app still running?"), { status: 0 });
  }
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (res.status === 401 && path !== "/login") { location.href = "/login"; throw Object.assign(new Error("Please sign in."), { status: 401 }); }
  if (!res.ok) throw Object.assign(new Error(data?.detail || "Something went wrong. Please try again."), { status: res.status });
  return data;
}

function toast(text, { error = false, action, onAction } = {}) {
  const el = document.createElement("div");
  el.className = `toast${error ? " error" : ""}`;
  el.setAttribute("role", error ? "alert" : "status");
  el.innerHTML = `<span>${esc(text)}</span>${action ? `<button type="button">${esc(action)}</button>` : ""}`;
  if (action) el.querySelector("button").addEventListener("click", () => { onAction?.(); el.remove(); });
  $("#toasts").append(el);
  setTimeout(() => el.remove(), error ? 7000 : action ? 6000 : 3200);
}

function confirmDelete(title, body, okLabel = "Delete") {
  const dlg = $("#confirm");
  $("#confirm-ok").textContent = okLabel;
  $("#confirm-title").textContent = title;
  $("#confirm-body").textContent = body;
  return new Promise((resolve) => {
    const done = (v) => { dlg.close(); cleanup(); resolve(v); };
    const ok = () => done(true);
    const cancel = (e) => { e?.preventDefault?.(); done(false); };
    const cleanup = () => {
      $("#confirm-ok").removeEventListener("click", ok);
      $("#confirm-cancel").removeEventListener("click", cancel);
      dlg.removeEventListener("cancel", cancel);
    };
    $("#confirm-ok").addEventListener("click", ok);
    $("#confirm-cancel").addEventListener("click", cancel);
    dlg.addEventListener("cancel", cancel);
    dlg.showModal();
    $("#confirm-cancel").focus();
  });
}

// Tiny, safe markdown: escape first, then **bold**, `code`, lists and paragraphs.
function md(text) {
  const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
  const out = [];
  let list = null;
  let table = null; // consecutive column-aligned lines (spreadsheet output) stay aligned
  const flushTable = () => { if (table) { out.push(`<pre class="table">${esc(table.join("\n"))}</pre>`); table = null; } };
  for (const raw of String(text || "").split("\n")) {
    const line = raw.trimEnd();
    if (/\S {2,}\S/.test(line) && !/^\s*[-*•]\s/.test(line)) {
      if (list) { out.push(`</${list.type}>`); list = null; }
      (table ||= []).push(line);
      continue;
    }
    flushTable();
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    const num = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (bullet || num) {
      const type = bullet ? "ul" : "ol";
      if (!list || list.type !== type) { if (list) out.push(`</${list.type}>`); list = { type }; out.push(`<${type}>`); }
      out.push(`<li>${inline((bullet || num)[1])}</li>`);
      continue;
    }
    if (list) { out.push(`</${list.type}>`); list = null; }
    if (!line.trim()) { out.push(""); continue; }
    if (/^[-=]{3,}$/.test(line.trim())) continue; // underline rules from plain-text headings
    out.push(`<p>${inline(line)}</p>`);
  }
  flushTable();
  if (list) out.push(`</${list.type}>`);
  return out.join("");
}

const today = () => new Date();
function localISO(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function dayLabel(iso) {
  if (!iso) return "";
  const d = new Date(`${iso}T00:00:00`);
  const diff = Math.round((d - new Date(`${localISO(today())}T00:00:00`)) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  if (diff === -1) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}
const timeOf = (iso) => new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
const sizeOf = (n) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`);
const ext = (name) => (name.split(".").pop() || "").toLowerCase();
const firstName = () => (state.status?.name || "Atharva").split(" ")[0];

// ---------- status -------------------------------------------------------
async function loadStatus() {
  try {
    state.status = await api("/status");
  } catch {
    state.status = null;
  }
  const s = state.status;
  document.title = `Ask ${s ? firstName() : "Atharva"}`;
  $("#hello-name").textContent = `Hello, ${s ? firstName() : "there"}`;
  $("#hello-date").textContent = today().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" });
  const initial = (s ? firstName() : "A").charAt(0).toUpperCase();
  const face = s?.photo ? `<img src="${esc(s.photo)}" alt="">` : initial;
  $("#avatar-letter").innerHTML = face;
  $("#rail-av").innerHTML = face;
  $("#rail-name").textContent = s ? firstName() : "";
  $("#avatar").classList.toggle("alert", !s); // orange dot: the app can't be reached
  $("#brand-name").textContent = `Ask ${s ? firstName() : "Atharva"}`;
  const rail = $("#rail-status");
  if (!s) rail.innerHTML = `<span class="dot warn"></span><span>Offline</span>`;
  else if (!s.ai.ready) rail.innerHTML = `<span class="dot warn"></span><span>Chat is offline</span>`;
  else rail.innerHTML = `<span class="dot ok"></span><span>Ready</span>`;
  return s;
}

// ---------- uploads ------------------------------------------------------
function pickFile(accept) {
  return new Promise((resolve) => {
    const input = $("#file-picker");
    input.value = "";
    input.accept = accept || ".xlsx,.xlsm,.csv,.txt,.md,.vtt,.srt";
    input.onchange = () => resolve(input.files[0] || null);
    input.click();
  });
}
async function uploadFile(file) {
  const form = new FormData();
  form.append("file", file);
  return api("/files", { method: "POST", form });
}

// ---------- router -------------------------------------------------------
const routes = { today: renderToday, chat: renderChat, todos: renderTodos, calendar: renderCalendar, files: renderFiles, settings: renderSettings };

async function route() {
  const [name, arg] = location.hash.replace(/^#\/?/, "").split("/");
  const page = routes[name] ? name : "today";
  $$(".tabbar a, .rail-nav a").forEach((a) => {
    if (a.getAttribute("href") === `#/${page}`) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  state.nav++;
  document.body.dataset.page = page;
  app.innerHTML = "";
  window.scrollTo(0, 0);
  try {
    await routes[page](arg ? decodeURIComponent(arg) : undefined);
  } catch (err) {
    app.innerHTML = `<div class="page"><div class="card"><p>${esc(err.message)}</p><button class="btn ghost" onclick="location.reload()">Reload</button></div></div>`;
  }
}

function goChat(question) {
  state.pendingAsk = question;
  state.threadId = null;
  if (location.hash === "#/chat") route();
  else location.hash = "#/chat";
}

// ---------- Progress (shared by Home and Todos) ----------------------------
function progressCard(st) {
  const msg = !st.total ? "Add your first task and I'll track your progress here."
    : st.percent === 100 ? "Everything is done. Nice work! 🎉"
    : st.overdue ? `${st.overdue} overdue — tackle ${st.overdue === 1 ? "that one" : "those"} first.`
    : st.due_today ? `${st.due_today} due today. You've finished ${st.done} so far.`
    : `${st.open} to go. You've finished ${st.done} so far.`;
  const R = 48, C = 2 * Math.PI * R;
  const max = Math.max(1, ...st.last7.map((d) => d.done));
  const bars = st.last7.map((d, i) => {
    const day = new Date(`${d.date}T00:00:00`);
    return `<div class="bar-col${i === 6 ? " now" : ""}" title="${esc(day.toLocaleDateString(undefined, { weekday: "long" }))}: ${d.done} done">
      <span class="bar-n">${d.done || ""}</span><i style="--h:${Math.max(6, Math.round((d.done / max) * 100))}%;--d:${i * 70}ms"></i><small>${day.toLocaleDateString(undefined, { weekday: "narrow" })}</small></div>`;
  }).join("");
  return `<section class="card tone-mint progress" aria-label="Your progress">
    <div class="pg-top">
      <div class="ring" role="img" aria-label="${st.percent}% of tasks done">
        <svg viewBox="0 0 120 120"><circle class="trk" cx="60" cy="60" r="${R}"/><circle class="val" cx="60" cy="60" r="${R}" style="--len:${((st.percent / 100) * C).toFixed(1)};--circ:${C.toFixed(1)}"/></svg>
        <div class="ring-mid"><b>${st.percent}%</b><small>done</small></div>
      </div>
      <div class="pg-nums">
        <div><b>${st.total}</b><span>Total tasks</span></div>
        <div><b>${st.done}</b><span>Completed</span></div>
        <div><b>${st.open}</b><span>Still open</span></div>
      </div>
    </div>
    <p class="pg-msg">${esc(msg)}</p>
    <div class="pg-week" aria-label="Tasks completed in the last 7 days">${bars}</div>
    <p class="pg-cap">Completed in the last 7 days</p>
  </section>`;
}

async function loadProgress(slot, live) {
  try {
    const st = await api("/todos/stats");
    if (live()) slot.innerHTML = progressCard(st);
  } catch (err) { if (live()) slot.innerHTML = `<section class="card"><p class="empty">${esc(err.message)}</p></section>`; }
}

// ---------- Today --------------------------------------------------------
function greetingWord() {
  const h = today().getHours();
  return h < 5 ? "Still up" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

function weekStrip(dueDays = new Set()) {
  const n = today();
  const start = new Date(n.getFullYear(), n.getMonth(), n.getDate() - n.getDay()); // Sunday first
  const days = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
    const iso = localISO(d);
    days.push(`<a href="#/calendar" class="${iso === localISO(n) ? "on" : ""}" aria-label="${esc(d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" }))}">
      ${dueDays.has(iso) ? "<i></i>" : ""}<small>${d.toLocaleDateString(undefined, { weekday: "short" })}</small><b>${d.getDate()}</b></a>`);
  }
  return `<nav class="week" id="week-strip" aria-label="This week">${days.join("")}</nav>`;
}

async function renderToday() {
  const live = current();
  const s = state.status || (await loadStatus());
  if (!live()) return;
  app.innerHTML = `<div class="page home">
    <section class="hero">
      <div class="hero-art" aria-hidden="true"><span class="mark-tile">${mark("mk-big")}</span><i class="spark sp1"></i><i class="spark sp2"></i><i class="spark sp3"></i></div>
      <div class="hero-text">
        <h1>${esc(greetingWord())}, ${esc(firstName())}</h1>
        <p class="summary" id="today-summary">&nbsp;</p>
      </div>
      <form class="ask-box" id="ask-form">
        <label class="sr-only" for="ask">Ask anything</label>
        <input id="ask" autocomplete="off" enterkeyhint="send" placeholder="Ask anything…" />
        <button type="button" class="mic" id="mic" aria-label="Talk instead of typing" aria-pressed="false">${icon("mic")}</button>
        <button type="submit" class="go" aria-label="Ask">${icon("send")}</button>
      </form>
    </section>
    ${s && !s.ai.ready ? `<div class="callout"><span class="tint">${icon("spark")}</span><div class="grow"><strong>Chat is switched off for now</strong>Your todos, calendar and files all still work.</div></div>` : ""}
    <div class="home-grid">
      <div class="home-main">
        ${weekStrip()}
        <h2 class="section-title">Your plan</h2>
        <div class="plan">
          <section class="card tone-orange big"><span class="tag" id="t-count">To do</span><h3>To do</h3><div id="t-todos"><p class="empty">Loading…</p></div></section>
          <a class="card tone-blue tile" href="#/calendar" id="t-cal"><span class="tag">Calendar</span><h3>…</h3></a>
          <section class="card tone-pink" id="quick">
            <div class="quick-card">
              <button type="button" data-ask="Make a 6-slide presentation about " aria-label="Make slides"><span class="c">${icon("spark")}</span><b>Slides</b></button>
              <button type="button" data-ask="Find me a free hour tomorrow" aria-label="Find free time"><span class="c">${icon("sun")}</span><b>Free time</b></button>
              <button type="button" data-upload aria-label="Analyse a file"><span class="c">${icon("clip")}</span><b>File</b></button>
            </div>
          </section>
        </div>
        <div id="t-tomorrow"></div>
      </div>
      <aside class="home-side">
        <h2 class="section-title">Your progress</h2>
        <div id="t-progress"><section class="card tone-mint"><p class="empty">Loading…</p></section></div>
      </aside>
    </div>
  </div>`;

  bindVoice($("#mic"), {
    onText: (t) => { $("#ask").value = t; },
    onDone: (t) => goChat(t),
  });
  $("#ask-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = $("#ask").value.trim();
    if (q) goChat(q);
    else $("#ask").focus();
  });
  $("#quick").addEventListener("click", async (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.upload !== undefined) {
      const file = await pickFile();
      if (!file) return;
      try {
        const f = await uploadFile(file);
        goChat(/\.(txt|md|vtt|srt)$/i.test(f.name) ? `Summarise my notes in ${f.name} and add the action items to my todos` : `Analyse ${f.name} and give me the key takeaways`);
      } catch (err) { toast(err.message, { error: true }); }
      return;
    }
    const q = b.dataset.ask;
    if (q.endsWith(" ")) { $("#ask").value = q; $("#ask").focus(); $("#ask").scrollIntoView({ block: "center", behavior: "smooth" }); }
    else goChat(q);
  });

  let data;
  try {
    data = await api("/today");
  } catch (err) {
    if (live()) $("#today-summary").textContent = err.message;
    return;
  }
  if (!live()) return;
  const bits = [];
  bits.push(data.open_count ? `${data.open_count} to do` : "Nothing to do");
  if (data.events.length) bits.push(`${data.events.length} event${data.events.length === 1 ? "" : "s"}`);
  if (data.done_today) bits.push(`${data.done_today} done`);
  $("#today-summary").textContent = bits.join(" · ");

  // dots on the week strip for days with a todo due
  api("/todos?show=open").then((all) => {
    if (!live()) return;
    const due = new Set(all.filter((t) => t.due).map((t) => t.due));
    $("#week-strip").outerHTML = weekStrip(due);
  }).catch(() => {});

  const todoList = [...data.due, ...data.upcoming].slice(0, 4);
  $("#t-count").textContent = data.open_count ? `${data.open_count} open` : "All clear";
  $("#t-todos").innerHTML = todoList.length
    ? `<ul class="list">${todoList.map((t) => todoRow(t, { compact: true })).join("")}</ul><a class="more" href="#/todos">See all ${icon("arrow")}</a>`
    : `<p class="empty">Nothing on your list.</p><a class="more" href="#/todos">Add one ${icon("arrow")}</a>`;
  bindTodoRows($("#t-todos"), () => renderToday());

  const tom = $("#t-tomorrow");
  if (data.tomorrow?.length) {
    tom.innerHTML = `<h2 class="section-title">Tomorrow</h2>
      <section class="card tone-yellow tomorrow"><span class="tag">${data.tomorrow.length} task${data.tomorrow.length === 1 ? "" : "s"} tomorrow</span>
        <ul class="list">${data.tomorrow.map((t) => todoRow(t, { compact: true })).join("")}</ul></section>`;
    bindTodoRows(tom, () => renderToday());
  }

  const cal = $("#t-cal");
  if (data.events.length) {
    const e = data.events[0];
    cal.innerHTML = `<span class="tag">${data.events.length} today</span><h3>${esc(e.title)}</h3><div class="meta">${e.all_day ? "All day" : `${esc(timeOf(e.start))}–${esc(timeOf(e.end))}`}${e.location ? `<br>${esc(e.location)}` : ""}</div>`;
  } else {
    cal.innerHTML = `<span class="tag">Today</span><h3>Free day</h3><div class="meta">Tap to plan something</div>`;
  }

  loadProgress($("#t-progress"), live);
}

// ---------- Todos --------------------------------------------------------
function todoRow(t, { compact = false } = {}) {
  const now = localISO(today());
  const due = t.due ? (t.due < now && !t.done ? `<span class="pill overdue">Overdue · ${esc(dayLabel(t.due))}</span>` : t.due === now ? `<span class="pill today">Today</span>` : `<span class="pill">${esc(dayLabel(t.due))}</span>`) : "";
  const prio = t.priority !== "medium" ? `<span class="pill ${esc(t.priority)}">${t.priority === "high" ? "High" : "Low"}</span>` : "";
  return `<li class="item" data-id="${t.id}">
    <button class="check" role="checkbox" aria-checked="${t.done}" aria-label="${t.done ? "Mark as not done" : "Mark as done"}: ${esc(t.title)}">${icon("check")}</button>
    <div class="grow"><div class="title ${t.done ? "done-text" : ""}">${esc(t.title)}</div>${due || prio ? `<div class="meta">${due}${prio}</div>` : ""}</div>
    ${compact ? "" : `<div class="actions"><button class="icon-btn" data-edit aria-label="Edit ${esc(t.title)}">${icon("edit")}</button><button class="icon-btn" data-del aria-label="Delete ${esc(t.title)}">${icon("trash")}</button></div>`}
  </li>`;
}

function bindTodoRows(root, refresh) {
  root.addEventListener("click", async (e) => {
    const li = e.target.closest("li[data-id]");
    if (!li || e.target.closest("form")) return; // clicks inside the inline editor are handled there
    const id = li.dataset.id;
    const title = $(".title", li)?.textContent || "this todo";
    if (e.target.closest(".check")) {
      const done = $(".check", li).getAttribute("aria-checked") !== "true";
      try {
        await api(`/todos/${id}`, { method: "PATCH", body: { done } });
        if (done) confetti($(".check", li));
        if (done) toast(`Done: ${title}`, { action: "Undo", onAction: async () => { await api(`/todos/${id}`, { method: "PATCH", body: { done: false } }); refresh(); } });
        refresh();
      } catch (err) { toast(err.message, { error: true }); }
    } else if (e.target.closest("[data-del]")) {
      if (!(await confirmDelete("Delete this todo?", `“${title}” will be removed for good.`))) return;
      try { await api(`/todos/${id}`, { method: "DELETE" }); toast("Todo deleted"); refresh(); } catch (err) { toast(err.message, { error: true }); }
    } else if (e.target.closest("[data-edit]")) {
      editTodoInline(li, refresh);
    }
  });
}

function editTodoInline(li, refresh) {
  const id = li.dataset.id;
  const title = $(".title", li).textContent;
  li.innerHTML = `<form class="grow stack" style="gap:8px">
      <input class="input" name="title" value="${esc(title)}" aria-label="Todo title" maxlength="300" required>
      <div class="add-form"><div class="opts"><select class="input" name="priority" aria-label="Priority"><option value="">Keep priority</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select>
      <input class="input" type="date" name="due" aria-label="Due date"></div></div>
      <div class="row"><button class="btn sm">Save</button><button class="btn quiet sm" type="button" data-cancel>Cancel</button></div>
    </form>`;
  const form = $("form", li);
  $("input", form).focus();
  $("[data-cancel]", form).addEventListener("click", refresh);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = { title: form.title.value.trim() };
    if (form.priority.value) body.priority = form.priority.value;
    if (form.due.value) body.due = form.due.value;
    try { await api(`/todos/${id}`, { method: "PATCH", body }); toast("Saved"); refresh(); } catch (err) { toast(err.message, { error: true }); }
  });
}

async function renderTodos(show = "open") {
  app.innerHTML = `<div class="page">
    <div class="page-head"><div><h1 class="page-title">Todos</h1></div></div>
    <form class="card tone-orange add-form" id="add-todo">
      <label class="sr-only" for="new-title">New todo</label>
      <div class="line"><input class="input" id="new-title" placeholder="Add a todo…" maxlength="300" enterkeyhint="done"><button class="btn" aria-label="Add">${icon("plus")}<span class="lbl">Add</span></button></div>
      <div class="opts">
        <select class="input" id="new-prio" aria-label="Priority"><option value="medium">Normal</option><option value="high">High priority</option><option value="low">Low priority</option></select>
        <input class="input" type="date" id="new-due" aria-label="Due date (optional)" min="${localISO(today())}">
      </div>
    </form>
    <div id="todo-progress" style="margin-top:14px"></div>
    <div class="seg" role="group" aria-label="Show" style="margin-top:14px">
      <button data-show="open" aria-pressed="${show === "open"}">To do</button>
      <button data-show="done" aria-pressed="${show === "done"}">Done</button>
    </div>
    <div class="card" id="todo-list"><p class="empty">Loading…</p></div>
  </div>`;
  $$("[data-show]").forEach((b) => b.addEventListener("click", () => renderTodos(b.dataset.show)));
  $("#add-todo").addEventListener("submit", async (e) => {
    e.preventDefault();
    const title = $("#new-title").value.trim();
    if (!title) return $("#new-title").focus();
    try {
      const t = await api("/todos", { method: "POST", body: { title, priority: $("#new-prio").value, due: $("#new-due").value || null } });
      toast(t.created ? "Added" : "That's already on your list");
      $("#new-title").value = "";
      $("#new-due").value = "";
      load();
    } catch (err) { toast(err.message, { error: true }); }
  });
  const box = $("#todo-list");
  bindTodoRows(box, () => load());

  const live = current();
  async function load() {
    loadProgress($("#todo-progress"), live);
    let items;
    try { items = await api(`/todos?show=${show}`); } catch (err) { if (live()) box.innerHTML = `<p class="empty">${esc(err.message)}</p>`; return; }
    if (!live()) return;
    if (!items.length) {
      box.innerHTML = `<p class="empty">${show === "open" ? "All clear. Add your first todo above." : "Nothing finished yet — it'll show up here."}</p>`;
      return;
    }
    if (show === "done") { box.innerHTML = `<ul class="list">${items.map((t) => todoRow(t)).join("")}</ul>`; return; }
    const now = localISO(today());
    const groups = [
      ["Overdue", items.filter((t) => t.due && t.due < now)],
      ["Today", items.filter((t) => t.due === now)],
      ["Coming up", items.filter((t) => t.due && t.due > now)],
      ["Anytime", items.filter((t) => !t.due)],
    ].filter(([, list]) => list.length);
    box.innerHTML = groups.map(([label, list]) => `<p class="group-label">${label}</p><ul class="list">${list.map((t) => todoRow(t)).join("")}</ul>`).join("");
  }
  load();
}

// ---------- Calendar -----------------------------------------------------
const TONES = ["purple", "orange", "blue", "pink", "yellow", "mint"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

async function renderCalendar() {
  const live = current();
  const now = today();
  const todayIso = localISO(now);
  let view = new Date(now.getFullYear(), now.getMonth(), 1); // first of the month on screen
  let selected = todayIso;
  let events = [];
  let gridStart = null;

  app.innerHTML = `<div class="page cal">
    <div class="page-head"><div><h1 class="page-title">Calendar</h1><p class="page-sub">Your own calendar. Tap a day, or ask in chat.</p></div></div>
    <div class="cal-layout">
      <section class="card cal-card" aria-label="Month">
        <div class="cal-nav">
          <button class="round-btn sm" id="prev" type="button" aria-label="Previous month">${icon("arrow").replace("<svg", '<svg style="transform:scaleX(-1)"')}</button>
          <h2 id="month-label" aria-live="polite"></h2>
          <button class="round-btn sm" id="next" type="button" aria-label="Next month">${icon("arrow")}</button>
        </div>
        <div class="cal-dow" aria-hidden="true">${["S", "M", "T", "W", "T", "F", "S"].map((d) => `<span>${d}</span>`).join("")}</div>
        <div class="cal-grid" id="grid" role="grid"></div>
        <button class="chip" id="go-today" type="button" style="margin-top:14px">${icon("sun")}Jump to today</button>
      </section>
      <section class="cal-day" aria-label="Day">
        <div class="day-head"><h2 id="day-title"></h2><span class="tag" id="day-count"></span></div>
        <div id="agenda"></div>
      </section>
    </div>
    <button class="fab" id="add-event" type="button" aria-label="Add an event">${icon("plus")}<span>New event</span></button>
  </div>`;

  const grid = $("#grid");
  const gridDays = () => {
    const first = new Date(view.getFullYear(), view.getMonth(), 1);
    const start = new Date(first.getFullYear(), first.getMonth(), 1 - first.getDay());
    return Array.from({ length: 42 }, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
  };
  const byDay = () => {
    const map = new Map();
    for (const e of events) { const k = e.start.slice(0, 10); (map.get(k) || map.set(k, []).get(k)).push(e); }
    return map;
  };

  function paintGrid() {
    const days = gridDays();
    const map = byDay();
    $("#month-label").textContent = `${MONTHS[view.getMonth()]} ${view.getFullYear()}`;
    grid.innerHTML = days.map((d, i) => {
      const iso = localISO(d);
      const n = (map.get(iso) || []).length;
      const cls = ["day", d.getMonth() !== view.getMonth() ? "out" : "", iso === todayIso ? "today" : "", iso === selected ? "sel" : ""].filter(Boolean).join(" ");
      return `<button type="button" role="gridcell" class="${cls}" data-day="${iso}" style="--i:${i}" aria-label="${esc(d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" }))}${n ? `, ${n} event${n === 1 ? "" : "s"}` : ""}" aria-pressed="${iso === selected}"><b>${d.getDate()}</b>${n ? `<span class="dots">${"<i></i>".repeat(Math.min(n, 3))}</span>` : ""}</button>`;
    }).join("");
  }

  function paintAgenda() {
    const list = (byDay().get(selected) || []).slice().sort((a, b) => (a.all_day === b.all_day ? a.start.localeCompare(b.start) : a.all_day ? -1 : 1));
    $("#day-title").textContent = selected === todayIso ? "Today" : new Date(`${selected}T00:00:00`).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
    $("#day-count").textContent = list.length ? `${list.length} event${list.length === 1 ? "" : "s"}` : "Free";
    $("#agenda").innerHTML = list.length
      ? list.map((e, i) => `<button type="button" class="ev tone-${TONES[i % TONES.length]}" data-id="${esc(e.id)}" style="--i:${i}">
          <span class="ev-time">${e.all_day ? "All<br>day" : `${esc(timeOf(e.start))}<small>${esc(timeOf(e.end))}</small>`}</span>
          <span class="ev-body"><b>${esc(e.title)}</b>${e.location ? `<span>${icon("pin")}${esc(e.location)}</span>` : ""}</span>
          <span class="ev-edit" aria-hidden="true">${icon("edit")}</span></button>`).join("")
      : `<div class="free-day"><span class="free-emoji" aria-hidden="true">🌿</span><p>Nothing planned. Enjoy the space, or add something.</p></div>`;
  }

  async function load() {
    const days = gridDays();
    gridStart = days[0];
    paintGrid();
    paintAgenda();
    try {
      const data = await api(`/calendar/events?day=${localISO(days[0])}&days=42`);
      if (!live()) return;
      events = data.events;
      paintGrid();
      paintAgenda();
    } catch (err) { if (live()) toast(err.message, { error: true }); }
  }

  const shift = (months) => { view = new Date(view.getFullYear(), view.getMonth() + months, 1); selected = localISO(new Date(view.getFullYear(), view.getMonth(), view.getMonth() === now.getMonth() && view.getFullYear() === now.getFullYear() ? now.getDate() : 1)); load(); };
  $("#prev").addEventListener("click", () => shift(-1));
  $("#next").addEventListener("click", () => shift(1));
  $("#go-today").addEventListener("click", () => { view = new Date(now.getFullYear(), now.getMonth(), 1); selected = todayIso; load(); });
  grid.addEventListener("click", (e) => {
    const b = e.target.closest("[data-day]");
    if (!b) return;
    selected = b.dataset.day;
    const d = new Date(`${selected}T00:00:00`);
    if (d.getMonth() !== view.getMonth()) { view = new Date(d.getFullYear(), d.getMonth(), 1); load(); } else { paintGrid(); paintAgenda(); }
  });
  $("#agenda").addEventListener("click", (e) => {
    const b = e.target.closest("[data-id]");
    if (b) openEventSheet(events.find((x) => x.id === b.dataset.id), selected, load);
  });
  $("#add-event").addEventListener("click", () => openEventSheet(null, selected, load));
  load();
}

// The "new / edit event" sheet (a bottom sheet on phones, a centred card on laptops).
function openEventSheet(event, day, refresh) {
  const dlg = $("#event-sheet");
  const f = $("#event-form");
  const editing = !!event;
  const start = event ? new Date(event.start) : null;
  const hh = (d) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  const soon = new Date(); soon.setMinutes(0, 0, 0); soon.setHours(soon.getHours() + 1);
  $("#sheet-title").textContent = editing ? "Edit event" : "New event";
  f.reset();
  f.title.value = event?.title || "";
  f.date.value = event ? event.start.slice(0, 10) : day;
  f.all_day.checked = !!event?.all_day;
  f.time.value = event && !event.all_day ? hh(start) : hh(soon);
  f.duration.value = event && !event.all_day ? String(Math.max(5, Math.round((new Date(event.end) - start) / 60000))) : "60";
  if (![...f.duration.options].some((o) => o.value === f.duration.value)) f.duration.add(new Option(`${f.duration.value} min`, f.duration.value, true, true));
  f.location.value = event?.location || "";
  f.notes.value = event?.notes || "";
  $("#event-delete").hidden = !editing;
  const timed = $("#timed-row");
  const sync = () => { timed.hidden = f.all_day.checked; };
  f.all_day.onchange = sync;
  sync();

  const close = () => dlg.close();
  $("#event-cancel").onclick = close;
  dlg.onclick = (e) => { if (e.target === dlg) close(); };
  $("#event-delete").onclick = async () => {
    close();
    if (!(await confirmDelete("Delete this event?", `“${event.title}” will be removed from your calendar.`))) return;
    try { await api(`/calendar/events/${encodeURIComponent(event.id)}`, { method: "DELETE" }); toast("Event deleted"); refresh(); } catch (err) { toast(err.message, { error: true }); }
  };
  f.onsubmit = async (e) => {
    e.preventDefault();
    const body = { title: f.title.value.trim(), date: f.date.value, all_day: f.all_day.checked, location: f.location.value.trim(), notes: f.notes.value.trim() };
    if (!body.title) return f.title.focus();
    if (!body.all_day) { body.time = f.time.value; body.duration_minutes = Number(f.duration.value); }
    try {
      const saved = await api(editing ? `/calendar/events/${encodeURIComponent(event.id)}` : "/calendar/events", { method: editing ? "PATCH" : "POST", body });
      close();
      toast(editing ? "Saved" : `Added ${saved.title} — ${dayLabel(saved.start.slice(0, 10))}${saved.all_day ? "" : ` at ${timeOf(saved.start)}`}`);
      refresh();
    } catch (err) { toast(err.message, { error: true }); }
  };
  dlg.showModal();
  if (!editing) f.title.focus();
}

// ---------- Files --------------------------------------------------------
function fileRow(f, { compact = false, ask = false } = {}) {
  const e = ext(f.name);
  const askLabel = /^(txt|md|vtt|srt)$/.test(e) ? "Summarise" : "Analyse";
  return `<div class="file"><span class="file-icon ${esc(e)}">${esc(e.slice(0, 4))}</span>
    <div class="grow"><div class="title" style="overflow-wrap:anywhere;font-weight:600">${esc(f.name)}</div><div class="faint small">${sizeOf(f.size)} · ${esc(dayLabel(f.modified.slice(0, 10)) || "")}</div></div>
    ${ask ? `<button class="btn ghost sm" data-ask="${esc(f.name)}">${askLabel}</button>` : ""}
    <a class="icon-btn" href="${esc(f.url)}" download aria-label="Download ${esc(f.name)}">${icon("download")}</a>
    ${compact ? "" : `<button class="icon-btn" data-del="${esc(f.kind)}/${esc(f.name)}" aria-label="Delete ${esc(f.name)}">${icon("trash")}</button>`}
  </div>`;
}

async function renderFiles() {
  app.innerHTML = `<div class="page" id="files-page">
    <div class="page-head"><div><h1 class="page-title">Files</h1></div></div>
    <div class="drop" id="drop" role="button" tabindex="0" aria-label="Upload a file">
      <span class="plus">${icon("plus")}</span>
      <div style="font-size:18px;font-weight:800">Add a file</div>
      <div class="small" style="margin-top:2px;opacity:.75">Spreadsheet or notes · up to ${state.status?.max_upload_mb || 25} MB</div>
    </div>
    <div class="grid-2" style="margin-top:12px">
      <section class="card"><div class="card-head"><h2>Your uploads</h2><span class="tint" style="background:var(--mint)">${icon("clip")}</span></div><div id="uploads"><p class="empty">Loading…</p></div></section>
      <section class="card"><div class="card-head"><h2>Made for you</h2><span class="tint" style="background:var(--orange)">${icon("spark")}</span></div><div id="outputs"><p class="empty">Loading…</p></div></section>
    </div></div>`;
  const drop = $("#drop");
  const send = async (file) => {
    if (!file) return;
    try { const f = await uploadFile(file); toast(`Uploaded ${f.name}`); load(); } catch (err) { toast(err.message, { error: true }); }
  };
  drop.addEventListener("click", async () => send(await pickFile()));
  drop.addEventListener("keydown", async (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); send(await pickFile()); } });
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); send(e.dataTransfer.files[0]); });

  $("#files-page").addEventListener("click", async (e) => {
    const askBtn = e.target.closest("[data-ask]");
    if (askBtn) {
      const n = askBtn.dataset.ask;
      goChat(/\.(txt|md|vtt|srt)$/i.test(n) ? `Summarise my notes in ${n} and add the action items to my todos` : `Analyse ${n} and give me the key takeaways`);
      return;
    }
    const del = e.target.closest("[data-del]");
    if (del && del.closest("#uploads, #outputs")) {
      const [kind, ...rest] = del.dataset.del.split("/");
      const name = rest.join("/");
      if (!(await confirmDelete("Delete this file?", `“${name}” will be removed for good.`))) return;
      try { await api(`/files/${kind}/${encodeURIComponent(name)}`, { method: "DELETE" }); toast("File deleted"); load(); } catch (err) { toast(err.message, { error: true }); }
    }
  });

  const live = current();
  async function load() {
    let data;
    try { data = await api("/files"); } catch (err) { if (live()) $("#uploads").innerHTML = `<p class="empty">${esc(err.message)}</p>`; return; }
    if (!live()) return;
    $("#uploads").innerHTML = data.uploads.length ? data.uploads.map((f) => fileRow(f, { ask: true })).join("") : `<p class="empty">Nothing uploaded yet.</p>`;
    $("#outputs").innerHTML = data.outputs.length ? data.outputs.map((f) => fileRow(f)).join("") : `<p class="empty">Ask for slides, a chart or a spreadsheet report and it lands here.</p>`;
  }
  load();
}

// ---------- Chat ---------------------------------------------------------
function messageHTML(m) {
  if (m.role === "user") return `<div class="msg user">${esc(m.content)}</div>`;
  const files = (m.files || []).map((f) => `<a class="file-chip" href="${esc(f.url)}" download>${icon("download")}${esc(f.name)}</a>`).join("");
  return `<div class="msg ai${m.error ? " error" : ""}"><span class="avatar" aria-hidden="true">${mark()}</span><div class="body">${md(m.content)}${files ? `<div class="msg-files">${files}</div>` : ""}${m.retry ? `<button class="btn ghost sm" data-retry style="margin-top:10px">Try again</button>` : ""}</div></div>`;
}

async function renderChat(threadArg) {
  const live = current();
  const s = state.status || (await loadStatus());
  if (!live()) return;
  if (threadArg) state.threadId = threadArg;
  const starters = [
    "What's on my plate today?",
    "Add “prepare demo” for Friday, high priority",
    "Make a 5-slide deck on time blocking",
    "Find a free 30 minutes tomorrow",
  ];
  app.innerHTML = `<div class="chat-layout">
    <section class="chat">
      <div class="chat-head"><h1>Chat</h1><button class="btn sm" id="new-chat">${icon("plus")}New chat</button></div>
      <nav class="thread-pick" id="thread-list" aria-label="Past chats" hidden></nav>
      ${s && !s.ai.ready ? `<div class="callout"><span class="tint">${icon("spark")}</span><div class="grow"><strong>Chat is switched off for now</strong>The app owner needs to turn the assistant on. Todos, calendar and files still work.</div></div>` : ""}
      <div class="messages" id="messages" aria-live="polite"></div>
      <div class="attach-note" id="attach-note" hidden></div>
      <form class="composer" id="composer">
        <button class="icon-btn" type="button" id="attach" aria-label="Attach a spreadsheet or notes">${icon("clip")}</button>
        <label class="sr-only" for="prompt">Message</label>
        <textarea id="prompt" rows="1" placeholder="Ask ${esc(firstName())}…" maxlength="20000"></textarea>
        <button class="icon-btn mic" type="button" id="chat-mic" aria-label="Talk instead of typing" aria-pressed="false">${icon("mic")}</button>
        <button class="btn send" type="submit" aria-label="Send">${icon("send")}</button>
      </form>
    </section></div>`;

  const list = $("#messages");
  const input = $("#prompt");
  let attached = null;
  let busy = false;
  let lastQuestion = "";

  const newChat = () => { state.threadId = null; history.replaceState(null, "", "#/chat"); renderChat(); };
  $("#new-chat").addEventListener("click", newChat);

  bindVoice($("#chat-mic"), { onText: (t) => { input.value = t; autosize(); } });
  // On phones, focusing pops the keyboard and hides the nav, so only auto-focus with a mouse.
  const focusInput = () => { if (matchMedia("(pointer: fine)").matches) input.focus(); };
  const autosize = () => { input.style.height = "auto"; input.style.height = `${Math.min(200, input.scrollHeight)}px`; };
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#composer").requestSubmit(); }
  });
  $("#attach").addEventListener("click", async () => {
    const file = await pickFile();
    if (!file) return;
    try {
      attached = await uploadFile(file);
      const note = $("#attach-note");
      note.hidden = false;
      note.textContent = `Attached ${attached.name}. Ask anything about it.`;
      if (!input.value.trim()) input.value = /\.(txt|md|vtt|srt)$/i.test(attached.name) ? `Summarise ${attached.name} and add the action items to my todos` : `Analyse ${attached.name} and give me the key takeaways`;
      input.focus();
      autosize();
    } catch (err) { toast(err.message, { error: true }); }
  });

  const scroll = () => window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });

  function showStarter() {
    list.innerHTML = `<div class="starter"><p class="muted" style="margin:0 0 12px">Tap one, or type your own:</p><div class="starter-list">${starters.map((q) => `<button class="chip" type="button" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div></div>`;
  }
  list.addEventListener("click", (e) => {
    const b = e.target.closest("[data-q]");
    if (b) { input.value = b.dataset.q; send(); }
  });

  async function loadThreads() {
    let threads = [];
    try { threads = await api("/threads"); } catch { /* sidebar is optional */ }
    if (!live()) return;
    const pick = $("#thread-list");
    pick.hidden = !threads.length;
    pick.innerHTML = threads.map((t) => `<a href="#/chat/${esc(t.id)}" aria-current="${t.id === state.threadId}">${esc(t.title)}</a>`).join("");
  }

  async function send() {
    const text = input.value.trim();
    if (!text || busy) return;
    busy = true;
    lastQuestion = text;
    if ($(".starter", list)) list.innerHTML = "";
    list.insertAdjacentHTML("beforeend", messageHTML({ role: "user", content: text }));
    input.value = "";
    autosize();
    $("#attach-note").hidden = true;
    attached = null;
    list.insertAdjacentHTML("beforeend", `<div class="msg ai" id="thinking"><span class="avatar" aria-hidden="true">${mark()}</span><div class="body"><span class="thinking" aria-label="Thinking"><span></span><span></span><span></span></span></div></div>`);
    scroll();
    try {
      const r = await api("/chat", { method: "POST", body: { message: text, thread_id: state.threadId } });
      if (!live()) { toast("Reply ready in Chat"); return; }
      const wasNew = !state.threadId;
      state.threadId = r.thread_id;
      $("#thinking")?.remove();
      list.insertAdjacentHTML("beforeend", messageHTML(r.message));
      if (wasNew) { history.replaceState(null, "", `#/chat/${r.thread_id}`); loadThreads(); }
    } catch (err) {
      if (!live()) { toast(err.message, { error: true }); return; }
      $("#thinking")?.remove();
      list.insertAdjacentHTML("beforeend", messageHTML({ role: "assistant", content: err.message, error: true, retry: err.status !== 409 }));
      if (err.status === 409) { await loadStatus(); }
    } finally {
      busy = false;
      scroll();
      focusInput();
    }
  }
  list.addEventListener("click", (e) => {
    if (e.target.closest("[data-retry]")) { e.target.closest(".msg").remove(); input.value = lastQuestion; send(); }
  });
  $("#composer").addEventListener("submit", (e) => { e.preventDefault(); send(); });

  loadThreads();
  if (state.threadId) {
    try {
      const t = await api(`/threads/${encodeURIComponent(state.threadId)}`);
      if (!live()) return;
      list.innerHTML = t.messages.map(messageHTML).join("") || "";
      if (!t.messages.length) showStarter();
      scroll();
    } catch (err) {
      toast(err.message, { error: true });
      state.threadId = null;
      showStarter();
    }
  } else showStarter();

  if (state.pendingAsk) {
    input.value = state.pendingAsk;
    state.pendingAsk = "";
    send();
  } else focusInput();
}

// ---------- Settings -----------------------------------------------------
async function renderSettings() {
  const live = current();
  const s = await loadStatus();
  if (!live()) return;
  if (!s) { app.innerHTML = `<div class="page"><div class="card">Can't reach the app.</div></div>`; return; }
  app.innerHTML = `<div class="page">
    <div class="page-head"><div><h1 class="page-title">Settings</h1></div></div>
    <div class="stack">
      <form class="card stack" id="you">
        <div class="card-head" style="margin:0"><h2>You</h2><span class="tint">${icon("sun")}</span></div>
        <div class="me-card">
          <span class="me-photo" id="me-photo">${s.photo ? `<img src="${esc(s.photo)}" alt="Your photo">` : esc(firstName().charAt(0).toUpperCase())}</span>
          <div class="me-info">
            <b>${esc(s.name)}</b>
            <span class="muted small">${esc(s.email)}</span>
            <div class="row" style="gap:8px;margin-top:10px">
              <button class="btn sm" type="button" id="photo-change">${s.photo ? "Change photo" : "Add a photo"}</button>
              ${s.photo ? `<button class="btn ghost sm" type="button" id="photo-edit">Edit</button><button class="btn danger sm" type="button" id="photo-remove">Remove</button>` : ""}
            </div>
          </div>
        </div>
        <label class="field"><span>Your name</span><input class="input" name="name" value="${esc(s.name)}" maxlength="40" required></label>
        <div><button class="btn">Save</button></div>
      </form>

      ${s.auth ? `<section class="card stack"><div class="card-head" style="margin:0"><h2>Sign out</h2><span class="tint">${icon("arrow")}</span></div><p class="muted small" style="margin:0">Signed in on this device.</p><div><button class="btn ghost" id="sign-out">Sign out</button></div></section>` : ""}
    </div></div>`;

  $("#photo-change")?.addEventListener("click", async () => {
    const file = await pickFile("image/*");
    if (file) openPhotoEditor(file, () => renderSettings());
  });
  $("#photo-edit")?.addEventListener("click", () => openPhotoEditor(s.photo, () => renderSettings()));
  $("#photo-remove")?.addEventListener("click", async () => {
    if (!(await confirmDelete("Remove your photo?", "You can add a new one any time.", "Remove"))) return;
    try { await api("/profile/photo", { method: "DELETE" }); await loadStatus(); toast("Photo removed"); renderSettings(); } catch (err) { toast(err.message, { error: true }); }
  });
  $("#sign-out")?.addEventListener("click", async () => { await api("/logout", { method: "POST" }).catch(() => {}); location.href = "/login"; });

  $("#you").addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await api("/settings", { method: "PUT", body: { name: e.target.name.value.trim() } }); await loadStatus(); toast("Saved"); } catch (err) { toast(err.message, { error: true }); }
  });
}

// ---------- Profile photo editor -----------------------------------------
// Pick a picture, drag it into place, zoom, save. The server turns it into a small square JPEG.
function openPhotoEditor(source, done) {
  const dlg = $("#photo-dialog");
  const cvs = $("#photo-canvas");
  const ctx = cvs.getContext("2d");
  const zoom = $("#photo-zoom");
  const S = cvs.width;
  const img = new Image();
  let url = null;
  const st = { zoom: 1, x: 0, y: 0 }; // x/y: how far the picture is moved from centre, in canvas pixels

  const cover = () => Math.max(S / img.naturalWidth, S / img.naturalHeight) * st.zoom;
  const clamp = () => {
    const mx = Math.max(0, (img.naturalWidth * cover() - S) / 2), my = Math.max(0, (img.naturalHeight * cover() - S) / 2);
    st.x = Math.min(mx, Math.max(-mx, st.x));
    st.y = Math.min(my, Math.max(-my, st.y));
  };
  const draw = (target = ctx, size = S) => {
    const k = size / S;
    target.fillStyle = "#fff";
    target.fillRect(0, 0, size, size);
    const w = img.naturalWidth * cover() * k, h = img.naturalHeight * cover() * k;
    target.drawImage(img, (size - w) / 2 + st.x * k, (size - h) / 2 + st.y * k, w, h);
  };
  const paint = () => { clamp(); draw(); };

  img.onload = () => { st.zoom = 1; st.x = 0; st.y = 0; zoom.value = "1"; paint(); dlg.showModal(); };
  img.onerror = () => toast("I couldn't open that picture. Try a JPG or PNG.", { error: true });
  if (source instanceof File) { url = URL.createObjectURL(source); img.src = url; } else img.src = source;

  let drag = null;
  cvs.onpointerdown = (e) => { drag = { x: e.clientX, y: e.clientY, sx: st.x, sy: st.y }; cvs.setPointerCapture(e.pointerId); cvs.classList.add("grabbing"); };
  cvs.onpointermove = (e) => { if (!drag) return; const r = S / cvs.getBoundingClientRect().width; st.x = drag.sx + (e.clientX - drag.x) * r; st.y = drag.sy + (e.clientY - drag.y) * r; paint(); };
  cvs.onpointerup = cvs.onpointercancel = () => { drag = null; cvs.classList.remove("grabbing"); };
  zoom.oninput = () => { st.zoom = Number(zoom.value); paint(); };

  const close = () => { dlg.close(); if (url) URL.revokeObjectURL(url); };
  $("#photo-cancel").onclick = close;
  $("#photo-save").onclick = async () => {
    const out = document.createElement("canvas");
    out.width = out.height = 640;
    draw(out.getContext("2d"), 640);
    const blob = await new Promise((r) => out.toBlob(r, "image/jpeg", 0.9));
    const form = new FormData();
    form.append("file", blob, "photo.jpg");
    try {
      await api("/profile/photo", { method: "POST", form });
      close();
      await loadStatus();
      toast("Photo saved");
      done?.();
    } catch (err) { toast(err.message, { error: true }); }
  };
}

// ---------- start --------------------------------------------------------
let lastY = 0;
window.addEventListener("scroll", () => {
  const y = window.scrollY, bar = $(".tabbar");
  if (!bar) return;
  bar.classList.toggle("tuck", y > lastY + 6 && y > 140 && document.body.dataset.page !== "chat");
  if (y < lastY - 6 || y < 140) bar.classList.remove("tuck");
  lastY = y;
}, { passive: true });
window.addEventListener("hashchange", route);
loadStatus().then(route);
