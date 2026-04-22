import { defaultServerUrl } from "../online-room.mjs";

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

export async function fetchEngineHealth({ serverUrl = "", signal } = {}) {
  const response = await fetch(`${normalizeServerOrigin(serverUrl)}/api/engine/health`, {
    method: "GET",
    cache: "no-store",
    signal,
  });

  const payload = await parseJsonResponse(response);
  if (!response.ok) {
    throw buildEngineError(payload, "Remote engine health request failed.");
  }
  return payload;
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

  async searchMove({ state, config, timeBudgetMs, maxDepth } = {}) {
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
        },
        signal: abortController.signal,
      });
    } finally {
      if (this.currentAbortController === abortController) {
        this.currentAbortController = null;
      }
    }
  }

  async analyzePosition({ state, config, timeBudgetMs, maxDepth } = {}) {
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
