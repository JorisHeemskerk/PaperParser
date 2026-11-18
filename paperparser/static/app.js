/** PaperParser frontend: library browsing, notes, PDF viewing and read-aloud wiring. */
import { api } from "./api.js";
import { PdfViewer } from "./viewer.js";
import { ReadAloud } from "./player.js";

const $ = (sel) => document.querySelector(sel);
const PALETTE = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#14b8a6", "#3b82f6", "#8b5cf6", "#ec4899"];
const DEFAULT_PREFS = {
  voice: null, speed: 1.0, follow: true, project: null, details: false,
  skip: { references: true, citations: true, headers: true },
};

// ------------------------------------------------------------------ helpers
/**
 * Create a DOM element (text only, never innerHTML, so file names/notes can't inject markup).
 * @param {string} tag Tag name.
 * @param {object} [props] Properties assigned to the element (``class``, ``dataset``, ``style`` supported).
 * @param {...(Node|string)} children Child nodes or text.
 * @returns {HTMLElement}
 */
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k === "style") node.style.cssText = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node[k] = v;
  }
  node.append(...children);
  return node;
}

/**
 * Return a debounced wrapper of a function.
 * @param {Function} fn Function to delay.
 * @param {number} ms Delay in milliseconds.
 * @returns {Function}
 */
function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

/** @returns {object} Preferences from localStorage merged over the defaults. */
function loadPrefs() {
  try {
    const saved = JSON.parse(localStorage.getItem("paperparser.prefs") || "{}");
    return { ...DEFAULT_PREFS, ...saved, skip: { ...DEFAULT_PREFS.skip, ...(saved.skip || {}) } };
  } catch {
    return structuredClone(DEFAULT_PREFS);
  }
}
const prefs = loadPrefs();
const savePrefs = () => localStorage.setItem("paperparser.prefs", JSON.stringify(prefs));

let toastTimer;
/**
 * Show a transient message at the top of the window.
 * @param {string} msg Text to show.
 * @param {number} [ms] Visible duration.
 */
function toast(msg, ms = 3500) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), ms);
}

/** Report an error to the user without breaking the app.
 * @param {Error} e The error. */
const fail = (e) => toast(e.message || String(e), 6000);

// -------------------------------------------------------------------- state
const state = {
  projects: [],
  project: null, // name
  data: null, // project payload incl. papers
  paper: null, // currently open paper object
  wire: null, // words of the open paper
  cursor: 0, // word index where Play starts
  openToken: 0,
};

const player = new ReadAloud();
const viewer = new PdfViewer($("#viewer-scroll"), $("#viewer"), {
  onPage: (p, n) => ($("#page-indicator").textContent = `${p} / ${n}`),
  onZoom: (label) => ($("#zoom-label").textContent = label),
  onPick: (idx) => {
    if (!state.paper) return;
    state.cursor = idx;
    play(idx);
  },
});

// ------------------------------------------------------------------ projects
/** Fetch the project list and re-render the sidebar. */
async function refreshProjects() {
  state.projects = await api.projects();
  renderProjects();
}

/** Render the project sidebar. */
function renderProjects() {
  const list = $("#project-list");
  list.replaceChildren(
    ...state.projects.map((p) =>
      el("div", { class: `project${p.name === state.project ? " active" : ""}`, onclick: () => selectProject(p.name) },
        el("span", {
          class: "dot", title: "Click to change colour", style: p.color ? `background:${p.color}` : "",
          onclick: async (ev) => {
            ev.stopPropagation();
            const next = PALETTE[(PALETTE.indexOf(p.color) + 1) % PALETTE.length];
            try { await api.updateProject(p.name, { color: next }); await refreshProjects(); } catch (e) { fail(e); }
          },
        }),
        el("span", { class: "name ellipsis" }, p.name),
        el("span", { class: "count" }, String(p.paper_count)),
      ),
    ),
  );
}

/**
 * Open a project and show its papers.
 * @param {string} name Project name.
 */
async function selectProject(name) {
  state.project = name;
  prefs.project = name;
  savePrefs();
  renderProjects();
  await loadProject();
}

/** (Re)load the current project's papers from the server and render the list. */
async function loadProject() {
  if (!state.project) return renderPapers();
  try {
    state.data = await api.project(state.project);
  } catch (e) {
    state.project = state.data = null;
    renderProjects();
    return fail(e);
  }
  if (state.paper) state.paper = state.data.papers.find((p) => p.filename === state.paper.filename) || state.paper;
  renderPapers();
  $("#groups-list").replaceChildren(...state.data.groups.map((g) => el("option", { value: g })));
}

// -------------------------------------------------------------- paper list
/** Render the (filtered, grouped) paper list. */
function renderPapers() {
  const list = $("#paper-list");
  if (!state.data) {
    list.replaceChildren(el("div", { class: "empty-hint" }, state.projects.length ? "Select a project." : "Create a project to get started — or make a folder inside your library directory."));
    return;
  }
  const q = $("#search").value.trim().toLowerCase();
  const papers = state.data.papers.filter((p) =>
    !q || [p.display_title, p.filename, p.group, p.notes, ...(p.tags || [])].join(" ").toLowerCase().includes(q));
  if (!papers.length) {
    list.replaceChildren(el("div", { class: "empty-hint" }, q ? "No matches." : "No papers yet. Drop PDFs here or press Upload."));
    return;
  }
  const groups = new Map();
  for (const p of papers) {
    if (!groups.has(p.group)) groups.set(p.group, []);
    groups.get(p.group).push(p);
  }
  const names = [...groups.keys()].sort((a, b) => (a === "" ? 1 : b === "" ? -1 : a.localeCompare(b)));
  const nodes = [];
  for (const g of names) {
    if (g !== "" || names.length > 1) nodes.push(el("div", { class: "group-label" }, g || "Ungrouped"));
    for (const p of groups.get(g).sort((a, b) => Number(b.favorite) - Number(a.favorite) || a.display_title.localeCompare(b.display_title))) {
      nodes.push(
        el("div", {
          class: `paper${state.paper?.filename === p.filename ? " active" : ""}`,
          style: p.color ? `--bar:${p.color}` : "",
          onclick: () => openPaper(p.filename),
        },
          el("div", { class: "title" }, (p.favorite ? "★ " : "") + p.display_title),
          el("div", { class: "sub" },
            p.status !== "unread" ? el("span", { class: `badge ${p.status}` }, p.status) : "",
            el("span", {}, `${p.pages} p.`),
            ...(p.tags || []).slice(0, 3).map((t) => el("span", {}, `#${t}`)),
          ),
        ),
      );
    }
  }
  list.replaceChildren(...nodes);
}

// ------------------------------------------------------------------- reader
/**
 * Open a paper in the viewer and load its word geometry.
 * @param {string} filename PDF file name inside the current project.
 */
async function openPaper(filename) {
  const paper = state.data?.papers.find((p) => p.filename === filename);
  if (!paper) return;
  await flushSave();
  player.stop();
  viewer.clearHighlight();
  const token = ++state.openToken;
  state.paper = paper;
  state.wire = null;
  state.cursor = paper.reading_pos || 0;
  location.hash = `#/${encodeURIComponent(state.project)}/${encodeURIComponent(filename)}`;
  $("#doc-title").textContent = paper.display_title;
  $("#empty").hidden = true;
  $("#player").hidden = false;
  $("#player-status").textContent = "";
  renderPapers();
  renderDetails();
  try {
    const [, wire] = await Promise.all([viewer.load(api.pdfUrl(state.project, filename)), api.words(state.project, filename)]);
    if (token !== state.openToken) return;
    state.wire = wire;
    viewer.setWords(wire);
    if (!wire.words.length) {
      $("#player-status").textContent = "No text layer found — scanned PDF? Run `ocrmypdf` on it first.";
    } else if (state.cursor > 0 && state.cursor < wire.words.length) {
      viewer.highlight(state.cursor, { follow: false, soft: true });
      viewer.scrollToWord(state.cursor);
    }
  } catch (e) {
    if (token === state.openToken) fail(e);
  }
}

// ------------------------------------------------------------------ details
const saveQueue = { project: null, file: null, patch: {}, timer: 0 };

/**
 * Queue a metadata change for the open paper; it is written after a short pause.
 * @param {object} patch Fields to change (see PaperPatch on the server).
 */
function queueSave(patch) {
  if (!state.paper) return;
  if (saveQueue.file && saveQueue.file !== state.paper.filename) flushSave();
  Object.assign(state.paper, patch);
  Object.assign(saveQueue, { project: state.project, file: state.paper.filename });
  Object.assign(saveQueue.patch, patch);
  $("#d-saved").textContent = "…";
  clearTimeout(saveQueue.timer);
  saveQueue.timer = setTimeout(flushSave, 600);
}

/** Write any queued metadata change to the server now. */
async function flushSave() {
  clearTimeout(saveQueue.timer);
  if (!saveQueue.file || !Object.keys(saveQueue.patch).length) return;
  const { project, file, patch } = saveQueue;
  saveQueue.file = null;
  saveQueue.patch = {};
  try {
    const updated = await api.updatePaper(project, file, patch);
    if (project === state.project && state.data) {
      const i = state.data.papers.findIndex((p) => p.filename === file);
      if (i >= 0) state.data.papers[i] = updated;
      if (state.paper?.filename === file) Object.assign(state.paper, { display_title: updated.display_title });
      renderPapers();
    }
    $("#d-saved").textContent = "Saved";
    setTimeout(() => ($("#d-saved").textContent = ""), 1500);
  } catch (e) {
    $("#d-saved").textContent = "";
    fail(e);
  }
}

/** Fill the details/notes panel from the open paper. */
function renderDetails() {
  const p = state.paper;
  $("#details-empty").hidden = !!p;
  $("#details-body").hidden = !p;
  if (!p) return;
  $("#d-title").value = p.title ?? "";
  $("#d-title").placeholder = p.display_title;
  $("#d-group").value = p.group || "";
  $("#d-tags").value = (p.tags || []).join(", ");
  if (document.activeElement !== $("#d-notes")) $("#d-notes").value = p.notes || "";
  $("#d-fav").textContent = p.favorite ? "★" : "☆";
  $("#d-fav").setAttribute("aria-pressed", String(!!p.favorite));
  document.querySelectorAll("#d-status button").forEach((b) => b.classList.toggle("on", b.dataset.status === p.status));
  $("#d-colors").replaceChildren(
    el("button", { class: `swatch none${p.color ? "" : " on"}`, title: "No colour", onclick: () => { queueSave({ color: null }); renderDetails(); } }),
    ...PALETTE.map((c) => el("button", { class: `swatch${p.color === c ? " on" : ""}`, style: `--c:${c}`, title: c, onclick: () => { queueSave({ color: c }); renderDetails(); } })),
  );
  $("#d-meta").textContent = `${p.filename} · ${p.pages} pages · ${(p.size / 1e6).toFixed(1)} MB`;
}

/** Toggle the details/notes side panel. */
function setDetailsOpen(open) {
  prefs.details = open;
  savePrefs();
  $("#details").hidden = !open;
  $("#app").classList.toggle("details-open", open);
  $("#toggle-details").style.color = open ? "var(--accent)" : "";
}

// ------------------------------------------------------------------- upload
/**
 * Upload PDFs into the current project.
 * @param {File[]} files Files chosen or dropped.
 */
async function uploadFiles(files) {
  const pdfs = files.filter((f) => f.name.toLowerCase().endsWith(".pdf"));
  if (!pdfs.length) return toast("Only PDF files can be added.");
  if (!state.project) return toast("Create or select a project first.");
  try {
    const res = await api.upload(state.project, pdfs);
    await Promise.all([refreshProjects(), loadProject()]);
    if (res.errors.length) toast(res.errors.map((e) => `${e.filename}: ${e.detail}`).join("\n"), 6000);
    else toast(`Added ${res.added.length} paper${res.added.length === 1 ? "" : "s"}.`);
    if (!state.paper && res.added[0]) openPaper(res.added[0].filename);
  } catch (e) {
    fail(e);
  }
}

// -------------------------------------------------------------- read aloud
/**
 * Start reading from a word.
 * @param {number} [startWord] Global word index; defaults to the saved cursor.
 */
async function play(startWord = state.cursor) {
  if (!state.paper || !state.wire?.words.length) return;
  try {
    await player.start({
      project: state.project, file: state.paper.filename, start_word: startWord,
      voice: prefs.voice, speed: prefs.speed, skip: prefs.skip,
    });
    if (state.paper.status === "unread") queueSave({ status: "reading" });
  } catch (e) {
    fail(e);
  }
}

/** Persist the reading position of the open paper. */
function saveProgress() {
  if (state.paper && state.cursor >= 0) queueSave({ reading_pos: state.cursor });
}
const saveProgressSoon = debounce(saveProgress, 4000);

/** Restart with new voice/speed/skip settings, from the word being read. */
const restartSoon = debounce(() => {
  const from = player.current >= 0 ? player.current : state.cursor;
  if (player.state === "playing" || player.state === "loading") play(from);
  else if (player.state === "paused") { state.cursor = from; player.stop(); }
}, 400);

/** Update the play button, status line and wake state from the player state. */
function syncPlayerUi({ state: s, message }) {
  // SVG elements have no `.hidden` property, so toggle the attribute explicitly
  $("#icon-play").toggleAttribute("hidden", s === "playing");
  $("#icon-pause").toggleAttribute("hidden", s !== "playing");
  $("#player-status").textContent = s === "loading" ? message || "Starting…" : message || (s === "paused" ? "Paused" : "");
  if (s === "paused" || s === "idle") saveProgress();
}

player.addEventListener("state", (ev) => syncPlayerUi(ev.detail));
player.addEventListener("word", (ev) => {
  state.cursor = ev.detail.index;
  viewer.highlight(state.cursor, { follow: prefs.follow });
  saveProgressSoon();
});
player.addEventListener("end", () => {
  viewer.clearHighlight();
  state.cursor = 0;
  queueSave({ status: "read", reading_pos: 0 });
  toast("Finished reading.");
});
player.addEventListener("error", (ev) => {
  toast(ev.detail.message, 7000);
  $("#player-status").textContent = ev.detail.message;
});

// --------------------------------------------------------------------- UI
/** Fill the voice dropdown (grouped) and restore the saved choice.
 * @param {Array<{id:string,name:string,group:string}>} voices Voices from the server.
 * @param {string} fallback Default voice id. */
function renderVoices(voices, fallback) {
  const select = $("#voice");
  const groups = new Map();
  for (const v of voices) {
    if (!groups.has(v.group)) groups.set(v.group, el("optgroup", { label: v.group }));
    groups.get(v.group).append(el("option", { value: v.id }, v.name));
  }
  select.replaceChildren(...groups.values());
  if (!voices.some((v) => v.id === prefs.voice)) prefs.voice = voices.some((v) => v.id === fallback) ? fallback : voices[0]?.id;
  select.value = prefs.voice;
}

/** Render engine status in the sidebar footer.
 * @param {object} s Response of /api/status. */
function renderStatus(s) {
  const label = s.state === "ready" ? "ready" : s.state === "loading" ? "loading model…" : "error";
  $("#engine-status").replaceChildren(
    el("div", { class: `state ${s.state}` }, `${s.engine} · ${label}`),
    el("div", {}, s.device),
    ...(s.error ? [el("div", {}, s.error)] : []),
    ...(s.note ? [el("div", {}, s.note)] : []),
    el("div", { title: s.library, class: "ellipsis" }, s.library),
  );
  return s.state;
}

/** Wire up all DOM event handlers (called once). */
function bindUi() {
  $("#search").addEventListener("input", renderPapers);
  $("#upload-btn").addEventListener("click", () => $("#upload-input").click());
  $("#upload-input").addEventListener("change", (e) => { uploadFiles([...e.target.files]); e.target.value = ""; });

  const dialog = $("#project-dialog");
  $("#new-project").addEventListener("click", () => { $("#project-name").value = ""; dialog.showModal(); $("#project-name").focus(); });
  dialog.addEventListener("close", async () => {
    if (dialog.returnValue !== "ok") return;
    try {
      const p = await api.createProject($("#project-name").value, PALETTE[state.projects.length % PALETTE.length]);
      await refreshProjects();
      await selectProject(p.name);
    } catch (e) { fail(e); }
  });

  $("#zoom-in").addEventListener("click", () => viewer.zoomBy(1.15));
  $("#zoom-out").addEventListener("click", () => viewer.zoomBy(1 / 1.15));
  $("#zoom-fit").addEventListener("click", () => viewer.fit());
  $("#toggle-details").addEventListener("click", () => setDetailsOpen(!prefs.details));

  // notes & details
  $("#d-title").addEventListener("input", (e) => queueSave({ title: e.target.value.trim() || null }));
  $("#d-group").addEventListener("input", (e) => queueSave({ group: e.target.value }));
  $("#d-tags").addEventListener("input", (e) => queueSave({ tags: e.target.value.split(",").map((t) => t.trim()).filter(Boolean) }));
  $("#d-notes").addEventListener("input", (e) => queueSave({ notes: e.target.value }));
  $("#d-fav").addEventListener("click", () => { queueSave({ favorite: !state.paper?.favorite }); renderDetails(); });
  $("#d-status").addEventListener("click", (e) => { if (e.target.dataset.status) { queueSave({ status: e.target.dataset.status }); renderDetails(); } });
  window.addEventListener("beforeunload", () => { saveProgress(); flushSave(); });

  // player
  $("#btn-play").addEventListener("click", togglePlay);
  $("#btn-next").addEventListener("click", () => { const n = player.nextSentence(); if (n != null) play(n); });
  $("#btn-prev").addEventListener("click", () => { const n = player.prevSentence(); if (n != null) play(n); });
  $("#voice").addEventListener("change", (e) => { prefs.voice = e.target.value; savePrefs(); restartSoon(); });
  $("#speed").addEventListener("input", (e) => {
    prefs.speed = Number(e.target.value);
    $("#speed-label").textContent = `${prefs.speed.toFixed(2).replace(/0$/, "")}×`;
    savePrefs();
    restartSoon();
  });
  for (const key of ["references", "citations", "headers"]) {
    $(`#skip-${key}`).checked = prefs.skip[key];
    $(`#skip-${key}`).addEventListener("change", (e) => { prefs.skip[key] = e.target.checked; savePrefs(); restartSoon(); });
  }
  $("#follow").checked = prefs.follow;
  $("#follow").addEventListener("change", (e) => { prefs.follow = e.target.checked; savePrefs(); });
  $("#speed").value = prefs.speed;
  $("#speed-label").textContent = `${prefs.speed.toFixed(2).replace(/0$/, "")}×`;

  // keyboard
  window.addEventListener("keydown", (e) => {
    const t = e.target;
    if (t.closest?.("input, textarea, select, dialog") || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.code === "Space") { e.preventDefault(); togglePlay(); }
    else if (e.code === "ArrowRight") $("#btn-next").click();
    else if (e.code === "ArrowLeft") $("#btn-prev").click();
  });

  // drag & drop upload anywhere
  let depth = 0;
  const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
  window.addEventListener("dragenter", (e) => { if (!hasFiles(e)) return; e.preventDefault(); depth++; $("#drop-target").textContent = state.project || "…"; $("#drop-overlay").hidden = false; });
  window.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
  window.addEventListener("dragleave", (e) => { if (!hasFiles(e)) return; if (--depth <= 0) { depth = 0; $("#drop-overlay").hidden = true; } });
  window.addEventListener("drop", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    depth = 0;
    $("#drop-overlay").hidden = true;
    uploadFiles([...e.dataTransfer.files]);
  });

  // pick up PDFs dropped into the folder by hand / OneDrive
  const refresh = () => { if (!document.hidden && state.project) { refreshProjects().catch(() => {}); loadProject().catch(() => {}); } };
  setInterval(refresh, 10000);
  window.addEventListener("focus", refresh);
}

/** Play/pause toggle used by the button and the space bar. */
function togglePlay() {
  if (!state.paper) return;
  if (player.state === "playing") player.pause();
  else if (player.state === "paused") player.resume();
  else play();
}

/** Boot the application. */
async function init() {
  bindUi();
  setDetailsOpen(prefs.details);
  const [status, voices] = await Promise.all([api.status(), api.voices()]);
  renderVoices(voices, status.default_voice);
  let engineState = renderStatus(status);
  if (engineState === "loading") {
    const poll = setInterval(async () => {
      const s = await api.status().catch(() => null);
      if (s && renderStatus(s) !== "loading") clearInterval(poll);
    }, 1500);
  }
  await refreshProjects();
  const [, hp, hf] = (location.hash.match(/^#\/([^/]+)\/?(.*)$/) || []).map((v) => v && decodeURIComponent(v));
  const target = [hp, prefs.project].find((n) => state.projects.some((p) => p.name === n)) || state.projects[0]?.name;
  if (target) await selectProject(target);
  else renderPapers();
  if (hp === target && hf) openPaper(hf);
}

init().catch(fail);
