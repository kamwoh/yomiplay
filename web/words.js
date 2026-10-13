// Words tab: every seen word with counts; star filter; click a word to see where it appeared.
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

export function mountWords() {
  async function refresh() {
    const list = $("word-list"); list.textContent = "";
    let rows;
    try {
      const r = await fetch(`/api/words?filter=${$("word-filter").value}&sort=${$("word-sort").value}`);
      if (!r.ok) throw new Error(r.status);
      rows = await r.json();
    } catch { list.append(el("li", "msg-err", "Could not load words.")); return; }
    if (!rows.length) { list.append(el("li", "msg-meta", "No words yet. Press Explain screen while playing.")); return; }
    for (const w of rows) {
      const li = el("li");
      const star = el("button", "chip", w.starred ? "★" : "☆"); star.type = "button";
      star.setAttribute("aria-pressed", w.starred ? "true" : "false");
      star.setAttribute("aria-label", w.starred ? "Unstar word" : "Star word");
      star.onclick = async (e) => {
        e.stopPropagation();
        try {
          const r = await fetch(`/api/words/${w.id}/star`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ starred: !w.starred }) });
          if (!r.ok) throw new Error(r.status);
        } catch { star.title = "Could not update the star. Try again."; star.setAttribute("aria-label", star.title); return; }
        refresh();
      };
      li.append(star, el("strong", null, w.lemma), el("span", "reading", w.reading),
        el("span", null, Object.values(w.meanings).join(" / ")), el("span", "count", `${w.seen_count}×`));
      li.onclick = () => detail(w);
      list.append(li);
    }
  }
  async function detail(w) {
    const box = $("word-detail"); box.textContent = "";
    box.append(el("strong", null, `${w.lemma} (${w.reading})`));
    let encs = [];
    try { encs = await (await fetch(`/api/words/${w.id}/encounters`)).json(); } catch { box.append(el("div", "msg-err", "Could not load where this word appeared.")); return; }
    for (const e of encs) {
      const row = el("div");
      if (e.screenshot) {
        const img = el("img"); img.src = `/api/shots/${encodeURIComponent(e.screenshot)}`; img.alt = "Screen where this word appeared";
        row.append(img);
      }
      row.append(el("div", null, e.line_text), el("div", "msg-meta", `${e.created_at} · ${e.profile_name}`));
      box.append(row);
    }
  }
  $("word-filter").onchange = refresh;
  $("word-sort").onchange = refresh;
  return { refresh };
}
