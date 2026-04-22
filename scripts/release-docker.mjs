import { createHash } from "node:crypto";
import { createReadStream, existsSync } from "node:fs";
import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";

const ROOT_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const RELEASE_VERSION = "2026-04-21-r3";
const IMAGE_NAME = "anti-gomoku-room-server";
const IMAGE_TAG = `${IMAGE_NAME}:${RELEASE_VERSION}`;
const PLATFORM = "linux/amd64";
const ARCHIVE_BASENAME = `${IMAGE_NAME}_${RELEASE_VERSION}_linux-x86_64`;
const RELEASE_DIR = path.join(ROOT_DIR, "release", "docker");
const ARCHIVE_PATH = path.join(RELEASE_DIR, `${ARCHIVE_BASENAME}.tar`);
const CHECKSUM_PATH = path.join(RELEASE_DIR, `${ARCHIVE_BASENAME}.sha256`);
const MANIFEST_PATH = path.join(RELEASE_DIR, `${ARCHIVE_BASENAME}.manifest.json`);
const RUNBOOK_SOURCE = path.join(ROOT_DIR, "docs", "DOCKER_RELEASE_RUNBOOK_LINUX_X86_64.md");
const RUNBOOK_COPY_PATH = path.join(RELEASE_DIR, `${ARCHIVE_BASENAME}.runbook.md`);
const CHECKLIST_SOURCE = path.join(ROOT_DIR, "docs", "DOCKER_SERVER_UPLOAD_CHECKLIST_LINUX_X86_64.md");
const CHECKLIST_COPY_PATH = path.join(RELEASE_DIR, `${ARCHIVE_BASENAME}.checklist.md`);
const SMOKE_CONTAINER_NAME = `${IMAGE_NAME}-release-smoke`;
const PRECHECK_COMMANDS = [
  "npm run test:engine-preflight",
  "python -m unittest discover -s model-server/tests -p \"test_*.py\"",
];
const KNOWN_LIMITATIONS = [
  "Server restarts do not recover live rooms or unfinished games.",
  "Online play still uses HTTP + polling instead of WebSocket.",
  "This release only targets Linux x86_64 Docker deployment.",
  "Electron release delivery remains out of scope for this package.",
  "ML-specific 11x11 coupling is not generalized; multi-board runtime currently relies on search-first paths.",
];

function runCommand(command, args, { stdio = "inherit", cwd = ROOT_DIR, env = process.env, shell = false } = {}) {
  const result = spawnSync(command, args, {
    cwd,
    env,
    shell,
    stdio,
    encoding: stdio === "pipe" ? "utf8" : undefined,
    windowsHide: true,
  });

  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(`Command failed (${command} ${args.join(" ")}).`);
  }
  return result;
}

function gitOutput(args) {
  return runCommand("git", args, { stdio: "pipe" }).stdout.trim();
}

function resolvePythonCommand() {
  const candidates = process.env.PYTHON
    ? [{ command: process.env.PYTHON, args: [] }]
    : process.platform === "win32"
      ? [
        { command: "python", args: [] },
        { command: "py", args: ["-3.11"] },
        { command: "py", args: ["-3"] },
      ]
      : [
        { command: "python3", args: [] },
        { command: "python", args: [] },
      ];

  for (const candidate of candidates) {
    const result = spawnSync(candidate.command, [...candidate.args, "--version"], {
      cwd: ROOT_DIR,
      stdio: "ignore",
      windowsHide: true,
    });
    if (result.error?.code === "ENOENT") {
      continue;
    }
    if (!result.error && result.status === 0) {
      return candidate;
    }
  }

  throw new Error("Could not find a Python interpreter for release verification.");
}

async function ensureReleaseDir() {
  await mkdir(RELEASE_DIR, { recursive: true });
}

async function hashFile(filePath) {
  return new Promise((resolve, reject) => {
    const hash = createHash("sha256");
    const stream = createReadStream(filePath);
    stream.on("error", reject);
    stream.on("data", (chunk) => hash.update(chunk));
    stream.on("end", () => resolve(hash.digest("hex")));
  });
}

async function readExistingManifest() {
  if (!existsSync(MANIFEST_PATH)) {
    return null;
  }

  try {
    const content = await readFile(MANIFEST_PATH, "utf8");
    return JSON.parse(content);
  } catch {
    return null;
  }
}

async function writeManifest({ verifiedAt = "", builtAt = "", checksum = "", smokePort = null } = {}) {
  await ensureReleaseDir();
  const gitCommit = gitOutput(["rev-parse", "HEAD"]);
  const gitStatus = gitOutput(["status", "--short"]);
  const previousManifest = await readExistingManifest();
  const manifest = {
    releaseVersion: RELEASE_VERSION,
    imageName: IMAGE_NAME,
    imageTag: IMAGE_TAG,
    platform: PLATFORM,
    archiveFile: path.basename(ARCHIVE_PATH),
    checksumFile: path.basename(CHECKSUM_PATH),
    runbookFile: path.basename(RUNBOOK_COPY_PATH),
    checklistFile: path.basename(CHECKLIST_COPY_PATH),
    gitCommit,
    dirtyWorktree: gitStatus.length > 0,
    gitStatus: gitStatus ? gitStatus.split(/\r?\n/) : [],
    builtAt: builtAt || previousManifest?.builtAt || "",
    verifiedAt: verifiedAt || previousManifest?.verifiedAt || "",
    smokePort: smokePort ?? previousManifest?.smokePort ?? null,
    prechecks: PRECHECK_COMMANDS,
    knownLimitations: KNOWN_LIMITATIONS,
  };
  if (checksum || previousManifest?.archiveSha256) {
    manifest.archiveSha256 = checksum || previousManifest.archiveSha256;
  }

  await writeFile(MANIFEST_PATH, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  if (existsSync(RUNBOOK_SOURCE)) {
    await copyFile(RUNBOOK_SOURCE, RUNBOOK_COPY_PATH);
  }
  if (existsSync(CHECKLIST_SOURCE)) {
    await copyFile(CHECKLIST_SOURCE, CHECKLIST_COPY_PATH);
  }
  return manifest;
}

async function verifyRepo() {
  const python = resolvePythonCommand();
  if (process.platform === "win32") {
    runCommand(process.env.ComSpec || "cmd.exe", ["/d", "/s", "/c", "npm run test:engine-preflight"]);
  } else {
    runCommand("npm", ["run", "test:engine-preflight"]);
  }
  runCommand(python.command, [
    ...python.args,
    "-m",
    "unittest",
    "discover",
    "-s",
    "model-server/tests",
    "-p",
    "test_*.py",
  ]);
  return new Date().toISOString();
}

async function buildImage() {
  runCommand("docker", ["build", "--platform", PLATFORM, "-t", IMAGE_TAG, "."]);
  return new Date().toISOString();
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
    await delay(250);
  }

  throw new Error(`Timed out waiting for ${label}.${lastError ? ` Last error: ${lastError.message}` : ""}`);
}

async function removeContainerIfExists() {
  try {
    runCommand("docker", ["rm", "-f", SMOKE_CONTAINER_NAME], { stdio: "ignore" });
  } catch {
    // Ignore cleanup failures for nonexistent containers.
  }
}

async function smokeImage() {
  const port = await findFreePort();
  await removeContainerIfExists();
  runCommand("docker", [
    "run",
    "-d",
    "--rm",
    "--name",
    SMOKE_CONTAINER_NAME,
    "-p",
    `${port}:8787`,
    IMAGE_TAG,
  ]);

  try {
    const appHealth = await waitForJson(`http://127.0.0.1:${port}/health`, 30000, "container /health");
    const engineHealth = await waitForJson(`http://127.0.0.1:${port}/api/engine/health`, 30000, "container /api/engine/health");
    if (appHealth.ok !== true) {
      throw new Error("Container /health did not report ok=true.");
    }
    if (engineHealth.ok !== true) {
      throw new Error("Container /api/engine/health did not report ok=true.");
    }
    return { port };
  } finally {
    await removeContainerIfExists();
  }
}

async function saveArchive() {
  await ensureReleaseDir();
  runCommand("docker", ["save", "-o", ARCHIVE_PATH, IMAGE_TAG]);
  const checksum = await hashFile(ARCHIVE_PATH);
  await writeFile(CHECKSUM_PATH, `${checksum}  ${path.basename(ARCHIVE_PATH)}\n`, "utf8");
  return checksum;
}

async function main() {
  const command = process.argv[2] || "metadata";
  let verifiedAt = "";
  let builtAt = "";
  let checksum = "";
  let smokePort = null;

  if (command === "verify") {
    verifiedAt = await verifyRepo();
    await writeManifest({ verifiedAt });
    return;
  }

  if (command === "build") {
    builtAt = await buildImage();
    await writeManifest({ builtAt });
    return;
  }

  if (command === "smoke") {
    const smoke = await smokeImage();
    await writeManifest({ smokePort: smoke.port });
    return;
  }

  if (command === "save") {
    checksum = await saveArchive();
    await writeManifest({ checksum });
    return;
  }

  if (command === "package") {
    verifiedAt = await verifyRepo();
    builtAt = await buildImage();
    const smoke = await smokeImage();
    smokePort = smoke.port;
    checksum = await saveArchive();
    await writeManifest({ verifiedAt, builtAt, checksum, smokePort });
    return;
  }

  if (command === "metadata") {
    const manifest = await writeManifest();
    process.stdout.write(`${JSON.stringify(manifest, null, 2)}\n`);
    return;
  }

  throw new Error(`Unknown release-docker command: ${command}`);
}

await main();
