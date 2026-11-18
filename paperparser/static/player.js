/**
 * Read-aloud player.
 *
 * Streams int16 PCM chunks (each preceded by a JSON header with per-word
 * timings) from the server over a WebSocket and schedules them gaplessly with
 * the Web Audio API. Word highlighting is driven by ``AudioContext.currentTime``
 * so it stays locked to what you actually hear, including pauses and underruns.
 *
 * Events (CustomEvent on this object): ``word`` {index}, ``state`` {state, message},
 * ``end``, ``error`` {message}.
 */
import { api } from "./api.js";

export class ReadAloud extends EventTarget {
  constructor() {
    super();
    /** @type {"idle"|"loading"|"playing"|"paused"} */
    this.state = "idle";
    this.ctx = null;
    this.ws = null;
    this._raf = 0;
    this._tick = this._tick.bind(this);
    this._reset();
  }

  /** Reset all per-stream bookkeeping. */
  _reset() {
    this.timeline = []; // {idx, t0, t1} in AudioContext time
    this.tp = 0;
    this.chunks = []; // {start, end, first, last}
    this.nextStart = 0;
    this.sources = new Set();
    this.pending = null;
    this.ended = false;
    this.current = -1;
    this.donePlayed = 0;
    this.chunkPtr = 0;
    this.lastPos = 0;
  }

  /**
   * Dispatch a CustomEvent.
   * @param {string} type Event name.
   * @param {object} [detail] Event payload.
   */
  _emit(type, detail = {}) {
    this.dispatchEvent(new CustomEvent(type, { detail }));
  }

  /**
   * Change state and notify listeners.
   * @param {"idle"|"loading"|"playing"|"paused"} state New state.
   * @param {string} [message] Optional status text for the UI.
   */
  _setState(state, message = "") {
    this.state = state;
    this._emit("state", { state, message });
  }

  /** Close the socket, silence scheduled audio and stop the animation loop. */
  _teardown() {
    cancelAnimationFrame(this._raf);
    if (this.ws) {
      const ws = this.ws;
      this.ws = null;
      try { ws.close(); } catch { /* already closed */ }
    }
    for (const s of this.sources) {
      s.onended = null;
      try { s.stop(); } catch { /* not started */ }
    }
    this.sources.clear();
  }

  /**
   * Start (or restart) reading.
   * @param {{project:string, file:string, start_word:number, voice:string, speed:number,
   *          skip:{references:boolean, citations:boolean, headers:boolean}}} req Stream request.
   * @returns {Promise<void>}
   */
  async start(req) {
    this._teardown();
    if (!this.ctx) this.ctx = new AudioContext({ latencyHint: "playback" });
    await this.ctx.resume();
    this._reset();
    this.nextStart = this.ctx.currentTime;
    this._setState("loading", "Starting…");

    const ws = new WebSocket(api.wsUrl());
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: "start", ...req }));
    ws.onmessage = (ev) => this._onMessage(ev);
    ws.onclose = () => {
      if (this.ws === ws && !this.ended) this._fail("Connection to the server was lost.");
    };
    this._raf = requestAnimationFrame(this._tick);
  }

  /** Pause playback (audio and highlighting freeze together). */
  pause() {
    if (this.state !== "playing") return;
    this.ctx.suspend();
    this._setState("paused");
  }

  /** Resume after :meth:`pause`. */
  resume() {
    if (this.state !== "paused") return;
    this.ctx.resume();
    this._setState("playing");
  }

  /** Stop reading and release the stream. */
  stop() {
    this._teardown();
    this._reset();
    this._setState("idle");
  }

  /**
   * Handle a WebSocket message (JSON header, status, or binary PCM).
   * @param {MessageEvent} ev The message event.
   */
  _onMessage(ev) {
    if (typeof ev.data === "string") {
      const m = JSON.parse(ev.data);
      if (m.type === "chunk") this.pending = m;
      else if (m.type === "status") this._setState(this.state, m.message);
      else if (m.type === "end") this.ended = true;
      else if (m.type === "error") this._fail(m.message);
      return;
    }
    const header = this.pending;
    this.pending = null;
    if (header) this._schedule(header, ev.data);
  }

  /**
   * Decode one PCM chunk and schedule it right after the previous one.
   * @param {{sample_rate:number, words:number[][]}} h Chunk header.
   * @param {ArrayBuffer} buf Little-endian int16 mono PCM.
   */
  _schedule(h, buf) {
    const i16 = new Int16Array(buf);
    const audio = this.ctx.createBuffer(1, i16.length, h.sample_rate);
    const ch = audio.getChannelData(0);
    for (let i = 0; i < i16.length; i++) ch[i] = i16[i] / 32768;
    const src = this.ctx.createBufferSource();
    src.buffer = audio;
    src.connect(this.ctx.destination);
    const startAt = Math.max(this.ctx.currentTime + 0.04, this.nextStart);
    src.start(startAt);
    this.nextStart = startAt + audio.duration;
    this.sources.add(src);
    src.onended = () => this.sources.delete(src);
    for (const [idx, s, e] of h.words) this.timeline.push({ idx, t0: startAt + s, t1: startAt + e });
    this.chunks.push({ start: startAt, end: startAt + audio.duration, first: h.words[0]?.[0] ?? -1, last: h.words.at(-1)?.[0] ?? -1 });
    if (this.state === "loading") this._setState("playing");
  }

  /**
   * Report a fatal problem and return to idle.
   * @param {string} message Human-readable error.
   */
  _fail(message) {
    this._teardown();
    this._reset();
    this._setState("idle");
    this._emit("error", { message });
  }

  /** @returns {number} Seconds of audio actually played so far (used for server flow control). */
  _playedSeconds() {
    const now = this.ctx.currentTime;
    while (this.chunkPtr < this.chunks.length && now >= this.chunks[this.chunkPtr].end) {
      const c = this.chunks[this.chunkPtr++];
      this.donePlayed += c.end - c.start;
    }
    const c = this.chunks[this.chunkPtr];
    return this.donePlayed + (c && now > c.start ? now - c.start : 0);
  }

  /** Animation-frame loop: update the highlighted word, flow control and end detection. */
  _tick() {
    if (!this.ws && this.state === "idle") return;
    this._raf = requestAnimationFrame(this._tick);
    const ctx = this.ctx;
    const now = ctx.currentTime - (ctx.outputLatency || ctx.baseLatency || 0);
    const tl = this.timeline;
    while (this.tp + 1 < tl.length && tl[this.tp + 1].t0 <= now) this.tp++;
    if (tl.length && tl[this.tp].t0 <= now && tl[this.tp].idx !== this.current) {
      this.current = tl[this.tp].idx;
      this._emit("word", { index: this.current });
    }
    if (this.ws && performance.now() - this.lastPos > 500 && this.ws.readyState === WebSocket.OPEN) {
      this.lastPos = performance.now();
      this.ws.send(JSON.stringify({ type: "pos", t: this._playedSeconds() }));
    }
    if (this.ended && this.state === "playing" && ctx.currentTime >= this.nextStart + 0.05) {
      this._teardown();
      this._reset();
      this._setState("idle");
      this._emit("end");
    }
  }

  /** @returns {number} Index of the chunk (≈ sentence) being played, or -1. */
  _currentChunk() {
    const now = this.ctx?.currentTime ?? 0;
    let idx = -1;
    this.chunks.forEach((c, i) => { if (c.start <= now) idx = i; });
    return idx;
  }

  /** @returns {number|null} First word of the next buffered sentence, if any. */
  nextSentence() {
    const i = this._currentChunk();
    const c = this.chunks[i + 1];
    return c && c.first >= 0 ? c.first : null;
  }

  /** @returns {number|null} First word to restart from for "previous sentence". */
  prevSentence() {
    const i = this._currentChunk();
    if (i < 0) return null;
    const cur = this.chunks[i];
    const target = this.ctx.currentTime - cur.start > 1.5 || i === 0 ? cur : this.chunks[i - 1];
    return target.first >= 0 ? target.first : null;
  }
}
