import { applyMove, createMatchState, opp, sanitizeConfig } from "../game-core.mjs";

export const EMPTY_MOVE_LIST = Object.freeze([]);

export function normalizeEngineConfig(config = {}) {
  return sanitizeConfig(config);
}

export function cloneMove(move) {
  if (!move) return null;
  return { row: move.row, col: move.col };
}

export function cloneState(state) {
  return {
    ...state,
    board: state.board.map((line) => [...line]),
    times: { ...(state.times || {}) },
    last: state.last ? [...state.last] : null,
    result: state.result
      ? {
        ...state.result,
        highlight: Array.isArray(state.result.highlight)
          ? state.result.highlight.map((point) => [...point])
          : [],
      }
      : null,
  };
}

export function createEngineState(config) {
  return createMatchState(normalizeEngineConfig(config));
}

export function moveKey(move) {
  return `${move.row},${move.col}`;
}

export function sameMove(left, right) {
  return !!left && !!right && left.row === right.row && left.col === right.col;
}

export function countOccupiedStones(state) {
  let count = 0;
  for (const line of state.board) {
    for (const cell of line) {
      if (cell) count += 1;
    }
  }
  return count;
}

export function listLegalMoves(state, config) {
  const cleanConfig = normalizeEngineConfig(config);
  if (state.result) {
    return EMPTY_MOVE_LIST;
  }

  const moves = [];
  for (let row = 0; row < cleanConfig.boardSize; row += 1) {
    for (let col = 0; col < cleanConfig.boardSize; col += 1) {
      if (!state.board[row][col]) {
        moves.push({ row, col });
      }
    }
  }
  return moves;
}

export function applyEngineMove(state, config, move) {
  if (!move) return null;
  return applyMove(state, normalizeEngineConfig(config), move.row, move.col);
}

export function hasNearbyStone(state, row, col, radius = 2) {
  const boardSize = state.board.length;
  for (let deltaRow = -radius; deltaRow <= radius; deltaRow += 1) {
    for (let deltaCol = -radius; deltaCol <= radius; deltaCol += 1) {
      if (deltaRow === 0 && deltaCol === 0) continue;
      const nextRow = row + deltaRow;
      const nextCol = col + deltaCol;
      if (nextRow < 0 || nextCol < 0 || nextRow >= boardSize || nextCol >= boardSize) continue;
      if (state.board[nextRow][nextCol]) {
        return true;
      }
    }
  }
  return false;
}

export function countNearbyStones(state, row, col, radius = 1) {
  const boardSize = state.board.length;
  let friendly = 0;
  let opponent = 0;
  for (let deltaRow = -radius; deltaRow <= radius; deltaRow += 1) {
    for (let deltaCol = -radius; deltaCol <= radius; deltaCol += 1) {
      if (deltaRow === 0 && deltaCol === 0) continue;
      const nextRow = row + deltaRow;
      const nextCol = col + deltaCol;
      if (nextRow < 0 || nextCol < 0 || nextRow >= boardSize || nextCol >= boardSize) continue;
      const cell = state.board[nextRow][nextCol];
      if (cell === state.turn) friendly += 1;
      else if (cell === opp(state.turn)) opponent += 1;
    }
  }
  return { friendly, opponent };
}

export function localMoveCandidates(state, config, {
  preferredRadius = 2,
  fallbackRadius = 3,
  minCount = 8,
} = {}) {
  const legalMoves = listLegalMoves(state, config);
  if (legalMoves.length <= 1) {
    return legalMoves;
  }

  if (countOccupiedStones(state) === 0) {
    const boardSize = normalizeEngineConfig(config).boardSize;
    const middle = Math.floor((boardSize - 1) / 2);
    return [{ row: middle, col: middle }];
  }

  let nearby = legalMoves.filter((move) => hasNearbyStone(state, move.row, move.col, preferredRadius));
  if (nearby.length >= minCount) {
    return nearby;
  }

  nearby = legalMoves.filter((move) => hasNearbyStone(state, move.row, move.col, fallbackRadius));
  return nearby.length ? nearby : legalMoves;
}

export function createPerspectiveState(state, turn) {
  return {
    ...cloneState(state),
    turn,
    result: state.result ? { ...state.result } : null,
  };
}

export function hashState(state) {
  const rows = state.board.map((line) => line.map((cell) => cell || ".").join("")).join("/");
  const resultKey = state.result ? `${state.result.winner}:${state.result.msg || ""}` : "-";
  return `${rows}|${state.turn}|${resultKey}`;
}
