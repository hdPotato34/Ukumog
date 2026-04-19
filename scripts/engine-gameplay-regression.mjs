import assert from "node:assert/strict";

import { searchMove, analyzePosition } from "../engine/engine-search.mjs";

class FakeWorker {
  constructor() {
    this.listeners = {
      message: new Set(),
      error: new Set(),
    };
  }

  addEventListener(type, callback) {
    if (this.listeners[type]) {
      this.listeners[type].add(callback);
    }
  }

  removeEventListener(type, callback) {
    this.listeners[type]?.delete(callback);
  }

  emit(type, payload) {
    for (const callback of this.listeners[type] || []) {
      callback(payload);
    }
  }

  postMessage(message) {
    setTimeout(() => {
      try {
        if (message.type === "init") {
          this.emit("message", {
            data: {
              type: "result",
              kind: "init",
              id: message.id,
              payload: { engineVersion: "fake-worker" },
            },
          });
          return;
        }

        if (message.type === "cancel") {
          this.emit("message", {
            data: {
              type: "result",
              kind: "cancel",
              id: message.id,
              payload: { ok: true },
            },
          });
          return;
        }

        if (message.type === "searchMove") {
          this.emit("message", {
            data: {
              type: "result",
              kind: "searchMove",
              id: message.id,
              payload: searchMove(message),
            },
          });
          return;
        }

        if (message.type === "analyzePosition") {
          this.emit("message", {
            data: {
              type: "result",
              kind: "analyzePosition",
              id: message.id,
              payload: analyzePosition(message),
            },
          });
          return;
        }

        throw new Error(`Unsupported fake worker message: ${message.type}`);
      } catch (error) {
        this.emit("message", {
          data: {
            type: "error",
            id: message.id,
            message: error instanceof Error ? error.message : "Fake worker failed.",
          },
        });
      }
    }, 0);
  }

  terminate() {}
}

globalThis.Worker = FakeWorker;

const [{ EngineGameplayRunner }, { createEngineRoomSession, applyEngineRoomMove }] = await Promise.all([
  import("../engine/engine-gameplay-runner.mjs"),
  import("../engine-room.mjs"),
]);

function createHarness(session) {
  const sessionRef = { current: session };

  const setSession = (value) => {
    const next = typeof value === "function" ? value(sessionRef.current) : value;
    sessionRef.current = next;
    return next;
  };

  return {
    sessionRef,
    setSession,
    getSession: () => sessionRef.current,
  };
}

async function waitFor(predicate, timeoutMs, label) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    if (predicate()) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error(`Timed out waiting for ${label} after ${timeoutMs} ms.`);
}

async function driveEngineTurn(runner, harness, timeoutMs, label) {
  const beforeMoveCount = harness.getSession().game.moves.length;
  runner.runTurn({
    screen: "engine",
    session: harness.getSession(),
    sessionRef: harness.sessionRef,
    setSession: harness.setSession,
  });

  await waitFor(() => {
    const session = harness.getSession();
    return session.engineStatus === "error" || session.game.moves.length > beforeMoveCount;
  }, timeoutMs, label);

  const session = harness.getSession();
  if (session.engineStatus === "error") {
    throw new Error(`Engine entered error state during ${label}: ${session.lastError}`);
  }
  return session;
}

function findSafeContinuation(session, preferredMoves = []) {
  const candidates = [
    ...preferredMoves,
    { row: 0, col: 0 },
    { row: 10, col: 10 },
    { row: 0, col: 10 },
    { row: 10, col: 0 },
    { row: 0, col: 5 },
    { row: 5, col: 0 },
    { row: 10, col: 5 },
    { row: 5, col: 10 },
    { row: 1, col: 3 },
    { row: 3, col: 1 },
    { row: 7, col: 9 },
    { row: 9, col: 7 },
    { row: 2, col: 6 },
    { row: 6, col: 2 },
  ];

  for (const move of candidates) {
    try {
      const actor = session.gameState.turn === session.engineSide ? "engine" : "player";
      const nextSession = applyEngineRoomMove(session, move, { actor });
      if (!nextSession.gameState.result) {
        return nextSession;
      }
    } catch {
      // Try the next move.
    }
  }

  throw new Error("Could not find a safe continuation move for the regression test.");
}

async function testFirstMove() {
  const runner = new EngineGameplayRunner({ enableOpeningWatchdog: false, enableWorkerFallback: false });
  runner.init();

  const harness = createHarness(createEngineRoomSession({
    boardSize: 11,
    baseSeconds: null,
    incrementSeconds: 0,
    colorMode: "white",
  }));

  const startedAt = Date.now();
  const session = await driveEngineTurn(runner, harness, 3000, "first move");
  const elapsedMs = Date.now() - startedAt;

  assert.equal(session.game.moves.length, 1, "Engine should complete the first move.");
  assert.equal(session.game.moves[0].row, 5, "First move should land on center row.");
  assert.equal(session.game.moves[0].col, 5, "First move should land on center col.");
  assert.notEqual(session.engineDebug?.stage, "watchdog-applied", "Regression first move should complete without watchdog.");

  runner.dispose();
  return { elapsedMs, debug: session.engineDebug };
}

async function testOpeningSequence() {
  const runner = new EngineGameplayRunner({ enableOpeningWatchdog: false, enableWorkerFallback: false });
  runner.init();

  const harness = createHarness(createEngineRoomSession({
    boardSize: 11,
    baseSeconds: null,
    incrementSeconds: 0,
    colorMode: "white",
  }));

  const results = [];

  for (let turnIndex = 0; turnIndex < 3; turnIndex += 1) {
    const startedAt = Date.now();
    const sessionAfterEngine = await driveEngineTurn(runner, harness, 3000, `opening turn ${turnIndex + 1}`);
    results.push({
      turn: turnIndex + 1,
      elapsedMs: Date.now() - startedAt,
      source: sessionAfterEngine.engineDebug?.source || "unknown",
      stage: sessionAfterEngine.engineDebug?.stage || "unknown",
    });

    if (turnIndex < 2) {
      harness.setSession(findSafeContinuation(harness.getSession()));
    }
  }

  assert.equal(harness.getSession().game.moves.length >= 5, true, "Opening sequence should advance past the first few plies.");

  runner.dispose();
  return results;
}

async function testMidgameResponse() {
  const runner = new EngineGameplayRunner({ enableOpeningWatchdog: false, enableWorkerFallback: false });
  runner.init();

  const harness = createHarness(createEngineRoomSession({
    boardSize: 11,
    baseSeconds: null,
    incrementSeconds: 0,
    colorMode: "white",
  }));

  let workingSession = harness.getSession();
  for (let index = 0; index < 8; index += 1) {
    workingSession = findSafeContinuation(workingSession);
  }
  harness.setSession(workingSession);

  assert.equal(harness.getSession().game.moves.length, 8, "Midgame setup should create an 8-ply position.");
  assert.equal(harness.getSession().gameState.turn, harness.getSession().engineSide, "Midgame setup should hand the turn to the engine.");

  const startedAt = Date.now();
  const sessionAfterEngine = await driveEngineTurn(runner, harness, 2000, "midgame response");
  const elapsedMs = Date.now() - startedAt;

  assert.equal(sessionAfterEngine.game.moves.length, 9, "Engine should add one move in the midgame position.");
  assert.notEqual(sessionAfterEngine.engineDebug?.source, "opening-book", "Midgame should not still be using the opening book.");
  assert.notEqual(sessionAfterEngine.engineDebug?.source, "sync-fallback", "Normal midgame search should not use sync fallback.");

  runner.dispose();
  return { elapsedMs, debug: sessionAfterEngine.engineDebug };
}

async function testWorkerFallbackPath() {
  const runner = new EngineGameplayRunner({ enableOpeningWatchdog: false, enableWorkerFallback: true });
  runner.client = {
    init() {
      return Promise.resolve({ engineVersion: "failing-client" });
    },
    searchMove() {
      return Promise.reject(new Error("forced-worker-failure"));
    },
    cancel() {
      return Promise.resolve({ ok: true });
    },
    dispose() {},
  };

  const harness = createHarness(createEngineRoomSession({
    boardSize: 11,
    baseSeconds: null,
    incrementSeconds: 0,
    colorMode: "white",
  }));

  let workingSession = harness.getSession();
  for (let index = 0; index < 8; index += 1) {
    workingSession = findSafeContinuation(workingSession);
  }
  harness.setSession(workingSession);

  const startedAt = Date.now();
  const sessionAfterEngine = await driveEngineTurn(runner, harness, 2000, "worker fallback response");
  const elapsedMs = Date.now() - startedAt;

  assert.equal(sessionAfterEngine.game.moves.length, 9, "Fallback path should still produce a move.");
  assert.equal(sessionAfterEngine.engineDebug?.source, "sync-fallback", "Forced worker failure should use sync fallback.");
  assert.equal(sessionAfterEngine.engineDebug?.reason, "forced-worker-failure", "Fallback debug should preserve failure reason.");

  runner.dispose();
  return { elapsedMs, debug: sessionAfterEngine.engineDebug };
}

const firstMove = await testFirstMove();
const openingSequence = await testOpeningSequence();
const midgame = await testMidgameResponse();
const workerFallback = await testWorkerFallbackPath();

console.log(JSON.stringify({
  firstMove,
  openingSequence,
  midgame,
  workerFallback,
}, null, 2));
console.log("Engine gameplay regression passed.");
