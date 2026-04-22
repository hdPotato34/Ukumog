import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { applyMove, createMatchState } from "../game-core.mjs";

const ROOT_DIR = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const ENGINE_ROOT = path.join(ROOT_DIR, "ukumog-engine");
const SUPPORTED_BOARD_SIZES = [9, 11, 13, 15];
const BASE_CONFIG = {
  baseSeconds: null,
  incrementSeconds: 0,
  colorMode: "black",
};

const PYTHON_COMPARE_SCRIPT = String.raw`
import json
import sys

from ukumog_engine import Color, Position, coord_to_index, generate_masks, play_move


def color_to_token(color):
    return "B" if color is Color.BLACK else "W"


def position_to_rows(position):
    rows = []
    board_size = position.board_size
    for row in range(board_size):
        chars = []
        for col in range(board_size):
            index = row * board_size + col
            mask = 1 << index
            if position.black_bits & mask:
                chars.append("B")
            elif position.white_bits & mask:
                chars.append("W")
            else:
                chars.append(".")
        rows.append("".join(chars))
    return rows


payload = json.loads(sys.stdin.read())
results = []
for case in payload["cases"]:
    turn = Color.BLACK if case["turn"] == "B" else Color.WHITE
    try:
        position = Position.from_rows(case["rows"], side_to_move=turn, board_size=case["boardSize"])
        move = coord_to_index(case["move"]["row"], case["move"]["col"], case["boardSize"])
        tables = generate_masks(case["boardSize"])
        next_position, result = play_move(position, move, tables)
        results.append(
            {
                "status": "legal",
                "outcome": result.name,
                "rows": position_to_rows(next_position),
                "nextTurn": color_to_token(next_position.side_to_move) if result.name == "NONTERMINAL" else None,
            }
        )
    except Exception as exc:
        results.append(
            {
                "status": "illegal",
                "error": str(exc),
            }
        )

print(json.dumps({"results": results}))
`;

function createMulberry32(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6D2B79F5) >>> 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t ^= t + Math.imul(t ^ (t >>> 7), 61 | t);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function shuffle(items, rng) {
  const next = [...items];
  for (let index = next.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(rng() * (index + 1));
    [next[index], next[swapIndex]] = [next[swapIndex], next[index]];
  }
  return next;
}

function createConfig(boardSize) {
  return {
    ...BASE_CONFIG,
    boardSize,
  };
}

function createEmptyRows(boardSize) {
  return Array.from({ length: boardSize }, () => ".".repeat(boardSize));
}

function placeTokens(boardSize, placements = []) {
  const rows = createEmptyRows(boardSize).map((row) => [...row]);
  placements.forEach(({ row, col, token = "B" }) => {
    rows[row][col] = token;
  });
  return rows.map((row) => row.join(""));
}

function stateFromRows(rows, turn = "B") {
  return {
    board: rows.map((row) => [...row].map((cell) => (cell === "." ? null : cell))),
    turn,
    times: { B: null, W: null },
    result: null,
    last: null,
  };
}

function boardToRows(board) {
  return board.map((row) => row.map((cell) => cell || ".").join(""));
}

function allLegalMoves(state, boardSize) {
  const moves = [];
  for (let row = 0; row < boardSize; row += 1) {
    for (let col = 0; col < boardSize; col += 1) {
      if (!state.board[row][col]) {
        moves.push({ row, col });
      }
    }
  }
  return moves;
}

function occupiedMoves(state, boardSize) {
  const moves = [];
  for (let row = 0; row < boardSize; row += 1) {
    for (let col = 0; col < boardSize; col += 1) {
      if (state.board[row][col]) {
        moves.push({ row, col });
      }
    }
  }
  return moves;
}

function moveToNotation(move) {
  return `${String.fromCharCode(65 + move.col)}${move.row + 1}`;
}

function evaluateJsCase(caseDefinition) {
  const state = stateFromRows(caseDefinition.rows, caseDefinition.turn);
  const nextState = applyMove(state, caseDefinition.config, caseDefinition.move.row, caseDefinition.move.col);
  if (!nextState) {
    return {
      status: "illegal",
    };
  }

  const outcome = !nextState.result
    ? "NONTERMINAL"
    : nextState.result.winner === state.turn
      ? "WIN"
      : "LOSS";

  return {
    status: "legal",
    outcome,
    rows: boardToRows(nextState.board),
    nextTurn: nextState.result ? null : nextState.turn,
  };
}

function buildFixedCasesForBoard(boardSize) {
  const config = createConfig(boardSize);
  const middle = Math.floor(boardSize / 2);
  return [
    {
      id: `${boardSize}-illegal-occupied-cell`,
      category: "fixed-illegal",
      description: "occupied cell should be rejected",
      boardSize,
      config,
      rows: placeTokens(boardSize, [{ row: middle, col: middle, token: "B" }]),
      turn: "W",
      move: { row: middle, col: middle },
    },
    {
      id: `${boardSize}-illegal-out-of-bounds`,
      category: "fixed-illegal",
      description: "out of bounds should be rejected",
      boardSize,
      config,
      rows: createEmptyRows(boardSize),
      turn: "B",
      move: { row: boardSize, col: 0 },
    },
    {
      id: `${boardSize}-simple-five-win`,
      category: "fixed-terminal",
      description: "forming five should win immediately",
      boardSize,
      config,
      rows: placeTokens(boardSize, [
        { row: middle, col: 0, token: "B" },
        { row: middle, col: 2, token: "B" },
        { row: middle, col: 4, token: "B" },
        { row: middle, col: 6, token: "B" },
      ]),
      turn: "B",
      move: { row: middle, col: 8 },
    },
    {
      id: `${boardSize}-simple-four-loss`,
      category: "fixed-terminal",
      description: "forming four should lose immediately",
      boardSize,
      config,
      rows: placeTokens(boardSize, [
        { row: middle, col: 0, token: "B" },
        { row: middle, col: 2, token: "B" },
        { row: middle, col: 4, token: "B" },
      ]),
      turn: "B",
      move: { row: middle, col: 6 },
    },
    {
      id: `${boardSize}-five-overrides-four`,
      category: "fixed-terminal",
      description: "five takes priority over four when both appear",
      boardSize,
      config,
      rows: placeTokens(boardSize, [
        { row: 2, col: 2, token: "B" },
        { row: 3, col: 3, token: "B" },
        { row: 4, col: 4, token: "B" },
        { row: 5, col: 5, token: "B" },
        { row: 6, col: 1, token: "B" },
        { row: 6, col: boardSize - 1, token: "B" },
      ]),
      turn: "B",
      move: { row: 6, col: 6 },
    },
    {
      id: `${boardSize}-gapped-progression-win`,
      category: "fixed-terminal",
      description: "arithmetic progression of five counts as a win",
      boardSize,
      config,
      rows: placeTokens(boardSize, [
        { row: 0, col: 0, token: "B" },
        { row: 2, col: 2, token: "B" },
        { row: 4, col: 4, token: "B" },
        { row: 6, col: 6, token: "B" },
      ]),
      turn: "B",
      move: { row: 8, col: 8 },
    },
    {
      id: `${boardSize}-negative-slope-four-loss`,
      category: "fixed-terminal",
      description: "negative slope arithmetic four counts as a loss",
      boardSize,
      config,
      rows: placeTokens(boardSize, [
        { row: 2, col: boardSize - 3, token: "B" },
        { row: 3, col: boardSize - 5, token: "B" },
        { row: 4, col: boardSize - 7, token: "B" },
      ]),
      turn: "B",
      move: { row: 5, col: boardSize - 9 },
    },
  ];
}

function buildRandomCases() {
  const rng = createMulberry32(20260421);
  const cases = [];
  let generatedStates = 0;
  let attempts = 0;

  for (const boardSize of SUPPORTED_BOARD_SIZES) {
    const config = createConfig(boardSize);
    let perBoardStates = 0;

    while (perBoardStates < 6 && attempts < 480) {
      attempts += 1;
      let state = createMatchState(config);
      const plies = 2 + Math.floor(rng() * 16);
      let valid = true;

      for (let ply = 0; ply < plies; ply += 1) {
        const legalMoves = allLegalMoves(state, boardSize);
        const move = legalMoves[Math.floor(rng() * legalMoves.length)];
        const nextState = applyMove(state, config, move.row, move.col);
        if (!nextState || nextState.result) {
          valid = false;
          break;
        }
        state = nextState;
      }

      if (!valid) {
        continue;
      }

      generatedStates += 1;
      perBoardStates += 1;
      const rows = boardToRows(state.board);
      const legalMoves = shuffle(allLegalMoves(state, boardSize), rng).slice(0, 10);
      const illegalMoves = shuffle(occupiedMoves(state, boardSize), rng).slice(0, 1);

      legalMoves.forEach((move, index) => {
        cases.push({
          id: `${boardSize}-random-${generatedStates}-legal-${index + 1}`,
          category: "random-legal",
          description: `random legal sample ${generatedStates}.${index + 1}`,
          boardSize,
          config,
          rows,
          turn: state.turn,
          move,
        });
      });

      illegalMoves.forEach((move, index) => {
        cases.push({
          id: `${boardSize}-random-${generatedStates}-illegal-${index + 1}`,
          category: "random-illegal",
          description: `random occupied sample ${generatedStates}.${index + 1}`,
          boardSize,
          config,
          rows,
          turn: state.turn,
          move,
        });
      });
    }
  }

  return cases;
}

function runPythonComparison(cases) {
  const candidates = process.env.PYTHON
    ? [{ command: process.env.PYTHON, args: ["-c", PYTHON_COMPARE_SCRIPT] }]
    : process.platform === "win32"
      ? [
        { command: "python", args: ["-c", PYTHON_COMPARE_SCRIPT] },
        { command: "py", args: ["-3", "-c", PYTHON_COMPARE_SCRIPT] },
      ]
      : [
        { command: "python3", args: ["-c", PYTHON_COMPARE_SCRIPT] },
        { command: "python", args: ["-c", PYTHON_COMPARE_SCRIPT] },
      ];

  for (const candidate of candidates) {
    const result = spawnSync(candidate.command, candidate.args, {
      cwd: ENGINE_ROOT,
      input: JSON.stringify({ cases }),
      encoding: "utf8",
      env: {
        ...process.env,
        PYTHONUTF8: "1",
      },
    });

    if (result.error?.code === "ENOENT") {
      continue;
    }

    if (result.error) {
      throw result.error;
    }

    if (result.status !== 0) {
      throw new Error(result.stderr || `Python comparison exited with status ${result.status}.`);
    }

    const payload = JSON.parse(result.stdout);
    if (!Array.isArray(payload.results) || payload.results.length !== cases.length) {
      throw new Error("Python comparison returned an unexpected payload.");
    }

    return {
      interpreter: candidate.command,
      results: payload.results,
    };
  }

  throw new Error("Could not find a usable Python interpreter for ukumog-engine comparison.");
}

function compareResults(cases, pythonResults) {
  const mismatches = [];

  cases.forEach((caseDefinition, index) => {
    const js = evaluateJsCase(caseDefinition);
    const py = pythonResults[index];
    const sameStatus = js.status === py.status;
    const sameOutcome = js.status !== "legal" || js.outcome === py.outcome;
    const sameRows = js.status !== "legal" || JSON.stringify(js.rows) === JSON.stringify(py.rows);
    const sameTurn = js.status !== "legal" || js.nextTurn === py.nextTurn;

    if (sameStatus && sameOutcome && sameRows && sameTurn) {
      return;
    }

    mismatches.push({
      caseDefinition,
      js,
      py,
    });
  });

  return mismatches;
}

function printMismatch(mismatch) {
  const { caseDefinition, js, py } = mismatch;
  console.error(`Mismatch: ${caseDefinition.id} (${caseDefinition.description}) board=${caseDefinition.boardSize}`);
  console.error(`Move: ${moveToNotation(caseDefinition.move)} row=${caseDefinition.move.row} col=${caseDefinition.move.col} turn=${caseDefinition.turn}`);
  console.error("Board:");
  caseDefinition.rows.forEach((row) => console.error(`  ${row}`));
  console.error(`JS: ${JSON.stringify(js)}`);
  console.error(`PY: ${JSON.stringify(py)}`);
  console.error("");
}

function summarizeByCategory(cases) {
  return cases.reduce((summary, caseDefinition) => {
    summary[caseDefinition.category] = (summary[caseDefinition.category] || 0) + 1;
    return summary;
  }, {});
}

function main() {
  const fixedCases = SUPPORTED_BOARD_SIZES.flatMap((boardSize) => buildFixedCasesForBoard(boardSize));
  const randomCases = buildRandomCases();
  const cases = [...fixedCases, ...randomCases];
  const { interpreter, results } = runPythonComparison(cases);
  const mismatches = compareResults(cases, results);

  if (mismatches.length > 0) {
    mismatches.slice(0, 8).forEach(printMismatch);
    console.error(`Rule comparison failed with ${mismatches.length} mismatches out of ${cases.length} cases.`);
    process.exitCode = 1;
    return;
  }

  const byCategory = summarizeByCategory(cases);
  console.log(`Rule comparison passed with ${cases.length} cases via ${interpreter}.`);
  Object.entries(byCategory)
    .sort(([left], [right]) => left.localeCompare(right))
    .forEach(([category, count]) => {
      console.log(`- ${category}: ${count}`);
    });
}

main();
