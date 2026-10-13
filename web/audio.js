// Starts audio on the first user gesture (browser rule) and forwards AUD1 payloads to the worklet.
export function createAudio(onFill) {
  let ctx = null, node = null;
  return {
    async start() {
      if (node) { if (ctx.state === "suspended") await ctx.resume(); return; }
      const c = new AudioContext({ sampleRate: 44100 });
      try {
        await c.audioWorklet.addModule("/static/audio-worklet.js");
        const n = new AudioWorkletNode(c, "pcm-player", { outputChannelCount: [2] });
        n.port.onmessage = (e) => onFill(e.data.fillMs);
        n.connect(c.destination);
        if (c.state === "suspended") await c.resume();
        ctx = c; node = n;
      } catch (err) {
        c.close().catch(() => {});  // leave the audio unstarted so a later gesture can retry
        throw err;
      }
    },
    push(buf) {
      if (!node) return;
      node.port.postMessage(new Int16Array(buf.slice(12)));
    },
    get running() { return !!ctx; },
  };
}
