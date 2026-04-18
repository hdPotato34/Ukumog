import { createMatchState, sanitizeConfig } from "../game-core.mjs";
import { searchMove } from "../engine/engine-search.mjs";

const config = sanitizeConfig({
  boardSize: 11,
  baseSeconds: null,
  incrementSeconds: 0,
  colorMode: "black",
});

const state = createMatchState(config);
state.board[5][0] = "B";
state.board[5][1] = "B";
state.board[5][3] = "B";
state.board[5][4] = "B";
state.board[4][4] = "W";
state.board[6][6] = "W";
state.turn = "B";
state.last = [6, 6];

const result = searchMove({
  state,
  config,
  timeBudgetMs: 250,
  maxDepth: 3,
});

console.log(JSON.stringify(result, null, 2));

if (!result.bestMove || result.bestMove.row !== 5 || result.bestMove.col !== 2) {
  throw new Error("Smoke test failed: engine did not find the immediate winning move at C6-equivalent (row 5, col 2).");
}

console.log("Engine smoke test passed.");
