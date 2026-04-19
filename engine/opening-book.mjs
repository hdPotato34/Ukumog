import { opp } from "../game-core.mjs";
import { rankCandidateMoves } from "./engine-tactics.mjs";
import { applyEngineMove, createPerspectiveState, listLegalMoves, normalizeEngineConfig } from "./rules-adapter.mjs";
import { listImmediateWinningMoves } from "./engine-tactics.mjs";

const OPENING_CACHE = new Map();
const OPENING_MAX_PLIES = 8;

const TRANSFORMS = [
  {
    name: "identity",
    apply: (size, row, col) => ({ row, col }),
    invert: (size, row, col) => ({ row, col }),
  },
  {
    name: "rot90",
    apply: (size, row, col) => ({ row: col, col: size - 1 - row }),
    invert: (size, row, col) => ({ row: size - 1 - col, col: row }),
  },
  {
    name: "rot180",
    apply: (size, row, col) => ({ row: size - 1 - row, col: size - 1 - col }),
    invert: (size, row, col) => ({ row: size - 1 - row, col: size - 1 - col }),
  },
  {
    name: "rot270",
    apply: (size, row, col) => ({ row: size - 1 - col, col: row }),
    invert: (size, row, col) => ({ row: col, col: size - 1 - row }),
  },
  {
    name: "flipH",
    apply: (size, row, col) => ({ row, col: size - 1 - col }),
    invert: (size, row, col) => ({ row, col: size - 1 - col }),
  },
  {
    name: "flipV",
    apply: (size, row, col) => ({ row: size - 1 - row, col }),
    invert: (size, row, col) => ({ row: size - 1 - row, col }),
  },
  {
    name: "diag",
    apply: (size, row, col) => ({ row: col, col: row }),
    invert: (size, row, col) => ({ row: col, col: row }),
  },
  {
    name: "antiDiag",
    apply: (size, row, col) => ({ row: size - 1 - col, col: size - 1 - row }),
    invert: (size, row, col) => ({ row: size - 1 - col, col: size - 1 - row }),
  },
];

function countStones(state) {
  let count = 0;
  for (const line of state.board) {
    for (const cell of line) {
      if (cell) count += 1;
    }
  }
  return count;
}

function transformState(state, transform) {
  const size = state.board.length;
  const board = Array.from({ length: size }, () => Array(size).fill(null));
  for (let row = 0; row < size; row += 1) {
    for (let col = 0; col < size; col += 1) {
      const cell = state.board[row][col];
      if (!cell) continue;
      const point = transform.apply(size, row, col);
      board[point.row][point.col] = cell;
    }
  }
  const last = state.last ? transform.apply(size, state.last[0], state.last[1]) : null;
  return {
    ...state,
    board,
    last: last ? [last.row, last.col] : null,
  };
}

function boardKey(state) {
  return state.board.map((line) => line.map((cell) => cell || ".").join("")).join("/");
}

function canonicalizeState(state) {
  const size = state.board.length;
  let best = null;
  for (const transform of TRANSFORMS) {
    const transformed = transformState(state, transform);
    const key = `${boardKey(transformed)}|${transformed.turn}`;
    if (!best || key < best.key) {
      best = {
        key,
        transform,
        size,
        state: transformed,
      };
    }
  }
  return best;
}

function preferredOpeningOffsets() {
  return [
    [0, 0],
    [0, -1], [-1, 0], [1, 0], [0, 1],
    [-1, -1], [1, 1], [-1, 1], [1, -1],
    [0, -2], [-2, 0], [2, 0], [0, 2],
    [-1, -2], [-2, -1], [1, 2], [2, 1],
    [-2, 1], [-1, 2], [1, -2], [2, -1],
  ];
}

function selectBookMoveForCanonicalState(state, config) {
  const cleanConfig = normalizeEngineConfig(config);
  const size = cleanConfig.boardSize;
  const middle = Math.floor((size - 1) / 2);
  const legalMoves = listLegalMoves(state, cleanConfig);
  if (!legalMoves.length) {
    return null;
  }

  const opponentState = createPerspectiveState(state, opp(state.turn));
  if (listImmediateWinningMoves(opponentState, cleanConfig).length) {
    const rankedDefense = rankCandidateMoves(state, cleanConfig, { candidateLimit: 10 });
    return rankedDefense[0]?.move || legalMoves[0] || null;
  }

  const legalKeySet = new Set(legalMoves.map((move) => `${move.row},${move.col}`));
  for (const [deltaRow, deltaCol] of preferredOpeningOffsets()) {
    const move = { row: middle + deltaRow, col: middle + deltaCol };
    if (!legalKeySet.has(`${move.row},${move.col}`)) {
      continue;
    }
    const nextState = applyEngineMove(state, cleanConfig, move);
    if (!nextState) {
      continue;
    }
    if (nextState.result && nextState.result.winner !== state.turn) {
      continue;
    }
    return move;
  }

  const ranked = rankCandidateMoves(state, cleanConfig, { candidateLimit: 10 });
  return ranked[0]?.move || legalMoves[0] || null;
}

export function getOpeningBookMove(state, config, { maxPlies = OPENING_MAX_PLIES } = {}) {
  const plyCount = countStones(state);
  if (plyCount >= maxPlies || state.result) {
    return null;
  }

  const canonical = canonicalizeState(state);
  if (!canonical) {
    return null;
  }

  if (!OPENING_CACHE.has(canonical.key)) {
    const move = selectBookMoveForCanonicalState(canonical.state, config);
    OPENING_CACHE.set(canonical.key, move);
  }

  const canonicalMove = OPENING_CACHE.get(canonical.key);
  if (!canonicalMove) {
    return null;
  }

  const restored = canonical.transform.invert(canonical.size, canonicalMove.row, canonicalMove.col);
  return { row: restored.row, col: restored.col };
}

export function getOpeningCacheStats() {
  return {
    size: OPENING_CACHE.size,
    maxPlies: OPENING_MAX_PLIES,
  };
}
