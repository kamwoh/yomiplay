// Speak Japanese text with the browser's speechSynthesis (needs a ja-JP voice installed).
const synth = window.speechSynthesis;
const buttons = new Set();
const NO_VOICE = "No Japanese voice is available in this browser. Install a Japanese text-to-speech voice in your system settings.";

function japaneseVoice() {
  if (!synth) return null;
  const voices = synth.getVoices();
  return voices.find((v) => /^ja[-_]JP$/i.test(v.lang)) || voices.find((v) => /^ja/i.test(v.lang)) || null;
}

function refresh() {
  const ok = !!japaneseVoice();
  for (const b of buttons) {
    if (!b.isConnected) { buttons.delete(b); continue; }
    b.disabled = !ok;
    b.parentElement.title = ok ? "Speak" : NO_VOICE;
  }
}
if (synth) synth.addEventListener("voiceschanged", refresh);

// A speaker button; `getText` is read at click time so an edited line is spoken as edited.
export function speakButton(getText) {
  const wrap = document.createElement("span");
  wrap.className = "speak-wrap";
  const b = document.createElement("button");
  b.type = "button"; b.className = "speak"; b.textContent = "🔊"; b.setAttribute("aria-label", "Speak");
  wrap.append(b);
  b.onclick = () => {
    const voice = japaneseVoice();
    const text = (getText() || "").trim();
    if (!voice || !text) return;
    synth.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "ja-JP"; u.voice = voice;
    synth.speak(u);
  };
  buttons.add(b);
  refresh();  // after insertion into the DOM the wrapper title is already set; harmless before
  wrap.title = japaneseVoice() ? "Speak" : NO_VOICE;
  b.disabled = !japaneseVoice();
  return wrap;
}
