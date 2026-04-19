import assert from "node:assert/strict";

import { opp } from "../game-core.mjs";
import { createEngineRoomSession, applyEngineRoomMove } from "../engine-room.mjs";
import {
  GAMEPLAY_ENGINE_PACK,
  GAMEPLAY_SEARCH_MAX_DEPTH,
  GAMEPLAY_UNTIMED_SEARCH_BUDGET_MS,
} from "../engine/engine-gameplay-runner.mjs";
import { searchMove } from "../engine/engine-search.mjs";
import { classifyMove, listImmediateWinningMoves } from "../engine/engine-tactics.mjs";
import { createPerspectiveState } from "../engine/rules-adapter.mjs";

const FORCED_DEFENSE_SEQUENCE = [
  { row: 5, col: 8, actor: "engine" },
  { row: 10, col: 8, actor: "player" },
  { row: 6, col: 3, actor: "engine" },
  { row: 4, col: 6, actor: "player" },
  { row: 10, col: 3, actor: "engine" },
  { row: 3, col: 4, actor: "player" },
  { row: 7, col: 0, actor: "engine" },
  { row: 4, col: 5, actor: "player" },
  { row: 6, col: 2, actor: "engine" },
  { row: 5, col: 6, actor: "player" },
  { row: 6, col: 4, actor: "engine" },
  { row: 8, col: 3, actor: "player" },
  { row: 0, col: 3, actor: "engine" },
  { row: 6, col: 8, actor: "player" },
  { row: 4, col: 8, actor: "engine" },
  { row: 3, col: 5, actor: "player" },
  { row: 0, col: 9, actor: "engine" },
  { row: 7, col: 8, actor: "player" },
  { row: 3, col: 0, actor: "engine" },
  { row: 6, col: 6, actor: "player" },
];

const SELF_DESTRUCT_SEQUENCE = [
  { row: 0, col: 0, actor: "engine" },
  { row: 10, col: 10, actor: "player" },
  { row: 0, col: 1, actor: "engine" },
  { row: 10, col: 9, actor: "player" },
  { row: 0, col: 2, actor: "engine" },
  { row: 9, col: 10, actor: "player" },
];

function buildForcedDefenseSession() {
  return buildSessionFromMoves(FORCED_DEFENSE_SEQUENCE);
}

function buildSelfDestructSession() {
  return buildSessionFromMoves(SELF_DESTRUCT_SEQUENCE);
}

function buildSessionFromMoves(sequence) {
  let session = createEngineRoomSession({
    boardSize: 11,
    baseSeconds: null,
    incrementSeconds: 0,
    colorMode: "white",
  });

  for (const move of sequence) {
    session = applyEngineRoomMove(session, { row: move.row, col: move.col }, { actor: move.actor });
  }

  return session;
}

function opponentImmediateWins(state, config) {
  const opponentState = createPerspectiveState(state, opp(state.turn));
  return listImmediateWinningMoves(opponentState, config);
}

function analyzeWithGameplayPack(state, config, signal) {
  return searchMove({
    state,
    config,
    enginePack: GAMEPLAY_ENGINE_PACK,
    timeBudgetMs: GAMEPLAY_UNTIMED_SEARCH_BUDGET_MS,
    maxDepth: GAMEPLAY_SEARCH_MAX_DEPTH,
    signal,
  });
}

function runForcedDefenseRegression() {
  const session = buildForcedDefenseSession();

  assert.equal(session.phase, "active", "Forced-defense position should still be active.");
  assert.equal(session.gameState.turn, session.engineSide, "Engine should be the side to move in forced-defense position.");

  const winningRepliesBefore = opponentImmediateWins(session.gameState, session.config);
  assert.ok(winningRepliesBefore.length > 0, "Opponent should already have at least one immediate winning reply.");

  const analysis = analyzeWithGameplayPack(session.gameState, session.config);
  assert.ok(analysis.bestMove, "Engine should return a move in forced-defense position.");

  const chosen = classifyMove(session.gameState, session.config, analysis.bestMove);
  assert.ok(chosen, "Chosen move should classify correctly.");
  assert.equal(chosen.isImmediateLoss, false, "Engine should not choose an immediate self-loss in forced-defense position.");

  const winningRepliesAfter = opponentImmediateWins(chosen.nextState, session.config);
  assert.equal(
    winningRepliesAfter.length,
    0,
    "Engine should eliminate the opponent's immediate winning replies in forced-defense position.",
  );

  const abortController = new AbortController();
  abortController.abort();
  const fallbackAnalysis = analyzeWithGameplayPack(session.gameState, session.config, abortController.signal);
  assert.ok(fallbackAnalysis.bestMove, "Fallback search should still return a move.");
  const fallbackChosen = classifyMove(session.gameState, session.config, fallbackAnalysis.bestMove);
  assert.ok(fallbackChosen, "Fallback move should classify correctly.");
  const fallbackWinningRepliesAfter = opponentImmediateWins(fallbackChosen.nextState, session.config);
  assert.equal(
    fallbackWinningRepliesAfter.length,
    0,
    "Aborted search fallback should still eliminate the opponent's immediate winning replies.",
  );

  return {
    winningRepliesBefore,
    chosenMove: analysis.bestMove,
    winningRepliesAfter,
    fallbackChosenMove: fallbackAnalysis.bestMove,
    fallbackWinningRepliesAfter,
    score: analysis.score,
    depth: analysis.depth,
  };
}

function runSelfDestructRegression() {
  const session = buildSelfDestructSession();

  assert.equal(session.phase, "active", "Self-destruct position should still be active.");
  assert.equal(session.gameState.turn, session.engineSide, "Engine should be the side to move in self-destruct position.");

  const losingMove = { row: 0, col: 3 };
  const losingSummary = classifyMove(session.gameState, session.config, losingMove);
  assert.ok(losingSummary, "Known self-destruct move should classify correctly.");
  assert.equal(losingSummary.isImmediateLoss, true, "Known self-destruct move should be marked as immediate loss.");

  const analysis = analyzeWithGameplayPack(session.gameState, session.config);
  assert.ok(analysis.bestMove, "Engine should return a move in self-destruct position.");
  assert.notDeepEqual(
    analysis.bestMove,
    losingMove,
    "Engine should not choose the obvious self-destructing fourth stone.",
  );

  const chosen = classifyMove(session.gameState, session.config, analysis.bestMove);
  assert.ok(chosen, "Chosen move should classify correctly in self-destruct position.");
  assert.equal(chosen.isImmediateLoss, false, "Engine should avoid immediate self-loss in self-destruct position.");

  const abortController = new AbortController();
  abortController.abort();
  const fallbackAnalysis = analyzeWithGameplayPack(session.gameState, session.config, abortController.signal);
  assert.ok(fallbackAnalysis.bestMove, "Fallback search should still return a move in self-destruct position.");
  assert.notDeepEqual(
    fallbackAnalysis.bestMove,
    losingMove,
    "Fallback search should not choose the obvious self-destructing fourth stone.",
  );

  const fallbackChosen = classifyMove(session.gameState, session.config, fallbackAnalysis.bestMove);
  assert.ok(fallbackChosen, "Fallback move should classify correctly in self-destruct position.");
  assert.equal(fallbackChosen.isImmediateLoss, false, "Fallback move should also avoid immediate self-loss.");

  return {
    losingMove,
    chosenMove: analysis.bestMove,
    fallbackChosenMove: fallbackAnalysis.bestMove,
  };
}

const forcedDefense = runForcedDefenseRegression();
const selfDestruct = runSelfDestructRegression();

console.log(JSON.stringify({
  forcedDefense,
  selfDestruct,
}, null, 2));
console.log("Engine tactics regression passed.");
