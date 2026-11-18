/**
 * PDF viewer built on PDF.js (vendored, fully offline).
 *
 * Pages are rendered lazily to canvases. Highlights are plain absolutely
 * positioned divs on a per-page overlay, positioned in percentages of the page
 * from the server's normalised word boxes, so they stay aligned at any zoom.
 */
import * as pdfjsLib from "/static/vendor/pdfjs/pdf.min.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/vendor/pdfjs/pdf.worker.min.mjs";

const FLAG_CONTINUATION = 8;
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

export class PdfViewer {
  /**
   * @param {HTMLElement} scrollEl Scrollable container.
   * @param {HTMLElement} viewerEl Element that receives the page elements.
   * @param {{onPage?: (page:number, total:number)=>void, onZoom?: (label:string)=>void,
   *          onPick?: (wordIndex:number)=>void}} [handlers] Callbacks.
   */
  constructor(scrollEl, viewerEl, handlers = {}) {
    this.scrollEl = scrollEl;
    this.viewerEl = viewerEl;
    this.handlers = handlers;
    this.pdf = null;
    this.pages = [];
    this.words = [];
    this.pageRanges = [];
    this.zoomMode = "fit";
    this.scale = 1;
    this.hlEls = [];
    this._raf = 0;
    this._loadToken = 0;
    this._autoScrollUntil = 0;

    scrollEl.addEventListener("scroll", () => this._schedule(), { passive: true });
    new ResizeObserver(() => {
      if (this.zoomMode === "fit") this._applyFit();
    }).observe(scrollEl);
    viewerEl.addEventListener("dblclick", (ev) => this._onDoubleClick(ev));
  }

  /**
   * Load a PDF and create (empty) page placeholders.
   * @param {string} url URL of the PDF file.
   * @returns {Promise<void>} Resolves when placeholders exist; rendering is lazy.
   */
  async load(url) {
    this.close();
    const token = ++this._loadToken;
    const pdf = await pdfjsLib.getDocument({ url }).promise;
    if (token !== this._loadToken) {
      pdf.destroy();
      return;
    }
    this.pdf = pdf;
    const proxies = await Promise.all(Array.from({ length: pdf.numPages }, (_, i) => pdf.getPage(i + 1)));
    if (token !== this._loadToken) return;
    proxies.forEach((proxy, i) => {
      const vp = proxy.getViewport({ scale: 1 });
      const el = document.createElement("div");
      el.className = "page";
      el.dataset.page = String(i);
      const canvas = document.createElement("canvas");
      const overlay = document.createElement("div");
      overlay.className = "overlay";
      el.append(canvas, overlay);
      this.viewerEl.append(el);
      this.pages.push({ el, canvas, overlay, proxy, base: { w: vp.width, h: vp.height }, renderedScale: 0, task: null });
    });
    this.scrollEl.scrollTop = 0;
    this.zoomMode === "fit" ? this._applyFit(true) : this._layout();
  }

  /** Tear down the current document and clear all pages. */
  close() {
    this._loadToken++;
    for (const p of this.pages) p.task?.cancel();
    this.pdf?.destroy();
    this.pdf = null;
    this.pages = [];
    this.words = [];
    this.pageRanges = [];
    this.hlEls = [];
    this.viewerEl.replaceChildren();
  }

  /**
   * Provide the word geometry used for highlighting and click-to-read.
   * @param {{words: number[][]}} wire Server response of the /words endpoint.
   */
  setWords(wire) {
    this.words = wire.words;
    this.pageRanges = [];
    this.words.forEach((w, i) => {
      const r = this.pageRanges[w[0]];
      if (!r) this.pageRanges[w[0]] = [i, i + 1];
      else r[1] = i + 1;
    });
  }

  /**
   * Zoom by a factor and leave "fit" mode.
   * @param {number} factor Multiplier, e.g. 1.15.
   */
  zoomBy(factor) {
    this.zoomMode = "manual";
    this._setScale(clamp(this.scale * factor, 0.3, 4));
  }

  /** Switch back to fit-to-width mode. */
  fit() {
    this.zoomMode = "fit";
    this._applyFit();
  }

  /**
   * Highlight a word (and the second half of a hyphen-split word).
   * @param {number} index Global word index.
   * @param {{follow?: boolean, soft?: boolean}} [opts] ``follow`` scrolls it into view; ``soft`` draws the dim "cursor" style.
   */
  highlight(index, { follow = true, soft = false } = {}) {
    this.clearHighlight();
    if (!this.words[index]) return;
    const idxs = [index];
    for (let k = index + 1; k < this.words.length && this.words[k][5] & FLAG_CONTINUATION; k++) idxs.push(k);
    for (const k of idxs) {
      const [pg, x0, y0, x1, y1] = this.words[k];
      const page = this.pages[pg];
      if (!page) continue;
      const d = document.createElement("div");
      d.className = soft ? "hl soft" : "hl";
      Object.assign(d.style, {
        left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%`,
      });
      page.overlay.append(d);
      this.hlEls.push(d);
    }
    if (follow && this.hlEls[0]) this._follow(this.hlEls[0]);
  }

  /** Remove the current highlight. */
  clearHighlight() {
    this.hlEls.forEach((d) => d.remove());
    this.hlEls = [];
  }

  /**
   * Scroll so a word sits near the upper third of the view.
   * @param {number} index Global word index.
   */
  scrollToWord(index) {
    const w = this.words[index];
    const page = w && this.pages[w[0]];
    if (!page) return;
    const pr = page.el.getBoundingClientRect();
    const sr = this.scrollEl.getBoundingClientRect();
    this.scrollEl.scrollTop += pr.top - sr.top + w[2] * pr.height - sr.height * 0.3;
  }

  /**
   * Find the word nearest to a point on a page.
   * @param {number} page Zero-based page index.
   * @param {number} nx Normalised x (0..1).
   * @param {number} ny Normalised y (0..1).
   * @returns {number} Global word index, or -1 if the page has no words.
   */
  wordAt(page, nx, ny) {
    const [start, end] = this.pageRanges[page] || [0, 0];
    let best = -1;
    let bestD = Infinity;
    for (let i = start; i < end; i++) {
      const w = this.words[i];
      const dx = nx < w[1] ? w[1] - nx : nx > w[3] ? nx - w[3] : 0;
      const dy = ny < w[2] ? w[2] - ny : ny > w[4] ? ny - w[4] : 0;
      const d = dx * dx + dy * dy;
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    }
    return best;
  }

  // ------------------------------------------------------------- internals
  /**
   * Handle a double click: report the word under the cursor.
   * @param {MouseEvent} ev The dblclick event.
   */
  _onDoubleClick(ev) {
    const pageEl = ev.target.closest(".page");
    if (!pageEl) return;
    const r = pageEl.getBoundingClientRect();
    const idx = this.wordAt(Number(pageEl.dataset.page), (ev.clientX - r.left) / r.width, (ev.clientY - r.top) / r.height);
    if (idx >= 0) this.handlers.onPick?.(idx);
  }

  /** Compute the fit-to-width scale and apply it if it changed noticeably.
   * @param {boolean} [force] Apply even if the scale barely changed. */
  _applyFit(force = false) {
    if (!this.pages.length) return;
    const maxW = Math.max(...this.pages.map((p) => p.base.w));
    const scale = clamp((this.scrollEl.clientWidth - 48) / maxW, 0.3, 4);
    if (force || Math.abs(scale - this.scale) / this.scale > 0.005) this._setScale(scale);
  }

  /**
   * Set the zoom scale, keeping the relative scroll position.
   * @param {number} scale New scale factor (1 = 72 dpi).
   */
  _setScale(scale) {
    const ratio = this.scrollEl.scrollHeight ? this.scrollEl.scrollTop / this.scrollEl.scrollHeight : 0;
    this.scale = scale;
    this._layout();
    this.scrollEl.scrollTop = ratio * this.scrollEl.scrollHeight;
  }

  /** Resize all page elements for the current scale and schedule re-rendering. */
  _layout() {
    for (const p of this.pages) {
      p.el.style.width = `${p.base.w * this.scale}px`;
      p.el.style.height = `${p.base.h * this.scale}px`;
      if (p.renderedScale !== this.scale) p.task?.cancel();
    }
    this.handlers.onZoom?.(this.zoomMode === "fit" ? "Fit" : `${Math.round(this.scale * 100)}%`);
    this._schedule();
  }

  /** Coalesce render/page-indicator work into one animation frame. */
  _schedule() {
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => {
      this._raf = 0;
      this._ensureRendered();
      this._reportPage();
    });
  }

  /** Render pages near the viewport and free canvases far away. */
  _ensureRendered() {
    const sr = this.scrollEl.getBoundingClientRect();
    for (const p of this.pages) {
      const r = p.el.getBoundingClientRect();
      const y0 = r.top - sr.top;
      const y1 = r.bottom - sr.top;
      if (y1 > -900 && y0 < sr.height + 900) this._render(p);
      else if ((y1 < -3500 || y0 > sr.height + 3500) && p.renderedScale && !p.task) {
        p.canvas.width = p.canvas.height = 0;
        p.renderedScale = 0;
      }
    }
  }

  /**
   * Render one page at the current scale (no-op if up to date or busy).
   * @param {object} p Page record created in :meth:`load`.
   */
  _render(p) {
    if (p.task || p.renderedScale === this.scale) return;
    const scale = this.scale;
    const vp = p.proxy.getViewport({ scale: scale * (window.devicePixelRatio || 1) });
    p.canvas.width = Math.floor(vp.width);
    p.canvas.height = Math.floor(vp.height);
    p.task = p.proxy.render({ canvasContext: p.canvas.getContext("2d"), viewport: vp });
    p.task.promise
      .then(() => { p.renderedScale = scale; })
      .catch(() => { /* cancelled by a zoom change */ })
      .finally(() => {
        p.task = null;
        if (p.renderedScale !== this.scale) this._schedule();
      });
  }

  /** Report the page currently in the middle of the viewport. */
  _reportPage() {
    if (!this.pages.length) return;
    const sr = this.scrollEl.getBoundingClientRect();
    const mid = sr.top + sr.height / 2;
    let cur = 0;
    this.pages.forEach((p, i) => {
      if (p.el.getBoundingClientRect().top <= mid) cur = i;
    });
    this.handlers.onPage?.(cur + 1, this.pages.length);
  }

  /**
   * Scroll smoothly if a highlighted element left the comfortable band of the view.
   * @param {HTMLElement} el Highlight element.
   */
  _follow(el) {
    if (performance.now() < this._autoScrollUntil) return;
    const sr = this.scrollEl.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    const rel = (r.top - sr.top) / sr.height;
    if (rel < 0.12 || rel > 0.7) {
      this._autoScrollUntil = performance.now() + 450;
      this.scrollEl.scrollTo({ top: this.scrollEl.scrollTop + (r.top - sr.top) - sr.height * 0.3, behavior: "smooth" });
    }
  }
}
