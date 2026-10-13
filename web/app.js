import { createVideo } from "./video.js";
import { createAudio } from "./audio.js";
import { createInput } from "./input.js";
import { createOverlay } from "./overlay.js";
import { mountChat } from "./chat.js";
import { mountWords } from "./words.js";
import { mountControls } from "./controls.js";
import { page } from "./state.js";

const $ = (id) => document.getElementById(id);
const wsUrl = (p) => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${p}`;
const video = createVideo($("screen"));
const overlay = createOverlay({ layer: $("overlay"), video, toggle: $("overlay-on"), select: $("overlay-mode"), focusTarget: $("screen") });
let mediaWs = null;
const audio = createAudio((ms) => mediaWs?.readyState === 1 && mediaWs.send(JSON.stringify({ type: "audio_fill", ms })));

function showError(msg) { const e = $("error"); e.textContent = msg; e.hidden = !msg; }
export function isTyping() { const a = document.activeElement; return !!a && (a.tagName === "INPUT" || a.tagName === "TEXTAREA" || a.tagName === "SELECT" || a.isContentEditable); }

async function refreshStatus() {
  const s = await (await fetch("/api/status")).json();
  $("game").textContent = s.serial ? `${s.game} · ${s.serial}` : s.game;
  $("btn-pause").textContent = s.paused ? "Resume" : "Pause";
  return s;
}

function connectMedia() {
  mediaWs = new WebSocket(wsUrl("/ws/media"));
  mediaWs.binaryType = "arraybuffer";
  mediaWs.onmessage = (e) => {
    if (typeof e.data === "string") {
      const m = JSON.parse(e.data);
      if (m.type === "status") $("btn-pause").textContent = m.paused ? "Resume" : "Pause";
      if (m.type === "emulator_failed") showError(`Emulator stopped: ${m.message}. Restart yomiplay serve to continue.`);
      return;
    }
    const tag = new TextDecoder().decode(new Uint8Array(e.data, 0, 4));
    if (tag === "VID1") { $("state").textContent = `frame ${video.draw(e.data)}`; overlay.onFrame(); }
    else if (tag === "AUD1") audio.push(e.data);
  };
  mediaWs.onclose = () => { if (page.stopped) return; showError("Disconnected. Reconnecting…"); setTimeout(connectMedia, 1000); };
  mediaWs.onopen = () => showError("");
}

// Button socket: reconnects like the media socket and re-sends the held buttons, since the server
// releases every button when a socket goes away.
let inputWs = null, heldMask = 0;
const sendMask = () => inputWs?.readyState === 1 && inputWs.send(JSON.stringify({ type: "buttons", port: 0, mask: heldMask }));
function connectInput() {
  inputWs = new WebSocket(wsUrl("/ws/input"));
  inputWs.onopen = sendMask;
  inputWs.onclose = () => { if (!page.stopped) setTimeout(connectInput, 1000); };
}

async function renderSlots() {
  const have = new Map((await (await fetch("/api/states")).json()).map((s) => [s.slot, s]));
  const box = $("slots"); box.textContent = "";
  for (let slot = 1; slot <= 9; slot++) {
    const group = document.createElement("span"); group.className = "slot";
    const num = document.createElement("b"); num.textContent = String(slot);
    const save = document.createElement("button");
    save.textContent = "Save"; save.setAttribute("aria-label", `Save slot ${slot}`);
    save.onclick = async () => { await fetch(`/api/states/${slot}`, { method: "POST" }); renderSlots(); };
    group.append(num, save);
    if (have.has(slot)) {
      const load = document.createElement("button");
      load.textContent = "Load"; load.setAttribute("aria-label", `Load slot ${slot}`);
      load.title = `Saved ${have.get(slot).saved_at}`;
      load.onclick = async () => {
        const r = await fetch(`/api/states/${slot}/load`, { method: "POST" });
        if (!r.ok) showError((await r.json()).detail);
      };
      group.append(load);
    }
    box.append(group);
  }
}

// Sound starts on the first user gesture anywhere on the page (browsers refuse audio before one).
function autoStartSound() {
  let starting = false;
  const note = (msg) => { $("sound-note-text").textContent = msg; $("sound-note").hidden = !msg; };
  const start = async () => {
    if (starting || audio.running) return;
    starting = true;
    try { await audio.start(); note(""); } catch (err) { note(`Sound could not start (${err.message}).`); }
    starting = false;
  };
  const once = () => { window.removeEventListener("pointerdown", once, true); window.removeEventListener("keydown", once, true); start(); };
  window.addEventListener("pointerdown", once, true);
  window.addEventListener("keydown", once, true);
  $("btn-sound").onclick = start;
}

// Reset and Quit ask for confirmation inside the page (no alert()).
function setupConfirm() {
  let action = null;
  const close = () => { action = null; $("confirm").hidden = true; };
  const ask = (text, fn) => { action = fn; $("confirm-text").textContent = text; $("confirm").hidden = false; $("confirm-no").focus(); };
  $("confirm-no").onclick = () => { close(); $("screen").focus(); };
  $("confirm-yes").onclick = async () => { const fn = action; close(); await fn(); };
  $("btn-reset").onclick = () => ask("Restart the game from the beginning? Unsaved progress is lost.", async () => {
    try {
      const r = await fetch("/api/reset", { method: "POST" });
      if (!r.ok) throw new Error(r.status);
      showError("");
    } catch (err) { showError(`Could not reset: ${err.message}`); }
    $("screen").focus();
  });
  $("btn-quit").onclick = () => ask("Stop Yomiplay? The game ends and the server shuts down.", async () => {
    try {
      const r = await fetch("/api/quit", { method: "POST" });
      if (!r.ok) throw new Error(r.status);
    } catch (err) {  // a network error right after the request usually means the server is already gone
      if (!(err instanceof TypeError)) { showError(`Could not quit: ${err.message}`); return; }
    }
    page.stopped = true;
    mediaWs?.close(); inputWs?.close();
    $("stopped").hidden = false;
  });
}

async function main() {
  const s = await refreshStatus();
  connectInput();
  let initial = { keys: s.keys };
  try { initial = await (await fetch("/api/controls")).json(); } catch { /* fall back to the status key map */ }
  const input = createInput(initial, (mask) => { heldMask = mask; sendMask(); }, isTyping);
  connectMedia();
  renderSlots();
  autoStartSound();
  setupConfirm();
  $("btn-pause").onclick = async () => {
    const paused = $("btn-pause").textContent === "Pause";
    await fetch(paused ? "/api/pause" : "/api/resume", { method: "POST" });
    refreshStatus();
  };
  const words = mountWords();
  let controls = null;
  mountControls(input).then((c) => { controls = c; }).catch((err) => showError(`Controls unavailable: ${err.message}`));
  const tabs = { chat: [$("tab-chat"), $("panel-chat")], words: [$("tab-words"), $("panel-words")],
    controls: [$("tab-controls"), $("panel-controls")] };
  for (const [name, [tab]] of Object.entries(tabs)) {
    tab.onclick = () => {
      for (const [n, [t, panel]] of Object.entries(tabs)) { t.setAttribute("aria-selected", String(n === name)); panel.hidden = n !== name; }
      if (name === "words") words.refresh();
      if (name === "controls") controls?.refresh(); else controls?.leave();
    };
  }
  try {
    await mountChat({ onAnswerStart: () => refreshStatus(), onAnswerEnd: () => refreshStatus(), onCard: (card, force) => overlay.show(card, force) });
  } catch (err) {
    showError(`Chat is unavailable: ${err.message}`);
  }
  $("screen").focus();
}
main();
