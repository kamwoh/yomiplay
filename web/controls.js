// Controls tab: the 16 PS1 buttons with their keyboard key and gamepad button; click a binding, then press
// a key or a gamepad button to rebind it. Save stores them on the server and applies them live.
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

const KEY_NAMES = { ArrowUp: "↑", ArrowDown: "↓", ArrowLeft: "←", ArrowRight: "→", Enter: "Enter", Space: "Space",
  ShiftRight: "Right Shift", ShiftLeft: "Left Shift", ControlLeft: "Left Ctrl", ControlRight: "Right Ctrl",
  AltLeft: "Left Alt", AltRight: "Right Alt", Escape: "Esc", Backspace: "Backspace", Tab: "Tab" };
const keyLabel = (code) => KEY_NAMES[code] || code.replace(/^Key/, "").replace(/^Digit/, "").replace(/^Numpad/, "Num ");
const padLabel = (i) => `Button ${i}`;

export async function mountControls(input, opts) {
  const server = await (await fetch("/api/controls")).json();
  const buttons = server.buttons;
  let keys = { ...server.keys }, pad = { ...server.pad };
  let waiting = null, dirty = false;
  const rows = $("controls-rows");

  const keysOf = (b) => Object.entries(keys).filter(([, v]) => v === b).map(([k]) => k);
  const padsOf = (b) => Object.entries(pad).filter(([, v]) => v === b).map(([k]) => k);

  function render() {
    rows.textContent = "";
    for (const b of buttons) {
      const row = el("div", "ctl-row");
      row.append(el("b", "ctl-name", b));
      for (const kind of ["key", "pad"]) {
        const cell = el("button", "ctl-bind");
        cell.type = "button";
        const mine = waiting === b;
        const have = kind === "key" ? keysOf(b).map(keyLabel) : padsOf(b).map(padLabel);
        cell.textContent = mine ? "Press a key or gamepad button… (Esc cancels)" : have.join(" / ") || "—";
        cell.setAttribute("aria-label", `${b} ${kind === "key" ? "keyboard key" : "gamepad button"}: ${have.join(", ") || "none"}`);
        cell.classList.toggle("waiting", mine);
        cell.onclick = () => rebind(b);
        row.append(cell);
      }
      rows.append(row);
    }
    $("controls-save").disabled = !dirty;
  }

  async function rebind(b) {
    if (waiting === b) { input.cancelCapture(); return; }
    waiting = b; render();
    const got = await input.capture();  // a second click elsewhere cancels this one first (resolves null)
    if (waiting === b) waiting = null;
    if (got) {
      if (got.type === "key") {
        for (const k of keysOf(b)) delete keys[k];
        keys[got.code] = b;  // a code already bound to another button is moved: assigning replaces it
      } else {
        for (const i of padsOf(b)) delete pad[i];
        pad[String(got.index)] = b;
      }
      dirty = true; say("");
    }
    render();
  }

  const say = (msg, bad = false) => { const n = $("controls-msg"); n.textContent = msg; n.classList.toggle("msg-err", bad); };

  $("controls-save").onclick = async () => {
    try {
      const r = await fetch("/api/controls", { method: "PUT", headers: { "content-type": "application/json" },
        body: JSON.stringify({ keys, pad }) });
      if (!r.ok) throw new Error((await r.json()).detail || r.status);
      input.setBindings({ keys, pad });
      dirty = false; say("Saved."); render();
    } catch (err) { say(`Could not save: ${err.message}`, true); }
  };
  $("controls-defaults").onclick = () => {
    input.cancelCapture();
    keys = { ...server.defaults.keys }; pad = { ...server.defaults.pad };
    dirty = true; say("Defaults loaded. Press Save to keep them."); render();
  };

  const padLine = $("controls-pad");
  function updatePad() {
    const pads = [...(navigator.getGamepads ? navigator.getGamepads() : [])].filter(Boolean);
    padLine.textContent = pads.length ? `Gamepad: ${pads[0].id}` : "No gamepad detected — press any button on it";
  }
  window.addEventListener("gamepadconnected", updatePad);
  window.addEventListener("gamepaddisconnected", updatePad);
  setInterval(() => { if (!$("panel-controls").hidden) updatePad(); }, 1000);
  updatePad(); render();
  return { refresh: updatePad, leave: () => input.cancelCapture() };
}
