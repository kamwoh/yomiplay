// Translation overlay: one panel per card line at its screen box (fractions of the screen), over the canvas.
// Hides when the pixels under the boxes change (next line, scene change) or the frame size changes.
const MARGIN = 0.01, CHECK_EVERY = 10, THRESHOLD = 12, MIN_FONT = 9, MAX_FONT = 28;
const MODES = new Set(["reading", "romaji"]);

export function createOverlay({ layer, video, toggle, select, focusTarget }) {
  let card = null, ref = null, tick = 0;
  let enabled = true, mode = "";
  try { enabled = localStorage.getItem("yomiplay.overlay") !== "off"; mode = localStorage.getItem("yomiplay.overlayMode") || ""; } catch {}
  toggle.checked = enabled;

  const textFor = (line) => (MODES.has(mode) ? line[mode] : Object.hasOwn(line.translations || {}, mode) ? line.translations[mode] : "") || "";
  const boxed = () => (card?.lines || []).filter((l) => Array.isArray(l.box) && l.box.length === 4);

  function fillSelect() {
    const langs = [...new Set((card?.lines || []).flatMap((l) => Object.keys(l.translations || {})))];
    const opts = [...langs, "reading", ...(card?.lines?.some((l) => l.romaji) ? ["romaji"] : [])];
    if (!opts.includes(mode)) mode = langs[0] || "reading";  // mode changes but is not saved; the user's choice returns for the next card that has it
    select.textContent = "";
    for (const o of opts) { const e = document.createElement("option"); e.value = o; e.textContent = o; select.append(e); }
    select.value = mode;
    select.disabled = false;
  }

  // Shrink the font until the inner text fits the panel's content box (bounded, so a zero-size panel cannot hang).
  function fit(panel, inner, maxH) {
    const layerH = layer.clientHeight;
    const avail = () => panel.clientHeight - 4;  // minus vertical padding
    let size = Math.max(MIN_FONT, Math.min(MAX_FONT, panel.clientHeight * 0.8));
    panel.style.fontSize = `${size}px`;
    for (let n = 0; n <= MAX_FONT && size > MIN_FONT && (inner.offsetHeight > avail() + 1 || inner.scrollWidth > inner.clientWidth + 1); n++) {
      size -= 1; panel.style.fontSize = `${size}px`;
    }
    if (inner.offsetHeight > avail() + 1) {  // still too long: grow downward, inside the screen
      panel.style.height = "auto"; panel.style.maxHeight = `${maxH * layerH}px`;
    }
  }

  function render() {
    layer.textContent = "";
    if (!enabled || !card || !layer.clientHeight || !layer.clientWidth) return;
    for (const line of boxed()) {
      const text = textFor(line);
      if (!text) continue;
      const [x, y, w, h] = line.box;
      const x0 = Math.max(0, x - MARGIN), y0 = Math.max(0, y - MARGIN);
      const x1 = Math.min(1, x + w + MARGIN), y1 = Math.min(1, y + h + MARGIN);
      const p = document.createElement("div");
      p.className = "ov-panel";
      const t = document.createElement("div"); t.textContent = text; p.append(t);
      Object.assign(p.style, { left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%` });
      layer.append(p);
      fit(p, t, 1 - y0);
    }
  }

  // Copy of the RGB values under each box (every 2nd pixel), to compare later frames against.
  function sample(img) {
    if (!img) return null;
    const out = [];
    for (const line of boxed()) {
      const [x, y, w, h] = line.box;
      const px0 = Math.max(0, Math.floor(x * img.width)), py0 = Math.max(0, Math.floor(y * img.height));
      const px1 = Math.min(img.width, Math.ceil((x + w) * img.width)), py1 = Math.min(img.height, Math.ceil((y + h) * img.height));
      for (let py = py0; py < py1; py += 2) for (let px = px0; px < px1; px += 2) {
        const i = (py * img.width + px) * 4;
        out.push(img.data[i], img.data[i + 1], img.data[i + 2]);
      }
    }
    return { w: img.width, h: img.height, values: out };
  }

  function giveFocusBack() { toggle.blur(); select.blur(); focusTarget?.focus(); }

  function hide() { card = null; ref = null; layer.textContent = ""; }

  toggle.onchange = () => {
    enabled = toggle.checked;
    try { localStorage.setItem("yomiplay.overlay", enabled ? "on" : "off"); } catch {}
    render(); giveFocusBack();
  };
  select.onchange = () => {
    mode = select.value;
    try { localStorage.setItem("yomiplay.overlayMode", mode); } catch {}
    render(); giveFocusBack();
  };
  // Render only changes the layer's children, never its size, so this cannot loop.
  new ResizeObserver(() => render()).observe(layer);

  return {
    show(c, force = false) {
      if (force && !enabled) {
        enabled = true; toggle.checked = true;
        try { localStorage.setItem("yomiplay.overlay", "on"); } catch {}
      }
      card = c; fillSelect();
      if (!boxed().length) { hide(); return; }
      ref = sample(video.pixels()); tick = 0; render();  // ref may be null: taken on the first frame
    },
    hide,
    onFrame() {
      if (!card) return;
      if (!ref) { ref = sample(video.pixels()); tick = 0; return; }
      if (++tick % CHECK_EVERY) return;
      const img = video.pixels();
      if (!img || img.width !== ref.w || img.height !== ref.h) { hide(); return; }
      const now = sample(img).values;
      let diff = 0;
      for (let i = 0; i < now.length; i++) diff += Math.abs(now[i] - ref.values[i]);
      if (now.length && diff / now.length > THRESHOLD) hide();
    },
  };
}
