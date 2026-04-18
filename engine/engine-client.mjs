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
