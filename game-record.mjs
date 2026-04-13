import { applyMove, createMatchState, sanitizeConfig } from "./game-core.mjs";

const RECORD_FORMAT = "AntiGomokuPGN/1";
const ARCHIVE_STORAGE_KEY = "anti_gomoku_record_archive_v1";

function generateId(prefix = "rec") {
  if (globalThis.crypto?.randomUUID) {
    return `${prefix}-${globalThis.crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function cloneNode(node) {
  return {
    ...node,
    move: node.move ? { ...node.move } : null,
    childrenIds: [...node.childrenIds],
  };
}

function cloneRecord(record) {
  return {
    ...record,
    config: sanitizeConfig(record.config),
    meta: { ...(record.meta || {}) },
    nodes: Object.fromEntries(Object.entries(record.nodes || {}).map(([id, node]) => [id, cloneNode(node)])),
  };
}

function ensureRecordShape(record) {
  if (!record?.nodes?.root) {
    throw new Error("Record is missing a root node.");
  }
  return record;
}

function toColumnLabel(col) {
  let index = Number(col);
  let label = "";
  while (index >= 0) {
    label = String.fromCharCode(65 + (index % 26)) + label;
    index = Math.floor(index / 26) - 1;
  }
  return label;
}

function fromColumnLabel(label) {
  let value = 0;
  for (const char of label) {
    value = value * 26 + (char.charCodeAt(0) - 64);
  }
  return value - 1;
}

export function moveToNotation(row, col) {
  return `${toColumnLabel(col)}${row + 1}`;
}

export function notationToMove(notation) {
  const match = String(notation || "").trim().toUpperCase().match(/^([A-Z]+)(\d+)$/);
  if (!match) {
    return null;
  }
  return {
    row: Number(match[2]) - 1,
    col: fromColumnLabel(match[1]),
  };
}

function defaultTitle(meta, config) {
  if (meta?.title) return meta.title;
  if (meta?.sourceKind === "online" && meta?.roomId) {
    return `Room ${meta.roomId}${meta.gameIndex ? ` - Game ${meta.gameIndex}` : ""}`;
  }
  return `Record ${config.boardSize}x${config.boardSize}`;
}

export function createEmptyRecord(config, meta = {}) {
  const cleanConfig = sanitizeConfig(config);
  const timestamp = new Date().toISOString();
  return {
    format: RECORD_FORMAT,
    id: meta.id || generateId("record"),
    config: cleanConfig,
    meta: {
      title: defaultTitle(meta, cleanConfig),
      sourceKind: meta.sourceKind || "local",
      sourceLabel: meta.sourceLabel || "",
      roomId: meta.roomId || "",
      gameId: meta.gameId || "",
      gameIndex: Number(meta.gameIndex || 0),
      createdAt: meta.createdAt || timestamp,
      updatedAt: meta.updatedAt || timestamp,
      players: meta.players || null,
      result: meta.result || null,
      tags: Array.isArray(meta.tags) ? [...meta.tags] : [],
    },
    rootId: "root",
    nodes: {
      root: {
        id: "root",
        parentId: null,
        move: null,
        childrenIds: [],
      },
    },
  };
}

export function getNodePath(record, nodeId) {
  ensureRecordShape(record);
  const path = [];
  let cursor = nodeId && record.nodes[nodeId] ? record.nodes[nodeId] : record.nodes.root;
  while (cursor) {
    path.push(cursor.id);
    cursor = cursor.parentId ? record.nodes[cursor.parentId] : null;
  }
  return path.reverse();
}

export function replayRecord(record, nodeId = null) {
  ensureRecordShape(record);
  const targetId = nodeId && record.nodes[nodeId] ? nodeId : record.rootId;
  const path = getNodePath(record, targetId);
  let state = createMatchState(record.config);
  const moves = [];

  for (const id of path.slice(1)) {
    const node = record.nodes[id];
    const next = applyMove(state, record.config, node.move.row, node.move.col);
    if (!next) {
      throw new Error(`Record contains an illegal move at ${node.move.notation || moveToNotation(node.move.row, node.move.col)}.`);
    }
    state = next;
    moves.push({ ...node.move });
  }

  return {
    state,
    path,
    nodeId: targetId,
    moves,
  };
}

export function addVariation(record, parentId, row, col, extras = {}) {
  const baseRecord = cloneRecord(ensureRecordShape(record));
  const safeParentId = baseRecord.nodes[parentId] ? parentId : baseRecord.rootId;
  const { state, path } = replayRecord(baseRecord, safeParentId);
  const nextState = applyMove(state, baseRecord.config, row, col);
  if (!nextState) {
    throw new Error("That move is not legal from the current review position.");
  }

  const existingChild = baseRecord.nodes[safeParentId].childrenIds
    .map((id) => baseRecord.nodes[id])
    .find((node) => node.move?.row === row && node.move?.col === col);
  if (existingChild) {
    return { record: baseRecord, nodeId: existingChild.id };
  }

  const nodeId = extras.id || generateId("node");
  const move = {
    row,
    col,
    player: state.turn,
    ply: path.length,
    notation: moveToNotation(row, col),
  };

  baseRecord.nodes[nodeId] = {
    id: nodeId,
    parentId: safeParentId,
    move,
    childrenIds: [],
  };
  baseRecord.nodes[safeParentId].childrenIds.push(nodeId);
  baseRecord.meta.updatedAt = new Date().toISOString();
  if (extras.result) {
    baseRecord.meta.result = extras.result;
  }
  return { record: baseRecord, nodeId };
}

export function buildRecordFromMoves(config, moves, meta = {}) {
  let record = createEmptyRecord(config, meta);
  let cursor = record.rootId;
  for (const move of moves || []) {
    const next = addVariation(record, cursor, move.row, move.col);
    record = next.record;
    cursor = next.nodeId;
  }
  if (meta.result) {
    record.meta.result = meta.result;
  }
  if (meta.players) {
    record.meta.players = meta.players;
  }
  return record;
}

export function getChildNodes(record, parentId) {
  ensureRecordShape(record);
  const parent = record.nodes[parentId] || record.nodes[record.rootId];
  return parent.childrenIds.map((id) => record.nodes[id]);
}

export function getTimeline(record, currentNodeId) {
  const path = getNodePath(record, currentNodeId && record.nodes[currentNodeId] ? currentNodeId : record.rootId);
  return path.map((id, index) => {
    const node = record.nodes[id];
    return {
      id,
      isRoot: id === record.rootId,
      label: id === record.rootId ? "Start" : `${index}. ${node.move.player}@${node.move.notation}`,
      move: node.move,
      children: node.childrenIds.map((childId) => record.nodes[childId]),
    };
  });
}

function headerLine(key, value) {
  const escaped = String(value ?? "").replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  return `[${key} "${escaped}"]`;
}

function readHeaders(text) {
  const headers = {};
  const lines = String(text || "").replace(/\r/g, "").split("\n");
  let index = 0;
  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) {
      index += 1;
      break;
    }
    const match = line.match(/^\[([A-Za-z0-9_]+)\s+"((?:[^"\\]|\\.)*)"\]$/);
    if (!match) {
      break;
    }
    headers[match[1]] = match[2].replace(/\\"/g, '"').replace(/\\\\/g, "\\");
    index += 1;
  }
  return {
    headers,
    body: lines.slice(index).join("\n").trim(),
  };
}

function tokenizeBody(body) {
  return String(body || "")
    .replace(/\r/g, " ")
    .match(/\(|\)|\d+\.(?:\.\.)?|[BW]@[A-Z]+\d+/g) || [];
}

function serializeBranch(record, parentId) {
  const children = getChildNodes(record, parentId);
  if (!children.length) {
    return [];
  }

  const [main, ...variations] = children;
  const tokens = [`${main.move.player}@${main.move.notation}`];
  tokens.push(...serializeBranch(record, main.id));

  for (const variation of variations) {
    tokens.push("(");
    tokens.push(`${variation.move.player}@${variation.move.notation}`);
    tokens.push(...serializeBranch(record, variation.id));
    tokens.push(")");
  }

  return tokens;
}

export function exportRecordText(record) {
  const safeRecord = ensureRecordShape(record);
  const headers = [
    headerLine("Format", safeRecord.format || RECORD_FORMAT),
    headerLine("RecordId", safeRecord.id),
    headerLine("Title", safeRecord.meta?.title || ""),
    headerLine("BoardSize", safeRecord.config.boardSize),
    headerLine("Timer", safeRecord.config.timerVal === null ? "null" : safeRecord.config.timerVal),
    headerLine("SourceKind", safeRecord.meta?.sourceKind || ""),
    headerLine("RoomId", safeRecord.meta?.roomId || ""),
    headerLine("GameId", safeRecord.meta?.gameId || ""),
    headerLine("GameIndex", safeRecord.meta?.gameIndex || 0),
    headerLine("CreatedAt", safeRecord.meta?.createdAt || ""),
    headerLine("UpdatedAt", safeRecord.meta?.updatedAt || ""),
  ];

  const body = serializeBranch(safeRecord, safeRecord.rootId).join(" ");
  return `${headers.join("\n")}\n\n${body}\n`;
}

function parseBranchIntoRecord(record, tokens, parentId, stopAtParen = false) {
  let currentParentId = parentId;

  while (tokens.length) {
    const token = tokens[0];
    if (token === ")" && stopAtParen) {
      tokens.shift();
      return record;
    }
    if (token === "(") {
      tokens.shift();
      record = parseBranchIntoRecord(record, tokens, parentId, true);
      continue;
    }
    if (/^\d+\.(?:\.\.)?$/.test(token)) {
      tokens.shift();
      continue;
    }

    tokens.shift();
    const moveMatch = token.match(/^([BW])@([A-Z]+\d+)$/);
    if (!moveMatch) {
      throw new Error(`Unsupported record token: ${token}`);
    }
    const move = notationToMove(moveMatch[2]);
    if (!move) {
      throw new Error(`Could not parse move notation ${moveMatch[2]}.`);
    }
    const replay = replayRecord(record, currentParentId);
    if (replay.state.turn !== moveMatch[1]) {
      throw new Error(`Move token ${token} does not match the expected side to move.`);
    }
    const next = addVariation(record, currentParentId, move.row, move.col);
    record = next.record;
    currentParentId = next.nodeId;
  }

  if (stopAtParen) {
    throw new Error("Record text ended before a variation was closed.");
  }

  return record;
}

export function importRecordText(text) {
  const { headers, body } = readHeaders(text);
  const record = createEmptyRecord(
    {
      boardSize: Number(headers.BoardSize || 11),
      timerVal: headers.Timer === "null" ? null : Number(headers.Timer || null),
    },
    {
      id: headers.RecordId || generateId("record"),
      title: headers.Title || "",
      sourceKind: headers.SourceKind || "imported",
      roomId: headers.RoomId || "",
      gameId: headers.GameId || "",
      gameIndex: Number(headers.GameIndex || 0),
      createdAt: headers.CreatedAt || new Date().toISOString(),
      updatedAt: headers.UpdatedAt || new Date().toISOString(),
    },
  );

  const tokens = tokenizeBody(body);
  const next = parseBranchIntoRecord(record, tokens, record.rootId, false);
  if (tokens.length) {
    throw new Error("Record text contains trailing tokens that could not be parsed.");
  }
  return next;
}

function canUseStorage() {
  return typeof window !== "undefined" && !!window.localStorage;
}

function sortRecords(records) {
  return [...records].sort((left, right) => String(right.meta?.updatedAt || "").localeCompare(String(left.meta?.updatedAt || "")));
}

export function loadArchivedRecords() {
  if (!canUseStorage()) return [];
  try {
    const raw = window.localStorage.getItem(ARCHIVE_STORAGE_KEY);
    const parsed = JSON.parse(raw || "[]");
    if (!Array.isArray(parsed)) return [];
    return sortRecords(parsed.map((record) => ensureRecordShape(record)));
  } catch {
    return [];
  }
}

function saveArchivedRecords(records) {
  if (!canUseStorage()) return;
  window.localStorage.setItem(ARCHIVE_STORAGE_KEY, JSON.stringify(sortRecords(records)));
}

export function upsertArchivedRecord(record) {
  const safeRecord = cloneRecord(ensureRecordShape(record));
  const existing = loadArchivedRecords().filter((entry) => entry.id !== safeRecord.id);
  safeRecord.meta.updatedAt = new Date().toISOString();
  saveArchivedRecords([safeRecord, ...existing]);
  return safeRecord;
}

export function deleteArchivedRecord(recordId) {
  saveArchivedRecords(loadArchivedRecords().filter((record) => record.id !== recordId));
}

export function findArchivedRecordByGameId(gameId) {
  return loadArchivedRecords().find((record) => record.meta?.gameId === gameId) || null;
}

export function summarizeArchivedRecord(record) {
  const replay = replayRecord(record, findDeepestMainlineNode(record));
  return {
    id: record.id,
    title: record.meta?.title || "Untitled Record",
    updatedAt: record.meta?.updatedAt || "",
    sourceKind: record.meta?.sourceKind || "local",
    roomId: record.meta?.roomId || "",
    gameId: record.meta?.gameId || "",
    gameIndex: record.meta?.gameIndex || 0,
    moveCount: replay.moves.length,
    result: record.meta?.result || replay.state.result || null,
    players: record.meta?.players || null,
    config: record.config,
  };
}

export function findDeepestMainlineNode(record) {
  let cursor = record.rootId;
  while (record.nodes[cursor]?.childrenIds?.length) {
    cursor = record.nodes[cursor].childrenIds[0];
  }
  return cursor;
}

export function promoteNodePathToMain(record, nodeId) {
  const safeRecord = cloneRecord(ensureRecordShape(record));
  const path = getNodePath(safeRecord, nodeId && safeRecord.nodes[nodeId] ? nodeId : safeRecord.rootId);
  for (let index = 1; index < path.length; index += 1) {
    const childId = path[index];
    const parentId = path[index - 1];
    const parent = safeRecord.nodes[parentId];
    if (!parent) continue;
    parent.childrenIds = [
      childId,
      ...parent.childrenIds.filter((id) => id !== childId),
    ];
  }
  safeRecord.meta.updatedAt = new Date().toISOString();
  return safeRecord;
}
