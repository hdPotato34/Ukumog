import { cp, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");
const outDir = path.join(rootDir, "site");

const html = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Anti-Gomoku Online</title>
    <style>
      html, body, #root { margin: 0; min-height: 100%; background: #0d1117; }
      body { overflow-x: hidden; overflow-y: auto; }
    </style>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="./renderer.js"></script>
  </body>
</html>
`;

await mkdir(outDir, { recursive: true });

await build({
  entryPoints: [path.join(rootDir, "renderer.jsx")],
  bundle: true,
  format: "esm",
  outfile: path.join(outDir, "renderer.js"),
  jsx: "automatic",
  target: ["chrome120"],
});

await build({
  entryPoints: [path.join(rootDir, "engine", "engine-worker.mjs")],
  bundle: true,
  format: "esm",
  outfile: path.join(outDir, "engine-worker.js"),
  target: ["chrome120"],
});

await build({
  entryPoints: [path.join(rootDir, "server.mjs")],
  bundle: true,
  platform: "node",
  format: "cjs",
  outfile: path.join(outDir, "server.cjs"),
  target: ["node20"],
});

await mkdir(path.join(outDir, "engine"), { recursive: true });
await cp(
  path.join(rootDir, "engine", "engine-pack.default.json"),
  path.join(outDir, "engine", "engine-pack.default.json"),
  { force: true },
);

await writeFile(path.join(outDir, "index.html"), html, "utf8");
console.log("Web assets built into ./site");
