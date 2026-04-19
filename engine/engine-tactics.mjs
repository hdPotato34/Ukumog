import { opp } from "../game-core.mjs";
import {
  applyEngineMove,
  countNearbyStones,
  createPerspectiveState,
  localMoveCandidates,
  moveKey,
  listLegalMoves,
  normalizeEngineConfig,
} from "./rules-adapter.mjs";

function centerBias(boardSize, row, col) {
  const middle = (boardSize - 1) / 2;
  return boardSize - (Math.abs(row - middle) + Math.abs(col - middle));
}

function lastMoveBias(state, row, col) {
  if (!state.last) return 0;
  return 6 - (Math.abs(row - state.last[0]) + Math.abs(col - state.last[1]));
}

export function classifyMove(state, config, move) {
  const cleanConfig = normalizeEngineConfig(config);
  const currentPlayer = state.turn;
  const nextState = applyEngineMove(state, cleanConfig, move);

  if (!nextState) {
    return null;
  }

  const isImmediateWin = !!nextState.result && nextState.result.winner === currentPlayer;
  const isImmediateLoss = !!nextState.result && nextState.result.winner === opp(currentPlayer);
  const nearby = countNearbyStones(state, move.row, move.col, 1);
  const score = (
    (isImmediateWin ? 2_000_000 : 0)
    + (isImmediateLoss ? -2_000_000 : 0)
    + nearby.friendly * 80
    + nearby.opponent * 50
    + centerBias(cleanConfig.boardSize, move.row, move.col) * 8
    + lastMoveBias(state, move.row, move.col) * 6
  );

  return {
    move: { row: move.row, col: move.col },
    key: moveKey(move),
    nextState,
    isImmediateWin,
    isImmediateLoss,
    opponentImmediateWins: 0,
    nearbyFriendly: nearby.friendly,
    nearbyOpponent: nearby.opponent,
    tacticalScore: score,
  };
}

function countOpponentImmediateWins(nextState, config) {
  if (nextState.result) {
    return 0;
  }

  const opponentMoves = listLegalMoves(nextState, config);
  let count = 0;
  for (const move of opponentMoves) {
    const replyState = applyEngineMove(nextState, config, move);
    if (replyState?.result?.winner === nextState.turn) {
      count += 1;
    }
  }
  return count;
}

export function listImmediateWinningMoves(state, config) {
  const legalMoves = listLegalMoves(state, config);
  const winningMoves = [];
  for (const move of legalMoves) {
    const summary = classifyMove(state, config, move);
    if (summary?.isImmediateWin) {
      winningMoves.push(summary.move);
    }
  }
  return winningMoves;
}

function mergeUniqueSummaries(entries) {
  const seen = new Set();
  const merged = [];
  for (const entry of entries) {
    if (!entry || seen.has(entry.key)) {
      continue;
    }
    seen.add(entry.key);
    merged.push(entry);
  }
  return merged;
}

export function rankCandidateMoves(state, config, {
  candidateLimit = 16,
  preferredRadius = 2,
  fallbackRadius = 3,
  minCount = 8,
} = {}) {
  const cleanConfig = normalizeEngineConfig(config);
  const seedMoves = localMoveCandidates(state, config, {
    preferredRadius,
    fallbackRadius,
    minCount,
  });
  let summaries = seedMoves
    .map((move) => classifyMove(state, config, move))
    .filter(Boolean);

  const opponentState = createPerspectiveState(state, opp(state.turn));
  const currentOpponentImmediateWins = listImmediateWinningMoves(opponentState, cleanConfig).length;
  const safeSummaryCount = summaries.filter((entry) => !entry.isImmediateLoss).length;

  if (currentOpponentImmediateWins > 0 || safeSummaryCount < Math.min(candidateLimit, 3)) {
    const emergencySummaries = listLegalMoves(state, cleanConfig)
      .map((move) => classifyMove(state, cleanConfig, move))
      .filter(Boolean);
    summaries = mergeUniqueSummaries([...summaries, ...emergencySummaries]);
  }

  if (!summaries.length) {
    return [];
  }

  const immediateWins = summaries.filter((entry) => entry.isImmediateWin);
  if (immediateWins.length) {
    return immediateWins
      .sort((left, right) => right.tacticalScore - left.tacticalScore)
      .slice(0, candidateLimit);
  }

  const safeSummaries = summaries.filter((entry) => !entry.isImmediateLoss);
  const pool = safeSummaries.length ? safeSummaries : summaries;

  pool.sort((left, right) => right.tacticalScore - left.tacticalScore);

  const threatCheckedCount = currentOpponentImmediateWins > 0
    ? pool.length
    : Math.min(pool.length, Math.max(candidateLimit * 2, 8));
  for (let index = 0; index < threatCheckedCount; index += 1) {
    pool[index].opponentImmediateWins = countOpponentImmediateWins(pool[index].nextState, cleanConfig);
    pool[index].tacticalScore -= pool[index].opponentImmediateWins * (currentOpponentImmediateWins > 0 ? 20_000 : 4_000);
  }

  if (currentOpponentImmediateWins > 0) {
    const minOpponentImmediateWins = Math.min(...pool.map((entry) => entry.opponentImmediateWins));
    const emergencyPool = pool.filter((entry) => entry.opponentImmediateWins === minOpponentImmediateWins);
    emergencyPool.sort((left, right) => {
      if (left.isImmediateLoss !== right.isImmediateLoss) {
        return left.isImmediateLoss ? 1 : -1;
      }
      return right.tacticalScore - left.tacticalScore;
    });
    return emergencyPool.slice(0, candidateLimit);
  }

  pool.sort((left, right) => {
    if (left.opponentImmediateWins !== right.opponentImmediateWins) {
      return left.opponentImmediateWins - right.opponentImmediateWins;
    }
    return right.tacticalScore - left.tacticalScore;
  });

  return pool.slice(0, candidateLimit);
}
