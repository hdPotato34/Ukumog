import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import net from "node:net";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";

import { createMatchState } from "../game-core.mjs";
import { RemoteEngineClient } from "../engine/engine-client.mjs";
import { moveToNotation } from "../game-record.mjs";
import { analysisBarPercent, formatAnalysisScore } from "../review-analysis.mjs";

const ROOT_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SERVING_DIR = path.join(ROOT_DIR, "model-server", "src", "serving");
const UKUMOG_DIR = path.join(ROOT_DIR, "ukumog-engine");
const DEFAULT_CONFIG = {
  boardSize: 11,
  baseSeconds: null,
  incrementSeconds: 0,
  colorMode: "black",
};

function windowsPath(input) {
  return process.platform === "win32" && input.startsWith("/") ? input.slice(1) : input;
}

const servingDir = windowsPath(SERVING_DIR);
const ukumogDir = windowsPath(UKUMOG_DIR);

function createEmptyBoard(boardSize = 11) {
  return Array.from({ length: boardSize }, () => Array(boardSize).fill(null));
}

function isInteger(value) {
  return Number.isInteger(value);
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        server.close(() => reject(new Error("Could not determine a free local port.")));
        return;
      }
      const { port } = address;
      server.close((error) => {
        if (error) {
          reject(error);
          return;
        }
        resolve(port);
      });
    });
  });
}

function captureProcess(command, args, options = {}) {
  const child = spawn(command, args, {
    ...options,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });

  let stdout = "";
  let stderr = "";
  child.stdout?.on("data", (chunk) => {
    stdout = `${stdout}${chunk}`.slice(-8000);
  });
  child.stderr?.on("data", (chunk) => {
    stderr = `${stderr}${chunk}`.slice(-8000);
  });

  return {
    child,
    logs() {
      return {
        stdout: stdout.trim(),
        stderr: stderr.trim(),
      };
    },
  };
}

async function stopProcess(proc) {
  if (!proc || proc.exitCode !== null || proc.killed) {
    return;
  }

  try {
    proc.kill();
  } catch {
    return;
  }

  const startedAt = Date.now();
  while (proc.exitCode === null && Date.now() - startedAt < 5000) {
    await delay(50);
  }

  if (proc.exitCode === null) {
    try {
      proc.kill("SIGKILL");
    } catch {
      // Ignore forced shutdown errors.
    }
  }
}

async function waitForJson(url, timeoutMs, label) {
  const startedAt = Date.now();
  let lastError = null;

  while (Date.now() - startedAt < timeoutMs) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (response.ok) {
        return await response.json();
      }
      lastError = new Error(`${label} returned HTTP ${response.status}.`);
    } catch (error) {
      lastError = error;
    }
    await delay(120);
  }

  throw new Error(`Timed out waiting for ${label}.${lastError ? ` Last error: ${lastError.message}` : ""}`);
}

function resolvePythonCandidate() {
  const verificationScript = [
    "import sys",
    `sys.path[:0] = [r"${servingDir}", r"${ukumogDir}"]`,
    "import fastapi, pydantic, uvicorn, app, ukumog_engine",
    "print(sys.version.split()[0])",
  ].join("; ");

  const candidates = process.env.PYTHON
    ? [{ command: process.env.PYTHON, args: [] }]
    : process.platform === "win32"
      ? [
        { command: "python", args: [] },
        { command: "py", args: ["-3"] },
      ]
      : [
        { command: "python3", args: [] },
        { command: "python", args: [] },
      ];

  for (const candidate of candidates) {
    const result = spawnSync(candidate.command, [...candidate.args, "-c", verificationScript], {
      cwd: ROOT_DIR,
      encoding: "utf8",
      env: {
        ...process.env,
        PYTHONPATH: [servingDir, ukumogDir, process.env.PYTHONPATH || ""].filter(Boolean).join(path.delimiter),
      },
    });

    if (result.error?.code === "ENOENT") {
      continue;
    }
    if (result.status === 0) {
      return candidate;
    }
  }

  throw new Error("Could not find a Python interpreter that can import fastapi, app, and ukumog_engine.");
}

function validateMovePayload(move, label, boardSize = 11) {
  assert.ok(move && typeof move === "object", `${label} should be an object.`);
  assert.ok(isInteger(move.row) && move.row >= 0 && move.row < boardSize, `${label}.row should be within the board.`);
  assert.ok(isInteger(move.col) && move.col >= 0 && move.col < boardSize, `${label}.col should be within the board.`);
  assert.equal(move.notation, moveToNotation(move.row, move.col), `${label}.notation should match row/col.`);
}

function validateAnalysisPayload(analysis, label, boardSize = 11) {
  assert.ok(analysis && typeof analysis === "object", `${label} should be an object.`);
  assert.equal(analysis.backend, "ukumog", `${label}.backend should identify ukumog.`);
  assert.equal(typeof analysis.engineVersion, "string", `${label}.engineVersion should be a string.`);
  assert.ok(analysis.engineVersion.length > 0, `${label}.engineVersion should not be empty.`);
  assert.ok(isInteger(analysis.score), `${label}.score should be an integer.`);
  assert.ok(analysis.mate === null || isInteger(analysis.mate), `${label}.mate should be null or an integer.`);
  assert.ok(isInteger(analysis.depth) && analysis.depth > 0, `${label}.depth should be a positive integer.`);
  assert.ok(isInteger(analysis.nodes) && analysis.nodes >= 0, `${label}.nodes should be a non-negative integer.`);
  assert.ok(isInteger(analysis.timeMs) && analysis.timeMs >= 0, `${label}.timeMs should be a non-negative integer.`);
  assert.ok(Array.isArray(analysis.pv), `${label}.pv should be an array.`);
  assert.ok(analysis.pv.length > 0, `${label}.pv should not be empty.`);
  analysis.pv.forEach((move, index) => validateMovePayload(move, `${label}.pv[${index}]`, boardSize));
  if (analysis.bestMove) {
    validateMovePayload(analysis.bestMove, `${label}.bestMove`, boardSize);
  }

  const scoreText = formatAnalysisScore(analysis);
  const barPercent = analysisBarPercent(analysis);
  const pvText = analysis.pv.map((move) => move.notation || moveToNotation(move.row, move.col)).join(" ");
  assert.equal(typeof scoreText, "string", `${label} should be consumable by formatAnalysisScore().`);
  assert.equal(typeof pvText, "string", `${label}.pv should be renderable as notation text.`);
  assert.ok(Number.isFinite(barPercent) && barPercent >= 0 && barPercent <= 100, `${label} should be consumable by analysisBarPercent().`);
}

async function createGuestToken(nodeOrigin) {
  const response = await fetch(`${nodeOrigin}/api/auth/guest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ displayName: "Contract Smoke" }),
  });
  assert.equal(response.status, 201, "Guest session creation should succeed.");
  const payload = await response.json();
  assert.equal(typeof payload.sessionToken, "string", "Guest session should return a session token.");
  assert.ok(payload.sessionToken.length > 0, "Guest session token should not be empty.");
  return payload.sessionToken;
}

async function main() {
  const pythonCandidate = resolvePythonCandidate();
  const pythonPort = await findFreePort();
  const nodePort = await findFreePort();
  const pythonOrigin = `http://127.0.0.1:${pythonPort}`;
  const nodeOrigin = `http://127.0.0.1:${nodePort}`;

  const pythonProcess = captureProcess(
    pythonCandidate.command,
    [
      ...pythonCandidate.args,
      "-m",
      "uvicorn",
      "app:app",
      "--app-dir",
      servingDir,
      "--host",
      "127.0.0.1",
      "--port",
      String(pythonPort),
    ],
    {
      cwd: ROOT_DIR,
      env: {
        ...process.env,
        PYTHONPATH: [servingDir, ukumogDir, process.env.PYTHONPATH || ""].filter(Boolean).join(path.delimiter),
      },
    },
  );

  const nodeProcess = captureProcess(
    process.execPath,
    ["server.mjs"],
    {
      cwd: ROOT_DIR,
      env: {
        ...process.env,
        PORT: String(nodePort),
        HOST: "127.0.0.1",
        ENGINE_SERVICE_ORIGIN: pythonOrigin,
        ENGINE_SERVICE_TIMEOUT_MS: "15000",
      },
    },
  );

  try {
    const pythonHealth = await waitForJson(`${pythonOrigin}/health`, 15000, "Python engine health");
    assert.equal(pythonHealth.ok, true, "Python engine health should report ok.");
    assert.deepEqual(pythonHealth.capabilities?.supportedBoardSizes, [9, 11, 13, 15], "Python engine health should expose supported board sizes.");
    assert.equal(pythonHealth.capabilities?.timeBudgetMs?.min, 25, "Python engine health should expose the minimum time budget.");
    assert.equal(pythonHealth.capabilities?.maxDepth?.max, 12, "Python engine health should expose the maximum search depth.");

    const nodeHealth = await waitForJson(`${nodeOrigin}/api/engine/health`, 15000, "Node engine health proxy");
    assert.equal(nodeHealth.ok, true, "Node proxy health should report ok.");
    assert.equal(nodeHealth.backend, "ukumog", "Node proxy health should surface the engine backend.");
    assert.equal(typeof nodeHealth.pythonVersion, "string", "Node proxy health should surface pythonVersion.");
    assert.deepEqual(nodeHealth.capabilities?.supportedBoardSizes, [9, 11, 13, 15], "Node proxy health should surface supported board sizes.");
    assert.equal(nodeHealth.capabilities?.timeBudgetMs?.max, 5000, "Node proxy health should surface the maximum time budget.");
    assert.equal(nodeHealth.capabilities?.maxDepth?.min, 1, "Node proxy health should surface the minimum search depth.");

    const token = await createGuestToken(nodeOrigin);
    const authenticatedClient = new RemoteEngineClient({
      serverUrl: nodeOrigin,
      getSessionToken: () => token,
    });

    const anonymousClient = new RemoteEngineClient({
      serverUrl: nodeOrigin,
      getSessionToken: () => "",
    });

    const emptyState = createMatchState(DEFAULT_CONFIG);
    const analyzeEmpty = await authenticatedClient.analyzePosition({
      state: emptyState,
      config: DEFAULT_CONFIG,
      timeBudgetMs: 160,
      maxDepth: 2,
    });
    validateAnalysisPayload(analyzeEmpty, "analyze(empty)");
    assert.ok(analyzeEmpty.bestMove, "analyze(empty) should return a bestMove.");
    assert.deepEqual(
      { row: analyzeEmpty.bestMove.row, col: analyzeEmpty.bestMove.col },
      { row: 5, col: 5 },
      "analyze(empty) should point at the center move on the opening position.",
    );

    const nineConfig = { ...DEFAULT_CONFIG, boardSize: 9 };
    const nineEmptyState = createMatchState(nineConfig);
    const analyzeNine = await authenticatedClient.analyzePosition({
      state: nineEmptyState,
      config: nineConfig,
      timeBudgetMs: 160,
      maxDepth: 2,
    });
    validateAnalysisPayload(analyzeNine, "analyze(9x9-empty)", 9);
    assert.ok(analyzeNine.bestMove, "analyze(9x9-empty) should return a bestMove.");
    assert.deepEqual(
      { row: analyzeNine.bestMove.row, col: analyzeNine.bestMove.col },
      { row: 4, col: 4 },
      "analyze(9x9-empty) should point at the center move on the opening position.",
    );

    const winningBoard = createEmptyBoard();
    for (const col of [0, 2, 4, 6]) {
      winningBoard[5][col] = "B";
    }
    const winningState = {
      board: winningBoard,
      turn: "B",
      result: null,
      last: null,
      times: { B: null, W: null },
    };
    const searchWinning = await authenticatedClient.searchMove({
      state: winningState,
      config: DEFAULT_CONFIG,
      timeBudgetMs: 180,
      maxDepth: 2,
    });
    validateAnalysisPayload(searchWinning, "search(immediate-win)");
    assert.ok(searchWinning.bestMove, "search(immediate-win) should return a bestMove.");
    assert.deepEqual(
      { row: searchWinning.bestMove.row, col: searchWinning.bestMove.col },
      { row: 5, col: 8 },
      "search(immediate-win) should return the winning move.",
    );
    assert.deepEqual(
      { row: searchWinning.pv[0].row, col: searchWinning.pv[0].col },
      { row: 5, col: 8 },
      "search(immediate-win) should start PV with the winning move.",
    );

    const forcedBlockBoard = createEmptyBoard();
    for (const col of [0, 2, 4, 6]) {
      forcedBlockBoard[5][col] = "W";
    }
    const forcedBlockState = {
      board: forcedBlockBoard,
      turn: "B",
      result: null,
      last: null,
      times: { B: null, W: null },
    };
    const searchForcedBlock = await authenticatedClient.searchMove({
      state: forcedBlockState,
      config: DEFAULT_CONFIG,
      timeBudgetMs: 180,
      maxDepth: 1,
    });
    validateAnalysisPayload(searchForcedBlock, "search(forced-block)");
    assert.ok(searchForcedBlock.bestMove, "search(forced-block) should return a bestMove.");
    assert.deepEqual(
      { row: searchForcedBlock.bestMove.row, col: searchForcedBlock.bestMove.col },
      { row: 5, col: 8 },
      "search(forced-block) should choose the only safe block.",
    );
    assert.deepEqual(
      { row: searchForcedBlock.pv[0].row, col: searchForcedBlock.pv[0].col },
      { row: 5, col: 8 },
      "search(forced-block) should start PV with the forced block.",
    );

    const poisonBoard = createEmptyBoard();
    for (const col of [0, 2, 4]) {
      poisonBoard[5][col] = "B";
    }
    const poisonState = {
      board: poisonBoard,
      turn: "B",
      result: null,
      last: null,
      times: { B: null, W: null },
    };
    const searchAvoidPoison = await authenticatedClient.searchMove({
      state: poisonState,
      config: DEFAULT_CONFIG,
      timeBudgetMs: 180,
      maxDepth: 1,
    });
    validateAnalysisPayload(searchAvoidPoison, "search(avoid-poison)");
    assert.ok(searchAvoidPoison.bestMove, "search(avoid-poison) should return a bestMove.");
    assert.notDeepEqual(
      { row: searchAvoidPoison.bestMove.row, col: searchAvoidPoison.bestMove.col },
      { row: 5, col: 6 },
      "search(avoid-poison) should not choose the obvious poison move.",
    );

    const doubleThreatBoard = createEmptyBoard();
    doubleThreatBoard[1][5] = "B";
    doubleThreatBoard[3][5] = "B";
    doubleThreatBoard[5][1] = "B";
    doubleThreatBoard[5][3] = "B";
    doubleThreatBoard[5][9] = "B";
    doubleThreatBoard[9][5] = "B";
    const doubleThreatState = {
      board: doubleThreatBoard,
      turn: "B",
      result: null,
      last: null,
      times: { B: null, W: null },
    };
    const searchDoubleThreat = await authenticatedClient.searchMove({
      state: doubleThreatState,
      config: DEFAULT_CONFIG,
      timeBudgetMs: 220,
      maxDepth: 1,
    });
    validateAnalysisPayload(searchDoubleThreat, "search(double-threat)");
    assert.ok(searchDoubleThreat.bestMove, "search(double-threat) should return a bestMove.");
    assert.deepEqual(
      { row: searchDoubleThreat.bestMove.row, col: searchDoubleThreat.bestMove.col },
      { row: 5, col: 5 },
      "search(double-threat) should convert the fork into the root choice.",
    );

    await assert.rejects(
      anonymousClient.analyzePosition({
        state: emptyState,
        config: DEFAULT_CONFIG,
        timeBudgetMs: 120,
        maxDepth: 2,
      }),
      (error) => error?.code === "auth_required",
      "Anonymous engine access should be rejected with auth_required.",
    );

    await assert.rejects(
      authenticatedClient.analyzePosition({
        state: {
          board: createEmptyBoard(10),
          turn: "B",
          result: null,
          last: null,
          times: { B: null, W: null },
        },
        config: { ...DEFAULT_CONFIG, boardSize: 10 },
        timeBudgetMs: 120,
        maxDepth: 2,
      }),
      (error) => error?.code === "unsupported_board_size",
      "Unsupported board sizes should be rejected with unsupported_board_size.",
    );

    await assert.rejects(
      authenticatedClient.analyzePosition({
        state: {
          ...emptyState,
          result: { winner: "B", msg: "done", sub: "done", highlight: [] },
        },
        config: DEFAULT_CONFIG,
        timeBudgetMs: 120,
        maxDepth: 2,
      }),
      (error) => error?.code === "terminal_position",
      "Terminal positions should be rejected with terminal_position.",
    );

    console.log(JSON.stringify({
      python: pythonCandidate.command,
      pythonOrigin,
      nodeOrigin,
      checks: {
        health: "passed",
        analyzeContract: {
          bestMove: analyzeEmpty.bestMove.notation,
          score: analyzeEmpty.score,
          pvLength: analyzeEmpty.pv.length,
        },
        searchContract: {
          bestMove: searchWinning.bestMove.notation,
          pvLength: searchWinning.pv.length,
        },
        tacticalSpots: {
          forcedBlock: searchForcedBlock.bestMove.notation,
          avoidPoison: searchAvoidPoison.bestMove.notation,
          doubleThreat: searchDoubleThreat.bestMove.notation,
        },
        errors: ["auth_required", "unsupported_board_size", "terminal_position"],
      },
    }, null, 2));
    console.log("Engine contract smoke passed.");
  } catch (error) {
    console.error("Engine contract smoke failed.");
    console.error(error instanceof Error ? error.stack || error.message : error);
    console.error("Python logs:");
    console.error(pythonProcess.logs().stderr || pythonProcess.logs().stdout || "(no logs)");
    console.error("Node logs:");
    console.error(nodeProcess.logs().stderr || nodeProcess.logs().stdout || "(no logs)");
    process.exitCode = 1;
  } finally {
    await stopProcess(nodeProcess.child);
    await stopProcess(pythonProcess.child);
  }
}

await main();
