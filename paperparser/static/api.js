/** Thin wrappers around the PaperParser REST API. */

/**
 * Perform a JSON request and throw an Error carrying the server's message on failure.
 * @param {string} method HTTP method.
 * @param {string} url Request URL.
 * @param {object|FormData} [body] JSON-serialisable object or FormData.
 * @returns {Promise<any>} Parsed JSON response.
 */
async function request(method, url, body) {
  const init = { method, headers: {} };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch { /* keep statusText */ }
    throw new Error(detail);
  }
  return res.json();
}

const enc = encodeURIComponent;

export const api = {
  /** @returns {Promise<object>} Engine state, device and library path. */
  status: () => request("GET", "/api/status"),
  /** @returns {Promise<Array<{id:string,name:string,group:string}>>} Voice presets. */
  voices: () => request("GET", "/api/voices"),
  /** @returns {Promise<Array<object>>} All projects. */
  projects: () => request("GET", "/api/projects"),
  /** @param {string} name Project name. @param {string|null} [color] Hex colour. */
  createProject: (name, color = null) => request("POST", "/api/projects", { name, color }),
  /** @param {string} name Project name. @param {object} patch Fields to change. */
  updateProject: (name, patch) => request("PATCH", `/api/projects/${enc(name)}`, patch),
  /** @param {string} name Project name. @returns {Promise<object>} Project with its papers. */
  project: (name) => request("GET", `/api/projects/${enc(name)}`),
  /**
   * Upload PDFs into a project.
   * @param {string} project Project name.
   * @param {File[]} files PDF files.
   * @returns {Promise<{added: object[], errors: object[]}>}
   */
  upload(project, files) {
    const form = new FormData();
    files.forEach((f) => form.append("files", f, f.name));
    return request("POST", `/api/projects/${enc(project)}/papers`, form);
  },
  /**
   * Patch a paper's metadata.
   * @param {string} project Project name.
   * @param {string} file PDF file name.
   * @param {object} patch Fields to change.
   * @returns {Promise<object>} Updated paper.
   */
  updatePaper: (project, file, patch) => request("PATCH", `/api/projects/${enc(project)}/papers/${enc(file)}`, patch),
  /** @returns {Promise<object>} Word boxes/flags of a paper for highlighting. */
  words: (project, file) => request("GET", `/api/projects/${enc(project)}/papers/${enc(file)}/words`),
  /** @returns {string} URL of the PDF file. */
  pdfUrl: (project, file) => `/api/projects/${enc(project)}/papers/${enc(file)}/pdf`,
  /** @returns {string} WebSocket URL of the read-aloud stream. */
  wsUrl: () => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/read`,
};
