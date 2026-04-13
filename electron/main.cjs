const { app, BrowserWindow } = require("electron");
const path = require("node:path");
const { spawn } = require("node:child_process");

let mainWindow = null;
let serverProcess = null;
let isQuitting = false;

function resolveRendererFile() {
  return path.join(__dirname, "..", "site", "index.html");
}

function resolveServerScript() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "server", "server.cjs");
  }
  return path.join(__dirname, "..", "site", "server.cjs");
}

function stopLocalServer() {
  if (!serverProcess) {
    return;
  }

  const proc = serverProcess;
  serverProcess = null;

  try {
    proc.kill();
  } catch {
    // Ignore shutdown errors.
  }
}

function startLocalServer() {
  stopLocalServer();

  const serverScript = resolveServerScript();
  serverProcess = spawn(process.execPath, [serverScript], {
    cwd: path.dirname(serverScript),
    env: {
      ...process.env,
      ELECTRON_RUN_AS_NODE: "1",
      PORT: process.env.PORT || "8787",
    },
    stdio: "ignore",
    windowsHide: true,
  });

  serverProcess.on("exit", () => {
    if (!isQuitting) {
      serverProcess = null;
    }
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 900,
    minWidth: 960,
    minHeight: 720,
    backgroundColor: "#0d1117",
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      sandbox: true,
    },
  });

  mainWindow.loadFile(resolveRendererFile());
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

app.whenReady().then(() => {
  startLocalServer();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("before-quit", () => {
  isQuitting = true;
  stopLocalServer();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
