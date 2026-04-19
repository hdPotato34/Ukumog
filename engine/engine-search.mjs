import { opp } from "../game-core.mjs";
import { DEFAULT_ENGINE_PACK, evaluateState, isMateScore, normalizeEnginePack, scoreToMatePly, terminalScoreForWinner } from "./engine-eval.mjs";
import { createPerspectiveState, hashState, listLegalMoves, normalizeEngineConfig } from "./rules-adapter.mjs";
import { listImmediateWinningMoves, rankCandidateMoves } from "./engine-tactics.mjs";

class SearchAbortError extends Error {
  constructor(message = "Search aborted.") {
    super(message);
    this.name = "SearchAbortError";
  }
}

function now() {
  return Date.now();
}

function ensureSearchState(context) {
  if (context.signal?.aborted) {
    throw new SearchAbortError();
  }
  if (now() >= context.deadlineAt) {
    throw new SearchAbortError("Search timed out.");
  }
}

function buildMoveSummary(bestMove, score, pv, depth, nodeCount, startedAt, pack) {
  return {
    bestMove: bestMove ? { ...bestMove } : null,
    score,
    mate: scoreToMatePly(score, pack),
    pv: Array.isArray(pv) ? pv.map((move) => ({ ...move })) : [],
    depth,
    nodes: nodeCount,
    timeMs: now() - startedAt,
  };
}

function storeExactEntry(context, key, depth, score, bestMove, pv) {
  if (!context.pack.featureFlags.useTranspositionTable) {
    return;
  }
  context.table.set(key, {
    depth,
    score,
    bestMove: bestMove ? { ...bestMove } : null,
    pv: Array.isArray(pv) ? pv.map((move) => ({ ...move })) : [],
  });
}

function lookupEntry(context, key, depth) {
  if (!context.pack.featureFlags.useTranspositionTable) {
    return null;
  }
  const entry = context.table.get(key);
  if (!entry || entry.depth < depth) {
    return null;
  }
  return entry;
}

function rankedCandidates(state, config, context, candidateLimit = context.pack.search.candidateLimit) {
  return rankCandidateMoves(state, config, {
    candidateLimit,
    preferredRadius: context.pack.search.preferredRadius,
    fallbackRadius: context.pack.search.fallbackRadius,
    minCount: context.pack.search.minCandidateCount,
  });
}

function tacticalCandidates(state, config, context) {
  const currentWinningMoves = listImmediateWinningMoves(state, config);
  const opponentState = createPerspectiveState(state, opp(state.turn));
  const opponentWinningMoves = listImmediateWinningMoves(opponentState, config);

  if (!currentWinningMoves.length && !opponentWinningMoves.length) {
    return [];
  }

  const candidateLimit = Math.max(
    context.pack.search.candidateLimit,
    context.pack.search.tacticalCandidateLimit || context.pack.search.candidateLimit,
  );
  const candidates = rankedCandidates(state, config, context, candidateLimit);
  if (!candidates.length) {
    return [];
  }

  if (currentWinningMoves.length) {
    return candidates.filter((candidate) => candidate.isImmediateWin);
  }

  const minOpponentImmediateWins = Math.min(...candidates.map((candidate) => candidate.opponentImmediateWins ?? 0));
  return candidates.filter((candidate) => (candidate.opponentImmediateWins ?? 0) === minOpponentImmediateWins);
}

function quiescenceNegamax(state, config, alpha, beta, player, ply, remainingDepth, context) {
  ensureSearchState(context);
  context.nodeCount += 1;

  if (state.result) {
    return {
      score: terminalScoreForWinner(state.result.winner, player, context.pack, ply),
      pv: [],
    };
  }

  if (remainingDepth <= 0) {
    return {
      score: evaluateState(state, config, context.pack, { perspective: player }),
      pv: [],
    };
  }

  const candidates = tacticalCandidates(state, config, context);
  if (!candidates.length) {
    return {
      score: evaluateState(state, config, context.pack, { perspective: player }),
      pv: [],
    };
  }

  let bestScore = -Infinity;
  let bestPv = [];
  let localAlpha = alpha;

  for (const candidate of candidates) {
    ensureSearchState(context);
    let nextScore = 0;
    let childPv = [];

    if (candidate.nextState.result) {
      nextScore = terminalScoreForWinner(candidate.nextState.result.winner, player, context.pack, ply + 1);
    } else {
      const child = quiescenceNegamax(candidate.nextState, config, -beta, -localAlpha, opp(player), ply + 1, remainingDepth - 1, context);
      nextScore = -child.score;
      childPv = child.pv;
    }

    if (nextScore > bestScore) {
      bestScore = nextScore;
      bestPv = [candidate.move, ...childPv];
    }
    if (nextScore > localAlpha) {
      localAlpha = nextScore;
    }
    if (localAlpha >= beta) {
      break;
    }
  }

  return {
    score: bestScore,
    pv: bestPv,
  };
}

function negamax(state, config, depth, alpha, beta, player, ply, context) {
  ensureSearchState(context);
  context.nodeCount += 1;

  if (state.result) {
    return {
      score: terminalScoreForWinner(state.result.winner, player, context.pack, ply),
      pv: [],
    };
  }

  if (depth <= 0) {
    return quiescenceNegamax(
      state,
      config,
      alpha,
      beta,
      player,
      ply,
      Math.max(0, context.pack.search.quiescenceDepth || 0),
      context,
    );
  }

  const key = `${hashState(state)}|${player}|${depth}`;
  const cached = lookupEntry(context, key, depth);
  if (cached) {
    return {
      score: cached.score,
      pv: cached.pv,
    };
  }

  const candidates = rankedCandidates(state, config, context);

  if (!candidates.length) {
    return { score: 0, pv: [] };
  }

  let bestScore = -Infinity;
  let bestMove = null;
  let bestPv = [];
  let localAlpha = alpha;

  for (const candidate of candidates) {
    ensureSearchState(context);
    let nextScore = 0;
    let childPv = [];

    if (candidate.nextState.result) {
      nextScore = terminalScoreForWinner(candidate.nextState.result.winner, player, context.pack, ply + 1);
    } else {
      const child = negamax(candidate.nextState, config, depth - 1, -beta, -localAlpha, opp(player), ply + 1, context);
      nextScore = -child.score;
      childPv = child.pv;
    }

    if (nextScore > bestScore) {
      bestScore = nextScore;
      bestMove = candidate.move;
      bestPv = [candidate.move, ...childPv];
    }

    if (nextScore > localAlpha) {
      localAlpha = nextScore;
    }
    if (localAlpha >= beta) {
      break;
    }
  }

  storeExactEntry(context, key, depth, bestScore, bestMove, bestPv);
  return {
    score: bestScore,
    pv: bestPv,
  };
}

function firstLegalFallback(state, config, pack = DEFAULT_ENGINE_PACK) {
  const ranked = rankCandidateMoves(state, config, {
    candidateLimit: Math.max(1, normalizeEnginePack(pack).search.candidateLimit),
    preferredRadius: normalizeEnginePack(pack).search.preferredRadius,
    fallbackRadius: normalizeEnginePack(pack).search.fallbackRadius,
    minCount: normalizeEnginePack(pack).search.minCandidateCount,
  });
  if (ranked.length) {
    return ranked[0].move;
  }
  const legalMoves = listLegalMoves(state, config);
  return legalMoves.length ? legalMoves[0] : null;
}

export function analyzePosition({
  state,
  config,
  enginePack = DEFAULT_ENGINE_PACK,
  timeBudgetMs,
  maxDepth,
  signal,
} = {}) {
  const cleanConfig = normalizeEngineConfig(config);
  const pack = normalizeEnginePack(enginePack);
  const startedAt = now();
  const moveBudgetMs = Number.isFinite(timeBudgetMs) ? Math.max(10, Math.round(timeBudgetMs)) : pack.search.defaultMoveTimeMs;
  const depthLimit = Number.isFinite(maxDepth) ? Math.max(1, Math.round(maxDepth)) : pack.search.maxDepth;

  if (state.result) {
    const score = terminalScoreForWinner(state.result.winner, state.turn, pack, 0);
    return buildMoveSummary(null, score, [], 0, 0, startedAt, pack);
  }

  const context = {
    pack,
    signal,
    deadlineAt: startedAt + moveBudgetMs,
    nodeCount: 0,
    table: new Map(),
  };

  let bestResult = null;

  try {
    for (let depth = 1; depth <= depthLimit; depth += 1) {
      const searched = negamax(state, cleanConfig, depth, -Infinity, Infinity, state.turn, 0, context);
      bestResult = buildMoveSummary(
        searched.pv[0] || firstLegalFallback(state, cleanConfig, pack),
        searched.score,
        searched.pv,
        depth,
        context.nodeCount,
        startedAt,
        pack,
      );

      if (bestResult.mate && Math.abs(bestResult.mate) <= 1) {
        break;
      }
    }
  } catch (error) {
    if (!(error instanceof SearchAbortError)) {
      throw error;
    }
  }

  if (bestResult) {
    return bestResult;
  }

  const fallbackMove = firstLegalFallback(state, cleanConfig, pack);
  const fallbackScore = evaluateState(state, cleanConfig, pack, { perspective: state.turn });
  return buildMoveSummary(
    fallbackMove,
    fallbackScore,
    fallbackMove ? [fallbackMove] : [],
    0,
    context.nodeCount,
    startedAt,
    pack,
  );
}

export function searchMove(input = {}) {
  const analyzed = analyzePosition(input);
  return {
    ...analyzed,
    isMateScore: isMateScore(analyzed.score, input.enginePack || DEFAULT_ENGINE_PACK),
  };
}
