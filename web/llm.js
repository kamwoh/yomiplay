// Model and thinking picker for the Chat tab. The server keeps the choice (llm.json).
const MODEL_LABEL = { opus: "Opus", sonnet: "Sonnet", haiku: "Haiku", fable: "Fable" };
const THINKING_LABEL = { off: "Off", low: "Low", medium: "Medium", high: "High", xhigh: "Extra high", max: "Max" };

const opt = (value, label) => { const o = document.createElement("option"); o.value = value ?? ""; o.textContent = label; return o; };

function fill(sel, values, labels, current) {
  sel.replaceChildren(...values.map((v) => opt(v, v == null ? "Default" : labels[v] || v)));
  if (current != null && !values.includes(current)) sel.append(opt(current, current)); // a full model id from config.toml
  sel.value = current ?? "";
}

export async function mountLLMPickers(onError) {
  const info = await (await fetch("/api/llm")).json();
  for (const target of ["chat"]) {
    const box = document.getElementById(`llm-${target}`);
    if (!box || !info[target]) continue;
    const model = box.querySelector(".llm-model"), thinking = box.querySelector(".llm-thinking");
    fill(model, info.models, MODEL_LABEL, info[target].model);
    fill(thinking, info.thinking, THINKING_LABEL, info[target].thinking);
    const hint = () => {
      thinking.title = thinking.value === "off" && (model.value === "opus" || model.value === "")
        ? "Opus can still think a little with Off. Use Low for the fastest Opus." : "";
    };
    hint();
    let applied = { model: model.value, thinking: thinking.value };
    const save = async () => {
      hint();
      const body = { target, model: model.value || null, thinking: thinking.value || null };
      try {
        const r = await fetch("/api/llm", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
        if (!r.ok) {
          let detail = r.statusText;
          try { const d = (await r.json()).detail; detail = typeof d === "string" ? d : JSON.stringify(d); } catch {}
          throw new Error(detail);
        }
        applied = { model: model.value, thinking: thinking.value };
        window.dispatchEvent(new CustomEvent("yomiplay:llm-change", { detail: { target } }));
      } catch (err) {
        model.value = applied.model; thinking.value = applied.thinking; hint();  // show what is really in effect
        onError(`Could not change the model: ${err.message}`);
      }
    };
    model.onchange = save; thinking.onchange = save;
  }
}
