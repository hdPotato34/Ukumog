import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import net from "node:net";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";

import {
  addVariation,
  buildRecordFromMoves,
  exportRecordText,
  findDeepestMainlineNode,
  importRecordText,
  moveToNotation,
  replayRecord,
} from "../game-record.mjs";
import { RemoteEngineClient } from "../engine/engine-client.mjs";
import { nextMainlineNodeToAnalyze, analysisBarPercent, formatAnalysisScore } from "../review-analysis.mjs";

const ROOT_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SERVING_DIR = path.join(ROOT_DIR, "model-server", "src", "serving");
const UKUMOG_DIR = path.join(ROOT_DIR, "ukumog-engine");
const REVIEW_CONFIG = {
  boardSize: 9,
  baseSeconds: null,
  incrementSeconds: 0,
  colorMode: "black",
};
const REVIEW_MOVES = [
  { row: 4, col: 4 },
  { row: 0, col: 0 },
  { row: 2, col: 2 },
  { row: 0, col: 8 },
  { row: 6, col: 6 },
  { row: 8, col: 0 },
];
const REVIEW_SETTINGS = {
  focus: {
    timeBudgetMs: 220,
    maxDepth: 4,
  },
  background: {
    timeBudgetMs: 140,
    maxDepth: 3,
  },
};

function windowsPath(input) {
  return process.platform === "win32" && input.startsWith("/") ? input.slice(1) : input;
}

const servingDir = windowsPath(SERVING_DIR);
const ukumogDir = windowsPath(UKUMOG_DIR);

function isInteger(value) {
  return Number.isInteger(value);
}

function validateMovePayload(move, label, boardSize = REVIEW_CONFIG.boardSize) {
  assert.ok(move && typeof move === "object", `${label} should be an object.`);
  assert.ok(isInteger(move.row) && move.row >= 0 && move.row < boardSize, `${label}.row should stay inside the board.`);
  assert.ok(isInteger(move.col) && move.col >= 0 && move.col < boardSize, `${label}.col should stay inside the board.`);
  assert.equal(move.notation, moveToNotation(move.row, move.col), `${label}.notation should match row/col.`);
}

function validateAnalysisPayload(analysis, label, boardSize = REVIEW_CONFIG.boardSize) {
  assert.ok(analysis && typeof analysis === "object", `${label} should be an object.`);
  assert.equal(analysis.backend, "ukumog", `${label}.backend should identify ukumog.`);
  assert.equal(typeof analysis.engineVersion, "string", `${label}.engineVersion should be a string.`);
  assert.ok(analysis.engineVersion.length > 0, `${label}.engineVersion should not be empty.`);
  assert.ok(isInteger(analysis.score), `${label}.score should be an integer.`);
  assert.ok(analysis.mate === null || isInteger(analysis.mate), `${label}.mate should be null or an integer.`);
  assert.ok(isInteger(analysis.depth) && analysis.depth > 0, `${label}.depth should be a positive integer.`);
  assert.ok(isInteger(analysis.nodes) && analysis.nodes >= 0, `${label}.nodes should be non-negative.`);
  assert.ok(isInteger(analysis.timeMs) && analysis.timeMs >= 0, `${label}.timeMs should be non-negative.`);
  assert.ok(Array.isArray(analysis.pv), `${label}.pv should be an array.`);
  assert.ok(analysis.pv.length > 0, `${label}.pv should not be empty.`);
  analysis.pv.forEach((move, index) => validateMovePayload(move, `${label}.pv[${index}]`, boardSize));
  if (analysis.bestMove) {
    validateMovePayload(analysis.bestMove, `${label}.bestMove`, boardSize);
  }

  const scoreText = formatAnalysisScore(analysis);
  const barPercent = analysisBarPercent(analysis);
  assert.equal(typeof scoreText, "string", `${label} should be consumable by formatAnalysisScore().`);
  assert.ok(Number.isFinite(barPercent) && barPercent >= 0 && barPercent <= 100, `${label} should be consumable by analysisBarPercent().`);
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

async function createGuestToken(nodeOrigin) {
  const response = await fetch(`${nodeOrigin}/api/auth/guest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ displayName: "Review Smoke" }),
  });
  assert.equal(response.status, 201, "Guest session creation should succeed.");
  const payload = await response.json();
  assert.equal(typeof payload.sessionToken, "string", "Guest session should return a session token.");
  assert.ok(payload.sessionToken.length > 0, "Guest session token should not be empty.");
  return payload.sessionToken;
}

function buildReviewRecord() {
  return buildRecordFromMoves(REVIEW_CONFIG, REVIEW_MOVES, {
    title: "Review Smoke 9x9",
    sourceKind: "local",
    sourceLabel: "Review Smoke",
  });
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
    const nodeHealth = await waitForJson(`${nodeOrigin}/api/engine/health`, 15000, "Node engine health proxy");
    assert.equal(nodeHealth.ok, true, "Node proxy health should report ok.");
    assert.deepEqual(nodeHealth.capabilities?.supportedBoardSizes, [9, 11, 13, 15], "Node proxy health should surface supported board sizes.");

    const token = await createGuestToken(nodeOrigin);
    const client = new RemoteEngineClient({
      serverUrl: nodeOrigin,
      getSessionToken: () => token,
    });
    await client.init();

    const baseRecord = buildReviewRecord();
    const deepestNodeId = findDeepestMainlineNode(baseRecord);
    const deepestReplay = replayRecord(baseRecord, deepestNodeId);
    assert.equal(deepestReplay.state.board.length, 9, "Review replay should preserve 9x9 board size.");
    assert.equal(deepestReplay.moves.length, REVIEW_MOVES.length, "Review replay should preserve the full move list.");

    const exported = exportRecordText(baseRecord);
    const imported = importRecordText(exported);
    const importedDeepestNodeId = findDeepestMainlineNode(imported);
    const importedReplay = replayRecord(imported, importedDeepestNodeId);
    assert.equal(imported.config.boardSize, 9, "Imported review record should preserve 9x9 board size.");
    assert.deepEqual(importedReplay.moves, deepestReplay.moves, "Record export/import should preserve the main line.");

    const focusAnalysis = await client.analyzePosition({
      state: deepestReplay.state,
      config: imported.config,
      timeBudgetMs: REVIEW_SETTINGS.focus.timeBudgetMs,
      maxDepth: REVIEW_SETTINGS.focus.maxDepth,
    });
    validateAnalysisPayload(focusAnalysis, "review(focus-9x9)", 9);

    const analyzedByNodeId = { [importedDeepestNodeId]: focusAnalysis };
    const analyzedStatusByNodeId = { [importedDeepestNodeId]: "ready" };
    const backgroundNodeId = nextMainlineNodeToAnalyze(imported, analyzedByNodeId, analyzedStatusByNodeId, importedDeepestNodeId);
    assert.ok(backgroundNodeId, "Review background analysis should find another mainline node on 9x9.");
    const backgroundReplay = replayRecord(imported, backgroundNodeId);
    const backgroundAnalysis = await client.analyzePosition({
      state: backgroundReplay.state,
      config: imported.config,
      timeBudgetMs: REVIEW_SETTINGS.background.timeBudgetMs,
      maxDepth: REVIEW_SETTINGS.background.maxDepth,
    });
    validateAnalysisPayload(backgroundAnalysis, "review(background-9x9)", 9);

    const branchPointId = replayRecord(imported, importedDeepestNodeId).path[2];
    const branched = addVariation(imported, branchPointId, 4, 6);
    const branchedReplay = replayRecord(branched.record, branched.nodeId);
    assert.equal(branchedReplay.state.board.length, 9, "Review branch replay should stay on 9x9.");
    assert.equal(branchedReplay.moves.at(-1)?.notation, "G5", "Review branch should append the expected variation move.");

    const branchAnalysis = await client.analyzePosition({
      state: branchedReplay.state,
      config: branched.record.config,
      timeBudgetMs: REVIEW_SETTINGS.focus.timeBudgetMs,
      maxDepth: REVIEW_SETTINGS.focus.maxDepth,
    });
    validateAnalysisPayload(branchAnalysis, "review(branch-9x9)", 9);

    client.dispose();

    console.log(JSON.stringify({
      reviewRecord: {
        boardSize: imported.config.boardSize,
        moveCount: importedReplay.moves.length,
        deepestNodeId: importedDeepestNodeId,
      },
      focusAnalysis: {
        bestMove: focusAnalysis.bestMove?.notation || "",
        pvLength: focusAnalysis.pv.length,
      },
      backgroundAnalysis: {
        nodeId: backgroundNodeId,
        bestMove: backgroundAnalysis.bestMove?.notation || "",
      },
      branchAnalysis: {
        nodeId: branched.nodeId,
        bestMove: branchAnalysis.bestMove?.notation || "",
      },
    }, null, 2));
    console.log("Review smoke passed.");
  } catch (error) {
    console.error("Review smoke failed.");
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
