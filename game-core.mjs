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
export const TIMER_OPTIONS = [
  { label: "None", value: null },
  { label: "30 s", value: 30 },
  { label: "1 min", value: 60 },
  { label: "2 min", value: 120 },
  { label: "5 min", value: 300 },
];

export const mkBoard = (boardSize) => Array.from({ length: boardSize }, () => Array(boardSize).fill(null));
export const pName = (player) => (player === "B" ? "Black" : "White");
export const opp = (player) => (player === "B" ? "W" : "B");

export function sanitizeConfig(config = {}) {
  const boardSize = SIZE_OPTIONS.includes(config.boardSize) ? config.boardSize : 11;
  const validTimer = TIMER_OPTIONS.some((option) => option.value === config.timerVal);
  return {
    boardSize,
    timerVal: validTimer ? config.timerVal : null,
  };
}

export function formatTime(seconds) {
  if (seconds === null) {
    return "INF";
  }

  if (seconds >= 60) {
    return `${Math.floor(seconds / 60)}:${(seconds % 60).toString().padStart(2, "0")}`;
  }

  return `${seconds}s`;
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
    times: { B: cleanConfig.timerVal, W: cleanConfig.timerVal },
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
  const patternOfFive = findPattern(nextBoard, boardSize, state.turn, 5, [row, col]);

  if (patternOfFive) {
    return {
      ...state,
      board: nextBoard,
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
    last: [row, col],
    turn: opponent,
  };
}

export function tickClock(state, config) {
  const cleanConfig = sanitizeConfig(config);
  if (cleanConfig.timerVal === null || state.result) {
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
