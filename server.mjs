import { WebSocketServer } from "ws";
import { applyMove, createMatchState, sanitizeConfig, tickClock } from "./game-core.mjs";

const PORT = Number(process.env.PORT || 8787);
const OPEN = 1;
const room = {
  host: null,
  guest: null,
  config: null,
  gameState: null,
  phase: "idle",
  rematch: { host: false, guest: false },
  timerId: null,
};

function send(socket, payload) {
  if (socket && socket.readyState === OPEN) socket.send(JSON.stringify(payload));
}

function stopTimer() {
  if (room.timerId) {
    clearInterval(room.timerId);
    room.timerId = null;
  }
}

function clearRoom() {
  stopTimer();
  room.host = null;
  room.guest = null;
  room.config = null;
  room.gameState = null;
  room.phase = "idle";
  room.rematch = { host: false, guest: false };
}

function notice(role) {
  if (room.phase === "waiting") return role === "host" ? "Waiting for opponent to join this server." : "Waiting for host.";
  if (room.phase === "active") return role === "host" ? "You are Black." : "You are White.";
  if (room.phase === "finished") return room.rematch[role] ? "Rematch requested. Waiting for the other player." : "Game finished. Rematch keeps the same settings.";
  return "";
}

function snapshot(role) {
  send(role === "host" ? room.host : room.guest, {
    type: "snapshot",
    role,
    phase: room.phase,
    config: room.config,
    gameState: room.gameState,
    rematch: room.rematch,
    notice: notice(role),
  });
}

function broadcast() {
  snapshot("host");
  snapshot("guest");
}

function restartTimer() {
  stopTimer();
  if (!room.config || room.config.timerVal === null || room.phase !== "active") return;
  room.timerId = setInterval(() => {
    const next = tickClock(room.gameState, room.config);
    if (next === room.gameState) return;
    room.gameState = next;
    if (room.gameState.result) {
      room.phase = "finished";
      stopTimer();
    }
    broadcast();
  }, 1000);
}

function closeRoom(hostMsg, guestMsg) {
  const host = room.host;
  const guest = room.guest;
  clearRoom();
  if (host && host.readyState === OPEN) {
    send(host, { type: "room_closed", message: hostMsg });
    host.close();
  }
  if (guest && guest.readyState === OPEN) {
    send(guest, { type: "room_closed", message: guestMsg });
    guest.close();
  }
}

function handleDisconnect(socket) {
  if (socket.role === "host" && room.host === socket) return closeRoom("Host left the room. Host again to create a new match.", "Host left the room. Rejoin after a new host opens the room.");
  if (socket.role === "guest" && room.guest === socket) return closeRoom("Opponent left the room. Host again to create a new match.", "You left the room.");
}

function hostGame(socket, config) {
  if (room.host) {
    send(socket, { type: "error", message: "This server already has an active host." });
    return socket.close();
  }
  room.host = socket;
  room.config = sanitizeConfig(config);
  room.gameState = createMatchState(room.config);
  room.phase = "waiting";
  room.rematch = { host: false, guest: false };
  socket.role = "host";
  snapshot("host");
}

function joinGame(socket) {
  if (!room.host || !room.config) {
    send(socket, { type: "error", message: "No open host room exists on this server yet." });
    return socket.close();
  }
  if (room.guest) {
    send(socket, { type: "error", message: "This room already has two players." });
    return socket.close();
  }
  room.guest = socket;
  socket.role = "guest";
  room.phase = "active";
  room.gameState = createMatchState(room.config);
  room.rematch = { host: false, guest: false };
  broadcast();
  restartTimer();
}

function move(socket, row, col) {
  if (room.phase !== "active" || !room.gameState) return;
  const turnRole = room.gameState.turn === "B" ? "host" : "guest";
  if (socket.role !== turnRole) return send(socket, { type: "error", message: "It is not your turn." });
  if (!Number.isInteger(row) || !Number.isInteger(col)) return send(socket, { type: "error", message: "Move coordinates are invalid." });
  const next = applyMove(room.gameState, room.config, row, col);
  if (!next) return send(socket, { type: "error", message: "That move is not legal." });
  room.gameState = next;
  if (room.gameState.result) {
    room.phase = "finished";
    stopTimer();
  } else {
    restartTimer();
  }
  broadcast();
}

function rematch(socket) {
  if (room.phase !== "finished" || !socket.role) return;
  room.rematch[socket.role] = true;
  if (room.rematch.host && room.rematch.guest) {
    room.gameState = createMatchState(room.config);
    room.phase = "active";
    room.rematch = { host: false, guest: false };
    broadcast();
    return restartTimer();
  }
  broadcast();
}

const wss = new WebSocketServer({ port: PORT });
wss.on("connection", (socket) => {
  socket.role = null;
  socket.on("message", (raw) => {
    let payload = null;
    try { payload = JSON.parse(raw.toString()); } catch { return send(socket, { type: "error", message: "Could not parse the client message." }); }
    if (payload.type === "host_game") return hostGame(socket, payload.config);
    if (payload.type === "join_game") return joinGame(socket);
    if (payload.type === "move") return move(socket, payload.row, payload.col);
    if (payload.type === "rematch_request") return rematch(socket);
    if (payload.type === "leave") return handleDisconnect(socket);
    send(socket, { type: "error", message: "Unsupported message type." });
  });
  socket.on("close", () => handleDisconnect(socket));
});

console.log(`Anti-Gomoku server listening on ws://0.0.0.0:${PORT}`);
