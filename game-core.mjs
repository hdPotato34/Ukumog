export const DIRS = [
  [0, 1],
  [1, 0],
  [1, 1],
  [1, -1],
  [1, 2],
  [1, -2],
  [2, 1],
  [2, -1],
  [1, 3],
  [1, -3],
  [3, 1],
  [3, -1],
  [2, 3],
  [2, -3],
  [3, 2],
  [3, -2],
];

export const CELL = 42;
export const MARGIN = 26;
export const PR = 15;
export const GOLD = "#e8c96a";
export const SIZE_OPTIONS = [9, 11, 13, 15];
export const COLOR_MODE_OPTIONS = [
  { label: "Black", value: "black" },
  { label: "White", value: "white" },
  { label: "Random", value: "random" },
];
export const CLOCK_PRESET_OPTIONS = [
  { id: "3+2", label: "3+2", baseSeconds: 180, incrementSeconds: 2 },
  { id: "5+3", label: "5+3", baseSeconds: 300, incrementSeconds: 3 },
  { id: "10+5", label: "10+5", baseSeconds: 600, incrementSeconds: 5 },
  { id: "15+10", label: "15+10", baseSeconds: 900, incrementSeconds: 10 },
  { id: "infinite", label: "Unlimited", baseSeconds: null, incrementSeconds: 0 },
  { id: "custom", label: "Custom", custom: true },
];
export const CUSTOM_BASE_TIME_OPTIONS = [
  30, 45, 60, 75, 90,
  120, 150, 180, 240, 300,
  360, 420, 480, 540, 600,
  720, 900, 1200, 1500, 1800,
  2400, 3000, 3600, 4500, 5400,
  6300, 7200,
];
export const DEFAULT_MATCH_CONFIG = {
  boardSize: 11,
  baseSeconds: 180,
  incrementSeconds: 2,
  colorMode: "random",
};

export const mkBoard = (boardSize) => Array.from({ length: boardSize }, () => Array(boardSize).fill(null));
export const pName = (player) => (player === "B" ? "Black" : "White");
export const opp = (player) => (player === "B" ? "W" : "B");

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

export function nearestBaseTime(seconds) {
  const numeric = Number(seconds);
  if (!Number.isFinite(numeric)) {
    return CUSTOM_BASE_TIME_OPTIONS[0];
  }
  return CUSTOM_BASE_TIME_OPTIONS.reduce((closest, candidate) => (
    Math.abs(candidate - numeric) < Math.abs(closest - numeric) ? candidate : closest
  ), CUSTOM_BASE_TIME_OPTIONS[0]);
}

export function sanitizeConfig(config = {}) {
  const boardSize = SIZE_OPTIONS.includes(config.boardSize) ? config.boardSize : 11;
  const colorMode = COLOR_MODE_OPTIONS.some((option) => option.value === config.colorMode) ? config.colorMode : DEFAULT_MATCH_CONFIG.colorMode;
  const legacyBaseSeconds = config.baseSeconds !== undefined ? config.baseSeconds : config.timerVal;
  const rawBaseSeconds = legacyBaseSeconds === null ? null : Number(legacyBaseSeconds);
  const baseSeconds = rawBaseSeconds === null
    ? null
    : Number.isFinite(rawBaseSeconds)
      ? nearestBaseTime(clamp(rawBaseSeconds, CUSTOM_BASE_TIME_OPTIONS[0], CUSTOM_BASE_TIME_OPTIONS[CUSTOM_BASE_TIME_OPTIONS.length - 1]))
      : DEFAULT_MATCH_CONFIG.baseSeconds;
  const rawIncrementSeconds = Number(config.incrementSeconds ?? 0);
  const incrementSeconds = baseSeconds === null
    ? 0
    : Number.isFinite(rawIncrementSeconds)
      ? clamp(Math.round(rawIncrementSeconds), 0, 60)
      : DEFAULT_MATCH_CONFIG.incrementSeconds;
  return {
    boardSize,
    baseSeconds,
    incrementSeconds,
    colorMode,
  };
}

export function formatTime(seconds) {
  if (seconds === null) {
    return "INF";
  }

  if (seconds >= 3600) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainder = seconds % 60;
    return `${hours}:${minutes.toString().padStart(2, "0")}:${remainder.toString().padStart(2, "0")}`;
  }

  if (seconds >= 60) {
    return `${Math.floor(seconds / 60)}:${(seconds % 60).toString().padStart(2, "0")}`;
  }

  return `${seconds}s`;
}

export function formatClockSetting(config = {}) {
  const cleanConfig = sanitizeConfig(config);
  if (cleanConfig.baseSeconds === null) {
    return "Unlimited";
  }
  const baseLabel = cleanConfig.baseSeconds < 60
    ? `${cleanConfig.baseSeconds}s`
    : cleanConfig.baseSeconds % 60 === 0
      ? `${Math.round(cleanConfig.baseSeconds / 60)}`
      : `${cleanConfig.baseSeconds}s`;
  return `${baseLabel}+${cleanConfig.incrementSeconds}`;
}

export function formatColorSetting(config = {}) {
  const cleanConfig = sanitizeConfig(config);
  if (cleanConfig.colorMode === "black") return "Host plays Black";
  if (cleanConfig.colorMode === "white") return "Host plays White";
  return "Random colors";
}

export function starPoints(boardSize) {
  const distance = boardSize <= 10 ? 2 : 3;
  const middle = Math.floor((boardSize - 1) / 2);
  const far = boardSize - 1 - distance;
  return [distance, middle, far].flatMap((row) => [distance, middle, far].map((col) => [row, col]));
}

export function findPattern(board, boardSize, color, length, mustInclude) {
  for (const [deltaRow, deltaCol] of DIRS) {
    for (let distance = 1; distance < boardSize; distance += 1) {
      const stepRow = deltaRow * distance;
      const stepCol = deltaCol * distance;

      for (let row = 0; row < boardSize; row += 1) {
        for (let col = 0; col < boardSize; col += 1) {
          const endRow = row + (length - 1) * stepRow;
          const endCol = col + (length - 1) * stepCol;

          if (endRow < 0 || endRow >= boardSize || endCol < 0 || endCol >= boardSize) {
            continue;
          }

          let valid = true;
          let includesPlacedStone = false;
          const cells = [];

          for (let index = 0; index < length; index += 1) {
            const pointRow = row + index * stepRow;
            const pointCol = col + index * stepCol;

            if (board[pointRow][pointCol] !== color) {
              valid = false;
              break;
            }

            if (pointRow === mustInclude[0] && pointCol === mustInclude[1]) {
              includesPlacedStone = true;
            }

            cells.push([pointRow, pointCol]);
          }

          if (valid && includesPlacedStone) {
            return cells;
          }
        }
      }
    }
  }

  return null;
}

export function createMatchState(config) {
  const cleanConfig = sanitizeConfig(config);
  return {
    board: mkBoard(cleanConfig.boardSize),
    turn: "B",
    times: { B: cleanConfig.baseSeconds, W: cleanConfig.baseSeconds },
    result: null,
    last: null,
  };
}

export function applyMove(state, config, row, col) {
  const cleanConfig = sanitizeConfig(config);
  const boardSize = cleanConfig.boardSize;

  if (state.result || row < 0 || col < 0 || row >= boardSize || col >= boardSize || state.board[row][col]) {
    return null;
  }

  const nextBoard = state.board.map((line) => [...line]);
  nextBoard[row][col] = state.turn;
  const opponent = opp(state.turn);
  const nextTimes = cleanConfig.baseSeconds === null
    ? { ...state.times }
    : {
      ...state.times,
      [state.turn]: Math.max(0, (state.times[state.turn] ?? 0) + cleanConfig.incrementSeconds),
    };
  const patternOfFive = findPattern(nextBoard, boardSize, state.turn, 5, [row, col]);

  if (patternOfFive) {
    return {
      ...state,
      board: nextBoard,
      times: nextTimes,
      last: [row, col],
      result: {
        winner: state.turn,
        msg: `${pName(state.turn)} forms a pattern of five`,
        sub: "wins the game!",
        highlight: patternOfFive,
      },
    };
  }

  const patternOfFour = findPattern(nextBoard, boardSize, state.turn, 4, [row, col]);
  if (patternOfFour) {
    return {
      ...state,
      board: nextBoard,
      times: nextTimes,
      last: [row, col],
      result: {
        winner: opponent,
        msg: `${pName(state.turn)} formed a pattern of four`,
        sub: `${pName(opponent)} wins!`,
        highlight: patternOfFour,
      },
    };
  }

  return {
    ...state,
    board: nextBoard,
    times: nextTimes,
    last: [row, col],
    turn: opponent,
  };
}

export function tickClock(state, config) {
  const cleanConfig = sanitizeConfig(config);
  if (cleanConfig.baseSeconds === null || state.result) {
    return state;
  }

  const currentTime = state.times[state.turn];
  if (currentTime === null) {
    return state;
  }

  const nextTime = Math.max(0, currentTime - 1);
  if (nextTime === currentTime) {
    return state;
  }

  const nextTimes = { ...state.times, [state.turn]: nextTime };
  if (nextTime > 0) {
    return {
      ...state,
      times: nextTimes,
    };
  }

  const loser = state.turn;
  return {
    ...state,
    times: nextTimes,
    result: {
      winner: opp(loser),
      msg: `${pName(loser)}'s time ran out`,
      sub: `${pName(opp(loser))} wins!`,
      highlight: [],
    },
  };
}
