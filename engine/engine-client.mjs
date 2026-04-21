import { defaultServerUrl } from "../online-room.mjs";

export class LocalEngineClient {
  constructor({
    workerFactory,
    enginePack,
    enginePackUrl = "",
  } = {}) {
    this.enginePack = enginePack || null;
    this.enginePackUrl = enginePackUrl;
    this.workerFactory = workerFactory || (() => new Worker(new URL("./engine-worker.js", import.meta.url), { type: "module" }));
    this.worker = null;
    this.requests = new Map();
    this.nextId = 1;
  }

  ensureWorker() {
    if (this.worker) {
      return this.worker;
    }

    this.worker = this.workerFactory();
    this.worker.addEventListener("message", (event) => {
      const message = event.data || {};
      const request = this.requests.get(message.id);
      if (!request) {
        return;
      }

      if (message.type === "error") {
        this.requests.delete(message.id);
        request.reject(new Error(message.message || "Engine request failed."));
        return;
      }

      if (message.type === "result") {
        this.requests.delete(message.id);
        request.resolve(message.payload);
      }
    });

    this.worker.addEventListener("error", (error) => {
      for (const request of this.requests.values()) {
        request.reject(error.error || new Error(error.message || "Engine worker crashed."));
      }
      this.requests.clear();
      this.worker = null;
    });

    return this.worker;
  }

  postRequest(type, payload = {}) {
    const worker = this.ensureWorker();
    const id = `engine-${this.nextId++}`;
    return new Promise((resolve, reject) => {
      this.requests.set(id, { resolve, reject });
      worker.postMessage({
        id,
        type,
        ...payload,
      });
    });
  }

  async init({ enginePack = this.enginePack, enginePackUrl = this.enginePackUrl } = {}) {
    const payload = {};
    if (enginePack) payload.enginePack = enginePack;
    if (!enginePack && enginePackUrl) payload.enginePackUrl = enginePackUrl;
    const result = await this.postRequest("init", payload);
    return result;
  }

  searchMove({ state, config, timeBudgetMs, maxDepth, enginePack } = {}) {
    return this.postRequest("searchMove", {
      state,
      config,
      timeBudgetMs,
      maxDepth,
      enginePack,
    });
  }

  analyzePosition({ state, config, timeBudgetMs, maxDepth, enginePack } = {}) {
    return this.postRequest("analyzePosition", {
      state,
      config,
      timeBudgetMs,
      maxDepth,
      enginePack,
    });
  }

  cancel() {
    return this.postRequest("cancel", {});
  }

  dispose() {
    if (this.worker) {
      this.worker.terminate();
      this.worker = null;
    }
    for (const request of this.requests.values()) {
      request.reject(new Error("Engine client disposed."));
    }
    this.requests.clear();
  }
}

function normalizeServerOrigin(baseUrl) {
  const clean = String(baseUrl || "").trim().replace(/\/+$/, "");
  return clean || defaultServerUrl();
}

async function parseJsonResponse(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function buildEngineError(payload, fallbackMessage) {
  const message = payload?.message || fallbackMessage || "Engine request failed.";
  const error = new Error(message);
  if (payload?.code) {
    error.code = payload.code;
  }
  return error;
}

export class RemoteEngineClient {
  constructor({
    serverUrl = "",
    getSessionToken = null,
  } = {}) {
    this.serverUrl = normalizeServerOrigin(serverUrl);
    this.getSessionToken = typeof getSessionToken === "function" ? getSessionToken : () => "";
    this.currentAbortController = null;
    this.sourceName = "remote-search";
  }

  async request(route, {
    method = "GET",
    body,
    signal,
  } = {}) {
    const sessionToken = this.getSessionToken();
    const response = await fetch(`${this.serverUrl}${route}`, {
      method,
      headers: {
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...(sessionToken ? { "x-session-token": sessionToken } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
      cache: "no-store",
      signal,
    });

    const payload = await parseJsonResponse(response);
    if (!response.ok) {
      throw buildEngineError(payload, "Remote engine request failed.");
    }
    return payload;
  }

  async init() {
    return { ok: true, source: this.sourceName };
  }

  async searchMove({ state, config, timeBudgetMs, maxDepth, enginePack } = {}) {
    this.cancelActiveRequest();
    const abortController = new AbortController();
    this.currentAbortController = abortController;

    try {
      return await this.request("/api/engine/search", {
        method: "POST",
        body: {
          state,
          config,
          timeBudgetMs,
          maxDepth,
          ...(enginePack ? { enginePack } : {}),
        },
        signal: abortController.signal,
      });
    } finally {
      if (this.currentAbortController === abortController) {
        this.currentAbortController = null;
      }
    }
  }

  async analyzePosition({ state, config, timeBudgetMs, maxDepth, enginePack } = {}) {
    this.cancelActiveRequest();
    const abortController = new AbortController();
    this.currentAbortController = abortController;

    try {
      return await this.request("/api/engine/analyze", {
        method: "POST",
        body: {
          state,
          config,
          timeBudgetMs,
          maxDepth,
          ...(enginePack ? { enginePack } : {}),
        },
        signal: abortController.signal,
      });
    } finally {
      if (this.currentAbortController === abortController) {
        this.currentAbortController = null;
      }
    }
  }

  cancelActiveRequest() {
    if (this.currentAbortController) {
      this.currentAbortController.abort();
      this.currentAbortController = null;
    }
  }

  async cancel() {
    this.cancelActiveRequest();
    return { ok: true };
  }

  dispose() {
    this.cancelActiveRequest();
  }
}
