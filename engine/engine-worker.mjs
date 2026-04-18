import { DEFAULT_ENGINE_PACK, normalizeEnginePack } from "./engine-eval.mjs";
import { analyzePosition, searchMove } from "./engine-search.mjs";

let currentEnginePack = normalizeEnginePack(DEFAULT_ENGINE_PACK);
let currentTaskController = null;

function post(kind, id, payload) {
  globalThis.postMessage({
    type: "result",
    kind,
    id,
    payload,
  });
}

function postError(id, message) {
  globalThis.postMessage({
    type: "error",
    id,
    message,
  });
}

function cancelCurrentTask() {
  if (currentTaskController) {
    currentTaskController.abort();
    currentTaskController = null;
  }
}

async function resolveEnginePack(message) {
  if (message.enginePack) {
    return normalizeEnginePack(message.enginePack);
  }
  if (message.enginePackUrl) {
    const response = await fetch(message.enginePackUrl, { cache: "no-store" });
    const payload = await response.json();
    return normalizeEnginePack(payload);
  }
  return currentEnginePack;
}

globalThis.onmessage = async (event) => {
  const message = event.data || {};
  try {
    if (message.type === "cancel") {
      cancelCurrentTask();
      post("cancel", message.id || "", { ok: true });
      return;
    }

    if (message.type === "init") {
      currentEnginePack = await resolveEnginePack(message);
      post("init", message.id || "", {
        engineVersion: currentEnginePack.engineVersion,
      });
      return;
    }

    if (message.type === "searchMove" || message.type === "analyzePosition") {
      cancelCurrentTask();
      currentTaskController = new AbortController();
      const pack = message.enginePack ? normalizeEnginePack(message.enginePack) : currentEnginePack;
      const baseInput = {
        state: message.state,
        config: message.config,
        enginePack: pack,
        timeBudgetMs: message.timeBudgetMs,
        maxDepth: message.maxDepth,
        signal: currentTaskController.signal,
      };
      const payload = message.type === "searchMove"
        ? searchMove(baseInput)
        : analyzePosition(baseInput);

      currentTaskController = null;
      post(message.type, message.id || "", {
        ...payload,
        engineVersion: pack.engineVersion,
      });
      return;
    }

    postError(message.id || "", `Unknown worker message type: ${message.type || "unknown"}.`);
  } catch (error) {
    currentTaskController = null;
    postError(message.id || "", error instanceof Error ? error.message : "Worker request failed.");
  }
};
