// Keyboard and Gamepad API -> PS1 button bitmask, sent on change. Bindings can be replaced live
// (setBindings) and a single key or gamepad press can be captured for the Controls tab (capture).
export const BIT = { CROSS: 0, SQUARE: 1, SELECT: 2, START: 3, UP: 4, DOWN: 5, LEFT: 6, RIGHT: 7,
  CIRCLE: 8, TRIANGLE: 9, L: 10, R: 11, L2: 12, R2: 13, L3: 14, R3: 15 };
// Standard gamepad layout index -> PS1 button name (used only if the server sends no pad map)
export const DEFAULT_PAD = { 0: "CROSS", 1: "CIRCLE", 2: "SQUARE", 3: "TRIANGLE", 4: "L", 5: "R", 6: "L2", 7: "R2",
  8: "SELECT", 9: "START", 10: "L3", 11: "R3", 12: "UP", 13: "DOWN", 14: "LEFT", 15: "RIGHT" };

export function createInput(initial, send, isTyping) {
  let keyMap = initial.keys || {}, padMap = initial.pad || DEFAULT_PAD;
  let keys = 0, pad = 0, last = -1;
  let capturing = null;  // { resolve } while the Controls tab waits for one key or gamepad button
  let prevPressed = new Set();
  const flush = () => { const m = keys | pad; if (m !== last) { last = m; send(m); } };
  const finish = (result) => { const c = capturing; capturing = null; if (c) c.resolve(result); };

  // Capture phase and registered first, so a captured key never reaches the game or the page.
  window.addEventListener("keydown", (e) => {
    if (!capturing) return;
    e.preventDefault(); e.stopPropagation();
    if (e.repeat) return;
    finish(e.code === "Escape" ? null : { type: "key", code: e.code });
  }, true);

  const onKey = (down) => (e) => {
    if (capturing && down) return;
    if (isTyping()) return;
    const name = keyMap[e.code];
    if (!name || !(name in BIT)) return;
    e.preventDefault();
    keys = down ? keys | (1 << BIT[name]) : keys & ~(1 << BIT[name]);
    flush();
  };
  window.addEventListener("keydown", onKey(true));
  window.addEventListener("keyup", onKey(false));
  window.addEventListener("blur", () => { keys = 0; flush(); });

  function pollPads() {
    let m = 0;
    const pressed = new Set();
    for (const gp of navigator.getGamepads ? navigator.getGamepads() : []) {
      if (!gp) continue;
      gp.buttons.forEach((b, i) => {
        if (!b.pressed) return;
        pressed.add(i);
        const name = padMap[i];
        if (name in BIT) m |= 1 << BIT[name];
      });
      const [x, y] = gp.axes;
      if (x < -0.5) m |= 1 << BIT.LEFT; if (x > 0.5) m |= 1 << BIT.RIGHT;
      if (y < -0.5) m |= 1 << BIT.UP; if (y > 0.5) m |= 1 << BIT.DOWN;
    }
    if (capturing) {
      for (const i of pressed) if (!prevPressed.has(i)) { finish({ type: "pad", index: i }); break; }
      m = 0;  // while rebinding, gamepad presses must not drive the game
    }
    prevPressed = pressed;
    pad = m; flush();
    requestAnimationFrame(pollPads);
  }
  requestAnimationFrame(pollPads);

  return {
    setBindings(b) { keyMap = b.keys || {}; padMap = b.pad || DEFAULT_PAD; keys = 0; flush(); },
    // Resolves with {type:"key", code} | {type:"pad", index}, or null when cancelled (Escape or cancelCapture).
    capture() {
      finish(null);
      keys = 0; flush();
      return new Promise((resolve) => { capturing = { resolve }; });
    },
    cancelCapture() { finish(null); },
  };
}
