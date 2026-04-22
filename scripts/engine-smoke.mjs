import assert from "node:assert/strict";

import { buildRecordFromMoves, findDeepestMainlineNode } from "../game-record.mjs";
import { applyEngineRoomMove, createEngineRoomSession } from "../engine-room.mjs";
import { EngineGameplayRunner } from "../engine/engine-gameplay-runner.mjs";

class FakeRemoteClient {
  constructor(plans = []) {
    this.plans = [...plans];
    this.currentAbort = null;
    this.requests = [];
    this.sourceName = "remote-search";
  }

  async init() {
    return { ok: true, source: this.sourceName };
  }

  async searchMove(request = {}) {
    if (!this.plans.length) {
      throw new Error("No fake remote response plan was queued.");
    }

    this.requests.push({
      ...request,
      config: request.config ? { ...request.config } : null,
    });

    const plan = this.plans.shift();
    this.currentAbort = { cancelled: false };

    return new Promise((resolve, reject) => {
      setTimeout(() => {
        if (this.currentAbort?.cancelled) {
          reject(new Error("Request cancelled."));
          return;
        }

        if (plan.type === "error") {
          reject(new Error(plan.message || "Fake remote search failed."));
          return;
        }

        resolve({
          bestMove: plan.bestMove,
          score: plan.score ?? 0,
          mate: null,
          pv: plan.pv || [plan.bestMove],
          depth: plan.depth ?? 4,
          nodes: plan.nodes ?? 42,
          timeMs: plan.timeMs ?? 12,
          backend: "fake-remote",
          engineVersion: "fake-remote-r1",
        });
      }, plan.delayMs ?? 5);
    }).finally(() => {
      this.currentAbort = null;
    });
  }

  async cancel() {
    if (this.currentAbort) {
      this.currentAbort.cancelled = true;
    }
    return { ok: true };
  }

  dispose() {
    if (this.currentAbort) {
      this.currentAbort.cancelled = true;
      this.currentAbort = null;
    }
  }
}

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
    getSession() {
      return sessionRef.current;
    },
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
  throw new Error(`Timed out waiting for ${label}.`);
}

async function driveRemoteTurn(runner, harness, label, timeoutMs = 1500) {
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

  return harness.getSession();
}

function findSafeContinuation(session, preferredMoves = []) {
  const boardSize = session.config.boardSize;
  const last = boardSize - 1;
  const middle = Math.floor(boardSize / 2);
  const near = Math.min(1, last);
  const inner = Math.min(2, last);
  const outer = Math.max(last - 2, 0);
  const rawCandidates = [
    ...preferredMoves,
    { row: 0, col: 0 },
    { row: last, col: last },
    { row: 0, col: last },
    { row: last, col: 0 },
    { row: 0, col: middle },
    { row: middle, col: 0 },
    { row: last, col: middle },
    { row: middle, col: last },
    { row: near, col: outer },
    { row: outer, col: near },
    { row: inner, col: middle },
    { row: middle, col: inner },
    { row: outer, col: middle },
    { row: middle, col: outer },
  ];
  const candidates = [
    ...new Map(rawCandidates.map((move) => [`${move.row}:${move.col}`, move])).values(),
  ];

  for (const move of candidates) {
    try {
      const actor = session.gameState.turn === session.engineSide ? "engine" : "player";
      const nextSession = applyEngineRoomMove(session, move, { actor });
      if (!nextSession.gameState.result) {
        return nextSession;
      }
    } catch {
      // Ignore and try the next candidate.
    }
  }

  throw new Error("Could not find a safe continuation for the smoke test.");
}

function createMidgameHarness({
  config = {
    boardSize: 11,
    baseSeconds: null,
    incrementSeconds: 0,
    colorMode: "white",
  },
  engineSettings,
} = {}) {
  let session = createEngineRoomSession({
    ...config,
  }, { displayName: "Tester", authenticated: true }, {
    engineSettings,
  });

  for (let index = 0; index < 8; index += 1) {
    session = findSafeContinuation(session);
  }

  return createHarness(session);
}

async function testRemoteFirstMoveAndFollowup() {
  const fakeClient = new FakeRemoteClient([
    {
      bestMove: { row: 4, col: 8, notation: "I5" },
      score: 24,
      pv: [{ row: 4, col: 8, notation: "I5" }],
    },
    {
      bestMove: { row: 8, col: 4, notation: "E9" },
      score: 18,
      pv: [{ row: 8, col: 4, notation: "E9" }],
    },
  ]);

  const runner = new EngineGameplayRunner({
    enableOpeningWatchdog: false,
    enableWorkerFallback: false,
    clientFactory: () => fakeClient,
  });
  runner.init();

  const harness = createMidgameHarness();

  let session = await driveRemoteTurn(runner, harness, "first remote turn");
  assert.equal(session.game.moves.length, 9, "Remote engine should add one move to the prepared midgame.");
  assert.equal(session.game.moves[8].notation, "I5");
  assert.equal(session.analysis?.bestMove?.notation, "I5");
  assert.equal(session.engineDebug?.source, "remote-search");

  harness.setSession(findSafeContinuation(harness.getSession()));
  session = await driveRemoteTurn(runner, harness, "second remote turn");

  assert.equal(session.game.moves.length, 11, "Engine and player moves should accumulate in the session.");
  assert.equal(session.game.moves[10].notation, "E9");
  assert.equal(session.engineDebug?.source, "remote-search");
  assert.equal(session.engineStatus, "idle");

  const record = buildRecordFromMoves(session.config, session.game.moves, {
    title: "Smoke Engine Match",
    sourceKind: "local",
    sourceLabel: "Local Engine Match",
    gameId: session.game.id,
    players: session.game.players,
    result: session.gameState.result,
  });

  assert.notEqual(findDeepestMainlineNode(record), record.rootId, "Built record should contain a non-root main line.");

  runner.dispose();

  return {
    moveCount: session.game.moves.length,
    finalMove: session.game.moves[10].notation,
    recordTitle: record.meta.title,
  };
}

async function testIllegalRemoteMoveFailsSafely() {
  const fakeClient = new FakeRemoteClient([
    {
      bestMove: { row: 0, col: 0, notation: "A1" },
    },
  ]);

  const runner = new EngineGameplayRunner({
    enableOpeningWatchdog: false,
    enableWorkerFallback: false,
    clientFactory: () => fakeClient,
  });
  runner.init();

  const harness = createMidgameHarness();

  runner.runTurn({
    screen: "engine",
    session: harness.getSession(),
    sessionRef: harness.sessionRef,
    setSession: harness.setSession,
  });

  await waitFor(() => harness.getSession().engineStatus === "error", 1500, "illegal remote move error");

  const failedSession = harness.getSession();
  assert.match(
    failedSession.lastError,
    /(illegal move|not legal)/i,
    "Illegal remote move should surface a safe error message.",
  );

  runner.dispose();

  return {
    error: failedSession.lastError,
    stage: failedSession.engineDebug?.stage,
  };
}

async function testCustomSearchSettingsAreForwarded() {
  const fakeClient = new FakeRemoteClient([
    {
      bestMove: { row: 4, col: 8, notation: "I5" },
    },
    {
      bestMove: { row: 8, col: 4, notation: "E9" },
    },
  ]);

  const runner = new EngineGameplayRunner({
    enableOpeningWatchdog: false,
    enableWorkerFallback: false,
    clientFactory: () => fakeClient,
  });
  runner.init();

  const timedHarness = createMidgameHarness({
    config: {
      boardSize: 11,
      baseSeconds: 180,
      incrementSeconds: 2,
      colorMode: "white",
    },
    engineSettings: {
      timedTimeBudgetMs: 325,
      untimedTimeBudgetMs: 90,
      maxDepth: 7,
    },
  });

  await driveRemoteTurn(runner, timedHarness, "timed remote turn");
  assert.equal(fakeClient.requests[0]?.timeBudgetMs, 325, "Timed engine search should forward the configured timed search budget.");
  assert.equal(fakeClient.requests[0]?.maxDepth, 7, "Timed engine search should forward the configured depth.");

  const untimedHarness = createMidgameHarness({
    engineSettings: {
      timedTimeBudgetMs: 300,
      untimedTimeBudgetMs: 95,
      maxDepth: 6,
    },
  });
  await driveRemoteTurn(runner, untimedHarness, "untimed remote turn");
  assert.equal(fakeClient.requests[1]?.timeBudgetMs, 95, "Untimed engine search should forward the configured untimed search budget.");
  assert.equal(fakeClient.requests[1]?.maxDepth, 6, "Untimed engine search should forward the configured depth.");

  runner.dispose();

  return {
    timed: {
      timeBudgetMs: fakeClient.requests[0]?.timeBudgetMs,
      maxDepth: fakeClient.requests[0]?.maxDepth,
    },
    untimed: {
      timeBudgetMs: fakeClient.requests[1]?.timeBudgetMs,
      maxDepth: fakeClient.requests[1]?.maxDepth,
    },
  };
}

async function testNineBoardOpeningSupport() {
  const fakeClient = new FakeRemoteClient([
    {
      bestMove: { row: 4, col: 4, notation: "E5" },
      score: 10,
      pv: [{ row: 4, col: 4, notation: "E5" }],
    },
  ]);

  const runner = new EngineGameplayRunner({
    enableOpeningWatchdog: false,
    enableWorkerFallback: false,
    clientFactory: () => fakeClient,
  });
  runner.init();

  const session = createEngineRoomSession({
    boardSize: 9,
    baseSeconds: null,
    incrementSeconds: 0,
    colorMode: "white",
  }, { displayName: "Tester", authenticated: true });
  const harness = createHarness(session);
  const afterOpening = await driveRemoteTurn(runner, harness, "9x9 remote opening");

  assert.equal(afterOpening.config.boardSize, 9, "Smoke harness should retain the requested 9x9 board size.");
  assert.equal(afterOpening.game.moves.length, 1, "Engine should be able to open a 9x9 engine room.");
  assert.equal(afterOpening.game.moves[0].notation, "E5");
  assert.equal(afterOpening.analysis?.bestMove?.notation, "E5");
  assert.equal(fakeClient.requests[0]?.config?.boardSize, 9, "Engine request should forward the 9x9 board size.");

  const record = buildRecordFromMoves(afterOpening.config, afterOpening.game.moves, {
    title: "Smoke Engine Match 9x9",
    sourceKind: "local",
    sourceLabel: "Local Engine Match",
    gameId: afterOpening.game.id,
    players: afterOpening.game.players,
    result: afterOpening.gameState.result,
  });
  assert.notEqual(findDeepestMainlineNode(record), record.rootId, "9x9 record should contain a non-root move.");

  runner.dispose();

  return {
    boardSize: afterOpening.config.boardSize,
    openingMove: afterOpening.game.moves[0].notation,
  };
}

const successfulMatch = await testRemoteFirstMoveAndFollowup();
const illegalMove = await testIllegalRemoteMoveFailsSafely();
const forwardedSearchSettings = await testCustomSearchSettingsAreForwarded();
const multiBoardSupport = await testNineBoardOpeningSupport();

console.log(JSON.stringify({
  successfulMatch,
  illegalMove,
  forwardedSearchSettings,
  multiBoardSupport,
}, null, 2));
console.log("Engine room smoke passed.");
