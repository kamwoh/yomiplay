// Ring buffer of interleaved stereo float samples; reports its fill level (ms) to the page.
// Playback starts (and restarts after an underrun) only once TARGET_MS is buffered, so small network
// jitter never empties it; if the buffer grows past MAX_MS (latency), the oldest samples are dropped
// back down to TARGET_MS.
const TARGET_MS = 80;
const MAX_MS = 250;

class PcmPlayer extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buf = new Float32Array(sampleRate * 2);  // 1 s stereo
    this.read = 0; this.write = 0; this.count = 0; this.ticks = 0;
    this.playing = false;
    this.target = Math.round(sampleRate * TARGET_MS / 1000) * 2;  // in interleaved samples
    this.max = Math.round(sampleRate * MAX_MS / 1000) * 2;
    this.port.onmessage = (e) => this.push(e.data);
  }
  drop(n) { this.read = (this.read + n) % this.buf.length; this.count -= n; }
  push(s) {  // Int16Array interleaved
    for (let i = 0; i < s.length; i++) {
      if (this.count >= this.buf.length) this.drop(2);
      this.buf[this.write] = s[i] / 32768; this.write = (this.write + 1) % this.buf.length; this.count++;
    }
    if (this.count > this.max) this.drop(this.count - this.target);
  }
  process(_inputs, outputs) {
    const [l, r] = outputs[0];
    if (!this.playing && this.count >= this.target) this.playing = true;
    if (this.playing && this.count < l.length * 2) this.playing = false;  // underrun: wait for a full prebuffer
    for (let i = 0; i < l.length; i++) {
      if (this.playing) {
        l[i] = this.buf[this.read]; r[i] = this.buf[(this.read + 1) % this.buf.length];
        this.drop(2);
      } else { l[i] = 0; r[i] = 0; }
    }
    if (++this.ticks % 32 === 0) this.port.postMessage({ fillMs: (this.count / 2) / sampleRate * 1000 });
    return true;
  }
}
registerProcessor("pcm-player", PcmPlayer);
