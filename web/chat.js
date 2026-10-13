// Chat panel: ask, explain, live progress, study cards (editable line, romaji, speech, star chips), history across sessions, cancel, continue.
import { page } from "./state.js";
import { speakButton } from "./speech.js";

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const wsUrl = (p) => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${p}`;
const LANG = { en: "EN", zh: "ZH", "zh-Hant": "ZH", ms: "MS", ja: "JA", ko: "KO" };
const JSON_POST = { method: "POST", headers: { "content-type": "application/json" } };

export async function mountChat(opts) {
  const msgs = $("messages");
  const profiles = await (await fetch("/api/profiles")).json();
  const sel = $("profile");
  for (const p of profiles.profiles) {
    const o = el("option", null, p.title); o.value = p.name; sel.append(o);
  }
  try { sel.value = localStorage.getItem("yomiplay.profile") || profiles.default; } catch { sel.value = profiles.default; }
  if (!sel.value) sel.value = profiles.default;
  sel.onchange = () => { try { localStorage.setItem("yomiplay.profile", sel.value); } catch {} };

  let ws, bot = null, busy = false;
  const setBusy = (b) => {
    busy = b; $("btn-cancel").hidden = !b; $("btn-send").disabled = b; $("btn-explain").disabled = b;
    if (!b) { clearStatus(); $("btn-continue").hidden = false; opts.onAnswerEnd(); }
  };
  const scroll = () => { msgs.scrollTop = msgs.scrollHeight; };

  // Live status under the last message: stage text plus elapsed seconds. Removed when the turn is done.
  let statusEl = null, statusText = "", statusTimer = null, statusStart = 0;
  const add = (node) => { if (statusEl) msgs.insertBefore(node, statusEl); else msgs.append(node); };
  const paintStatus = () => {
    if (statusEl) statusEl.textContent = `${statusText} · ${Math.round((Date.now() - statusStart) / 1000)} s`;
  };
  const setStatus = (text) => { statusText = text; if (statusEl) { paintStatus(); scroll(); } };
  const startStatus = (text) => {
    clearStatus();
    statusEl = el("div", "msg-meta status-line", ""); statusEl.setAttribute("role", "status");
    msgs.append(statusEl); statusStart = Date.now(); setStatus(text);
    statusTimer = setInterval(paintStatus, 500);
  };
  function clearStatus() {
    if (statusTimer) clearInterval(statusTimer);
    statusTimer = null; statusEl?.remove(); statusEl = null;
  }
  let turnKind = "ask";  // wording of the progress line: "study card" for Explain, "answer" for Ask
  const noun = () => (turnKind === "explain" ? "study card" : "answer");

  async function sessionWords() {
    return new Map((await (await fetch("/api/words?filter=session&sort=recent")).json()).map((w) => [w.lemma, w]));
  }

  async function renderCard(m, known = null, readOnly = false) {
    const card = el("div", "card");
    m.card.lines.forEach((line, i) => {
      const src = el("div", "src", line.source);
      if (readOnly) { src.title = "From an earlier session (read-only)"; }
      else { src.contentEditable = "true"; src.spellcheck = false; src.title = "Edit if the transcription is wrong, then press Enter"; }
      src.onkeydown = async (e) => {
        if (e.key !== "Enter" || e.isComposing || e.keyCode === 229) return;
        e.preventDefault(); src.blur();
        try {
          const r = await fetch(`/api/cards/${m.card_id}/lines/${i}`, { ...JSON_POST, body: JSON.stringify({ text: src.textContent.trim() }) });
          src.title = r.ok ? "Words updated" : `Could not update this line: ${(await r.json()).detail || r.status}`;
        } catch { src.title = "Could not update this line: server not reachable"; }
      };
      const head = el("div", "line-head");
      head.append(src, speakButton(() => src.textContent));
      card.append(head);
      if (line.reading) card.append(el("div", "reading", line.reading));
      if (line.romaji) card.append(el("div", "romaji", line.romaji));
      const tr = el("div", "tr");
      for (const [lang, text] of Object.entries(line.translations)) { tr.append(el("b", null, LANG[lang] || lang), el("span", null, text)); }
      card.append(tr);
      if (line.note) card.append(el("div", "msg-meta", line.note));
    });
    if (m.card.words.length) {
      const chips = el("div", "chips");
      const ids = new Map();
      if (known) for (const [k, v] of known) ids.set(k, v);
      else {
        try { for (const [k, v] of await sessionWords()) ids.set(k, v); } catch { /* chips still render, without counts */ }
      }
      for (const w of m.card.words) {
        const known = ids.get(w.word);
        const chipBox = el("span", "chip-box");
        const chip = el("button", "chip", `${known?.starred ? "★" : "☆"} ${w.word} ${w.reading}${w.romaji ? ` (${w.romaji})` : ""}${known ? ` · seen ${known.seen_count}×` : ""}`);
        chip.type = "button"; chip.setAttribute("aria-pressed", known?.starred ? "true" : "false");
        chip.title = Object.values(w.meanings).join(" / ");
        chip.onclick = async () => {
          if (!known) { chip.title = "This word was not found in the line; edit the line to re-split it"; return; }
          const on = chip.getAttribute("aria-pressed") !== "true";
          try {
            const r = await fetch(`/api/words/${known.id}/star`, { ...JSON_POST, body: JSON.stringify({ starred: on }) });
            if (!r.ok) throw new Error(r.status);
          } catch { chip.title = "Could not update the star. Try again."; return; }
          chip.setAttribute("aria-pressed", on ? "true" : "false");
          chip.textContent = chip.textContent.replace(/^[☆★]/, on ? "★" : "☆");
        };
        chipBox.append(chip, speakButton(() => w.word));
        chips.append(chipBox);
      }
      card.append(chips);
    }
    if (!readOnly && m.card.lines.some((l) => Array.isArray(l.box))) {
      const show = el("button", "speak", "Show on screen");
      show.type = "button"; show.title = "Show this card's translation on the game screen";
      show.onclick = () => opts.onCard?.(m.card, true);
      card.append(show);
    }
    return card;
  }

  function connect() {
    ws = new WebSocket(wsUrl("/ws/chat"));
    // Handlers run one at a time so a card (async) cannot be overtaken by the "done" that follows it.
    let queue = Promise.resolve();
    ws.onmessage = (e) => { queue = queue.then(() => handle(JSON.parse(e.data))).catch((err) => console.error(err)); };
    ws.onclose = () => {
      queue = queue.then(() => { if (busy && !page.stopped) { bot = null; add(el("div", "msg-err", "Chat connection lost. Reconnecting…")); setBusy(false); } });
      if (!page.stopped) setTimeout(connect, 1000);
    };
  }
  async function handle(m) {
    if (m.type === "progress") {
      if (!busy) return;
      setStatus(m.stage === "started" ? "Claude is reading the screen…" : `Writing the ${noun()}… ${m.chars} characters`);
    }
    else if (m.type === "delta") { if (!bot) { bot = el("div", "msg-bot", ""); add(bot); } bot.textContent += m.text; }
    else if (m.type === "final") { if (!bot) { bot = el("div", "msg-bot", m.text); add(bot); } }
    else if (m.type === "card") { add(await renderCard(m)); opts.onCard?.(m.card); }
    else if (m.type === "usage") { add(el("div", "msg-meta", `${m.latency_s}s · ${m.model}`)); }
    else if (m.type === "error") { add(el("div", "msg-err", `${m.kind}: ${m.message}`)); }
    else if (m.type === "done") { bot = null; setBusy(false); }
    scroll();
  }
  connect();

  // Chat history: this session and earlier sessions of the same game. Older pages load at the top.
  const sessionLabel = (name, current) => {
    if (name === current) return "This session";
    const m = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/.exec(name);
    if (!m) return "Earlier session";
    const d = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
    return `Earlier session · ${d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}`;
  };
  const divider = (name, current) => { const d = el("div", "msg-divider", sessionLabel(name, current)); d.dataset.session = name; return d; };
  let before = null, loadingOlder = false, olderBtn = null, olderFailed = false;

  async function historyPage(cursor) {
    const q = new URLSearchParams({ limit: "50" });
    if (cursor) q.set("before", cursor);
    const r = await fetch(`/api/history?${q}`);
    if (!r.ok) throw new Error(`history ${r.status}`);
    const page = await r.json();
    const words = new Map();  // session -> its words, for the chips' counts and stars
    for (const name of new Set(page.entries.filter((h) => h.kind === "explain").map((h) => h.session))) {
      try {
        const list = await (await fetch(`/api/words?filter=session&sort=recent&session=${encodeURIComponent(name)}`)).json();
        words.set(name, new Map(list.map((w) => [w.lemma, w])));
      } catch { /* chips render without counts */ }
    }
    const nodes = [];
    const grouped = cursor || page.before || page.entries.some((h) => h.session !== page.session);
    let last = null;
    for (const h of page.entries) {
      if (grouped && h.session !== last) nodes.push(divider(h.session, page.session));
      last = h.session;
      if (h.kind === "ask") {
        nodes.push(el("div", "msg-user", h.question || ""), el("div", "msg-bot", h.answer || ""));
      } else if (h.kind === "explain" && h.card) {
        nodes.push(el("div", "msg-user", "Explain this screen"));
        nodes.push(await renderCard(h, words.get(h.session) || new Map(), h.session !== page.session));
      }
    }
    return { nodes, before: page.before, last, session: page.session };
  }
  function setOlderButton() {
    if (before && !olderBtn) {
      olderBtn = el("button", "speak older", "Show earlier messages");
      olderBtn.type = "button"; olderBtn.onclick = () => { olderFailed = false; loadOlder(); };
      msgs.prepend(olderBtn);
    } else if (!before && olderBtn) { olderBtn.remove(); olderBtn = null; }
  }
  async function loadOlder() {
    if (!before || loadingOlder) return;
    loadingOlder = true;
    try {
      const page = await historyPage(before);
      const anchor = olderBtn ? olderBtn.nextSibling : msgs.firstChild;
      // the same session can continue on the page below: keep one divider, at the top of the group
      if (anchor?.classList?.contains("msg-divider") && anchor.dataset.session === page.last) anchor.remove();
      const keep = msgs.scrollHeight - msgs.scrollTop;
      const next = olderBtn ? olderBtn.nextSibling : msgs.firstChild;
      for (const n of page.nodes) msgs.insertBefore(n, next);
      msgs.scrollTop = msgs.scrollHeight - keep;  // stay at the message you were reading
      before = page.before;
      setOlderButton();
      if (olderBtn) olderBtn.textContent = "Show earlier messages";
    } catch {
      olderFailed = true;  // stop loading on scroll; the button retries
      if (olderBtn) olderBtn.textContent = "Could not load earlier messages. Try again";
    }
    finally { loadingOlder = false; }
  }
  msgs.addEventListener("scroll", () => { if (msgs.scrollTop < 40 && !olderFailed) loadOlder(); });
  try {
    const page = await historyPage(null);
    for (const n of page.nodes) add(n);
    // new messages of this session go under their own divider when older history is above them
    if (page.nodes.length && page.last !== page.session) add(divider(page.session, page.session));
    before = page.before;
    setOlderButton();
    scroll();
  } catch { /* no history: start with an empty chat */ }
  for (const problem of profiles.problems || []) add(el("div", "msg-err", `Profile skipped: ${problem}`));

  const send = (payload, label) => {
    if (busy) return;
    if (!ws || ws.readyState !== 1) { add(el("div", "msg-err", "Chat is reconnecting… try again in a moment.")); scroll(); return; }
    add(el("div", "msg-user", label));
    turnKind = payload.type;
    $("btn-continue").hidden = true; setBusy(true); opts.onAnswerStart();
    startStatus("Capturing screen…"); scroll();
    ws.send(JSON.stringify({ chat_id: "main", profile: sel.value, ...payload }));
  };
  $("composer").onsubmit = (e) => {
    e.preventDefault();
    const q = $("question").value.trim(); if (!q) return;
    $("question").value = "";
    send({ type: "ask", text: q, with_screen: true }, q);
  };
  $("btn-explain").onclick = () => send({ type: "explain" }, "Explain this screen");
  $("btn-cancel").onclick = () => ws.readyState === 1 && ws.send(JSON.stringify({ type: "cancel", chat_id: "main" }));
  $("btn-continue").onclick = async () => { await fetch("/api/resume", { method: "POST" }); $("btn-continue").hidden = true; opts.onAnswerEnd(); $("screen").focus(); };
}
