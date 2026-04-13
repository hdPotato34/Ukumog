import { randomBytes, randomUUID, scryptSync, timingSafeEqual } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createServer as createHttpServer } from "node:http";
import { createServer as createHttpsServer } from "node:https";
import path from "node:path";
import { applyMove, createMatchState, pName, sanitizeConfig, tickClock } from "./game-core.mjs";

const PORT = Number(process.env.PORT || 8787);
const HOST = process.env.HOST || "0.0.0.0";
const CLOSED_ROOM_TTL_MS = 60_000;
const ACTIVE_SESSION_WINDOW_MS = 90_000;
const INITIAL_RATING = 1000;
const STABLE_RATING_K = 20;
const HOT_RATING_K = 60;
const RATING_DECAY_GAMES = 8;
const SESSION_STORAGE_KEY = "x-session-token";
const ROOM_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
const GUEST_NAME_ADJECTIVES = ["Swift", "Quiet", "Amber", "Iron", "North", "Bright", "Silver", "Brisk"];
const GUEST_NAME_ANIMALS = ["Fox", "Tiger", "Wolf", "Raven", "Panda", "Lynx", "Hawk", "Otter"];
const MIME_TYPES = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".txt": "text/plain; charset=utf-8",
};

const moduleDir = process.argv[1] ? path.dirname(path.resolve(process.argv[1])) : process.cwd();
const dataRoot = path.join(process.cwd(), "data");
const dataFile = path.join(dataRoot, "app-state.json");

const rooms = new Map();
let persistentState = {
  users: [],
  sessions: [],
  matchHistory: [],
};
let persistQueue = Promise.resolve();

const staticRoot = resolveStaticRoot();

function resolveStaticRoot() {
  const candidates = [
    path.join(process.cwd(), "site"),
    path.join(moduleDir, "site"),
    moduleDir,
  ];

  return candidates.find((candidate) => {
    const indexPath = path.join(candidate, "index.html");
    const rendererPath = path.join(candidate, "renderer.js");
    return requireFile(indexPath) && requireFile(rendererPath);
  }) || path.join(process.cwd(), "site");
}

function requireFile(filePath) {
  return existsSync(filePath);
}

function normalizeRatedGames(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(0, Math.floor(parsed)) : 0;
}

function normalizeRatingValue(value, fallback = INITIAL_RATING) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.round(parsed) : fallback;
}

function ratingKForGames(ratedGames = 0) {
  const games = normalizeRatedGames(ratedGames);
  return STABLE_RATING_K + (HOT_RATING_K - STABLE_RATING_K) * Math.exp(-games / RATING_DECAY_GAMES);
}

function ratingTemperatureForGames(ratedGames = 0) {
  return Number((ratingKForGames(ratedGames) / STABLE_RATING_K).toFixed(2));
}

function normalizeUserRecord(user) {
  return {
    ...user,
    rating: normalizeRatingValue(user?.rating, INITIAL_RATING),
    ratedGames: normalizeRatedGames(user?.ratedGames),
  };
}

function decorateIdentityWithRating(identity, fallbackRating = null, fallbackGames = null) {
  if (!identity) return null;
  const rating = identity.authenticated ? normalizeRatingValue(identity.rating, fallbackRating ?? INITIAL_RATING) : null;
  const ratedGames = identity.authenticated ? normalizeRatedGames(identity.ratedGames ?? fallbackGames ?? 0) : null;
  return {
    ...identity,
    rating,
    ratedGames,
    ratingTemperature: identity.authenticated ? ratingTemperatureForGames(ratedGames) : null,
  };
}

async function loadPersistentState() {
  await mkdir(dataRoot, { recursive: true });

  if (!existsSync(dataFile)) {
    await persistState();
    return;
  }

  try {
    const raw = await readFile(dataFile, "utf8");
    const parsed = JSON.parse(raw);
    persistentState = {
      users: Array.isArray(parsed.users) ? parsed.users.map(normalizeUserRecord) : [],
      sessions: Array.isArray(parsed.sessions) ? parsed.sessions : [],
      matchHistory: Array.isArray(parsed.matchHistory) ? parsed.matchHistory : [],
    };
  } catch (error) {
    console.error("Could not read persisted app state. Starting from a clean state.");
    console.error(error);
    persistentState = { users: [], sessions: [], matchHistory: [] };
    await persistState();
  }
}

function persistState() {
  persistQueue = persistQueue.then(() => writeFile(dataFile, JSON.stringify(persistentState, null, 2), "utf8"));
  return persistQueue;
}

function normalizeRoomId(input) {
  return String(input || "").trim().toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 6);
}

function normalizeLoginId(input) {
  return String(input || "").trim().toLowerCase().replace(/[^a-z0-9_.-]/g, "").slice(0, 24);
}

function normalizeDisplayName(input, fallback = "") {
  const clean = String(input || "").trim().replace(/\s+/g, " ").slice(0, 28);
  return clean || fallback;
}

function createHttpError(statusCode, message) {
  const error = new Error(message);
  error.statusCode = statusCode;
  return error;
}

function hashPassword(password, salt = randomBytes(16).toString("hex")) {
  const hash = scryptSync(password, salt, 64).toString("hex");
  return { salt, hash };
}

function verifyPassword(password, user) {
  const candidate = scryptSync(password, user.passwordSalt, 64);
  const actual = Buffer.from(user.passwordHash, "hex");
  return candidate.length === actual.length && timingSafeEqual(candidate, actual);
}

function publicUser(user) {
  if (!user) return null;
  return decorateIdentityWithRating({
    id: user.id,
    loginId: user.loginId,
    displayName: user.displayName,
    createdAt: user.createdAt,
    authenticated: true,
    rating: user.rating,
    ratedGames: user.ratedGames,
  });
}

function createGuestName() {
  const adjective = GUEST_NAME_ADJECTIVES[Math.floor(Math.random() * GUEST_NAME_ADJECTIVES.length)];
  const animal = GUEST_NAME_ANIMALS[Math.floor(Math.random() * GUEST_NAME_ANIMALS.length)];
  const digits = randomBytes(2).toString("hex").slice(0, 4).toUpperCase();
  return `${adjective}${animal}${digits}`;
}

function generateRoomId() {
  for (let attempt = 0; attempt < 1000; attempt += 1) {
    let id = "";
    for (let index = 0; index < 6; index += 1) {
      id += ROOM_CHARS[Math.floor(Math.random() * ROOM_CHARS.length)];
    }
    if (!rooms.has(id)) {
      return id;
    }
  }
  throw new Error("Unable to allocate a room id.");
}

function stopTimer(room) {
  if (room.timerId) {
    clearInterval(room.timerId);
    room.timerId = null;
  }
}

function scheduleRoomCleanup(room) {
  if (room.cleanupId) {
    clearTimeout(room.cleanupId);
  }

  room.cleanupId = setTimeout(() => {
    if (rooms.get(room.id) === room && room.phase === "closed") {
      rooms.delete(room.id);
    }
  }, CLOSED_ROOM_TTL_MS);
}

function readTokenFromRequest(req) {
  const authHeader = req.headers.authorization || "";
  if (authHeader.startsWith("Bearer ")) {
    return authHeader.slice(7).trim();
  }
  const headerToken = req.headers[SESSION_STORAGE_KEY];
  if (typeof headerToken === "string" && headerToken.trim()) {
    return headerToken.trim();
  }
  return "";
}

function findUserById(userId) {
  return persistentState.users.find((user) => user.id === userId) || null;
}

function findUserByLoginId(loginId) {
  const cleanLoginId = normalizeLoginId(loginId);
  return persistentState.users.find((user) => user.loginId === cleanLoginId) || null;
}

function findSessionByToken(token) {
  if (!token) return null;
  return persistentState.sessions.find((session) => session.token === token) || null;
}

function touchSession(session) {
  if (!session) return;
  session.lastSeenAt = new Date().toISOString();
}

function buildViewer(session) {
  if (!session) return null;

  if (session.kind === "user") {
    const user = findUserById(session.userId);
    if (!user) return null;
    return {
      sessionToken: session.token,
      sessionKind: "user",
      authenticated: true,
      anonymous: false,
      userId: user.id,
      loginId: user.loginId,
      displayName: user.displayName,
      createdAt: user.createdAt,
      rating: user.rating,
      ratedGames: user.ratedGames,
      ratingTemperature: ratingTemperatureForGames(user.ratedGames),
    };
  }

  return {
    sessionToken: session.token,
    sessionKind: "guest",
    authenticated: false,
    anonymous: true,
    userId: null,
    loginId: null,
    displayName: session.guestName,
    createdAt: session.createdAt,
  };
}

function exposeViewer(viewer) {
  if (!viewer) return null;
  return {
    sessionKind: viewer.sessionKind,
    authenticated: viewer.authenticated,
    anonymous: viewer.anonymous,
    userId: viewer.userId,
    loginId: viewer.loginId,
    displayName: viewer.displayName,
    createdAt: viewer.createdAt,
    rating: viewer.authenticated ? normalizeRatingValue(viewer.rating, INITIAL_RATING) : null,
    ratedGames: viewer.authenticated ? normalizeRatedGames(viewer.ratedGames) : null,
    ratingTemperature: viewer.authenticated ? ratingTemperatureForGames(viewer.ratedGames) : null,
    presence: getPresenceForViewer(viewer),
  };
}

function exposeViewerFromSession(session) {
  return exposeViewer(buildViewer(session));
}

function createSession(kind, payload) {
  const session = {
    token: randomUUID(),
    kind,
    userId: payload.userId || null,
    guestName: payload.guestName || null,
    createdAt: new Date().toISOString(),
    lastSeenAt: new Date().toISOString(),
  };

  persistentState.sessions.push(session);
  return session;
}

function createGuestSession(displayName = "") {
  const guestName = normalizeDisplayName(displayName, createGuestName());
  const session = createSession("guest", { guestName });
  return { session, viewer: buildViewer(session) };
}

function createUserAccount({ loginId, displayName, password }) {
  const cleanLoginId = normalizeLoginId(loginId);
  const cleanDisplayName = normalizeDisplayName(displayName);

  if (cleanLoginId.length < 3) {
    throw createHttpError(400, "User ID must be at least 3 characters.");
  }
  if (!/^[a-z0-9_.-]+$/.test(cleanLoginId)) {
    throw createHttpError(400, "User ID can only contain letters, numbers, dot, dash, and underscore.");
  }
  if (cleanDisplayName.length < 2) {
    throw createHttpError(400, "Display name must be at least 2 characters.");
  }
  if (String(password || "").length < 6) {
    throw createHttpError(400, "Password must be at least 6 characters.");
  }
  if (findUserByLoginId(cleanLoginId)) {
    throw createHttpError(409, `User ID ${cleanLoginId} is already taken.`);
  }

  const { salt, hash } = hashPassword(password);
  const user = {
    id: randomUUID(),
    loginId: cleanLoginId,
    displayName: cleanDisplayName,
    rating: INITIAL_RATING,
    ratedGames: 0,
    passwordSalt: salt,
    passwordHash: hash,
    createdAt: new Date().toISOString(),
  };

  persistentState.users.push(user);
  const session = createSession("user", { userId: user.id });
  return { user, session, viewer: buildViewer(session) };
}

function loginUserAccount({ loginId, password }) {
  const user = findUserByLoginId(loginId);
  if (!user || !verifyPassword(String(password || ""), user)) {
    throw createHttpError(401, "User ID or password is incorrect.");
  }

  const session = createSession("user", { userId: user.id });
  return { user, session, viewer: buildViewer(session) };
}

function logoutSession(token) {
  persistentState.sessions = persistentState.sessions.filter((session) => session.token !== token);
}

function cloneGameResult(result) {
  if (!result) return null;
  return {
    ...result,
    highlight: Array.isArray(result.highlight) ? result.highlight.map(([row, col]) => [row, col]) : [],
  };
}

function cloneMatchState(state) {
  if (!state) return null;
  return {
    board: Array.isArray(state.board) ? state.board.map((row) => [...row]) : [],
    turn: state.turn,
    times: state.times ? { ...state.times } : { B: null, W: null },
    result: cloneGameResult(state.result),
    last: Array.isArray(state.last) ? [...state.last] : null,
  };
}

function createActionState() {
  return {
    host: false,
    guest: false,
    requestedBy: null,
    updatedAt: "",
  };
}

function clearActionState(actionState) {
  if (!actionState) {
    return createActionState();
  }
  actionState.host = false;
  actionState.guest = false;
  actionState.requestedBy = null;
  actionState.updatedAt = "";
  return actionState;
}

function actionRequestedByOpponent(actionState, role) {
  if (!actionState || !role || !actionState.requestedBy) {
    return false;
  }
  return actionState.requestedBy !== role && !!actionState[actionState.requestedBy] && !actionState[role];
}

function colorForRole(game, role) {
  if (!game?.seats || !role) return null;
  if (game.seats.B === role) return "B";
  if (game.seats.W === role) return "W";
  return null;
}

function roleForColor(game, color) {
  if (!game?.seats || !color) return null;
  return game.seats[color] || null;
}

function assignSeatsForGame(room) {
  const colorMode = room?.config?.colorMode || "random";
  if (colorMode === "black") {
    return { B: "host", W: "guest" };
  }
  if (colorMode === "white") {
    return { B: "guest", W: "host" };
  }
  return Math.random() < 0.5
    ? { B: "host", W: "guest" }
    : { B: "guest", W: "host" };
}

function resetNegotiationState(room) {
  room.rematch = { host: false, guest: false };
  room.requests = {
    rematch: createActionState(),
    draw: createActionState(),
    takeback: createActionState(),
  };
}

function clearLiveRequests(room) {
  if (!room?.requests) return;
  clearActionState(room.requests.draw);
  clearActionState(room.requests.takeback);
}

function participantFromViewer(viewer) {
  if (!viewer?.sessionToken) return null;
  return decorateIdentityWithRating({
    sessionToken: viewer.sessionToken,
    sessionKind: viewer.sessionKind,
    authenticated: viewer.authenticated,
    anonymous: viewer.anonymous,
    userId: viewer.userId || null,
    loginId: viewer.loginId || null,
    displayName: viewer.displayName,
    createdAt: viewer.createdAt,
    rating: viewer.rating ?? null,
    ratedGames: viewer.ratedGames ?? null,
  }, viewer.rating ?? null, viewer.ratedGames ?? null);
}

function publicParticipant(participant) {
  if (!participant) return null;
  return decorateIdentityWithRating({
    sessionKind: participant.sessionKind,
    authenticated: participant.authenticated,
    anonymous: participant.anonymous,
    userId: participant.userId,
    loginId: participant.loginId,
    displayName: participant.displayName,
    createdAt: participant.createdAt,
    rating: participant.rating ?? null,
    ratedGames: participant.ratedGames ?? null,
  }, participant.rating ?? null, participant.ratedGames ?? null);
}

function participantMatchesIdentity(participant, identity) {
  if (!participant || !identity?.sessionToken) {
    return false;
  }

  if (participant.userId && identity.userId) {
    return participant.userId === identity.userId;
  }

  return participant.sessionToken === identity.sessionToken;
}

function participantMatchesViewer(participant, viewer) {
  return participantMatchesIdentity(participant, viewer);
}

function syncParticipantFromViewer(participant, viewer) {
  if (!participantMatchesViewer(participant, viewer)) {
    return participant;
  }

  participant.sessionToken = viewer.sessionToken;
  participant.sessionKind = viewer.sessionKind;
  participant.authenticated = viewer.authenticated;
  participant.anonymous = viewer.anonymous;
  participant.userId = viewer.userId || null;
  participant.loginId = viewer.loginId || null;
  participant.displayName = viewer.displayName;
  participant.createdAt = viewer.createdAt;
  participant.rating = viewer.authenticated ? normalizeRatingValue(viewer.rating, INITIAL_RATING) : null;
  participant.ratedGames = viewer.authenticated ? normalizeRatedGames(viewer.ratedGames) : null;
  participant.ratingTemperature = viewer.authenticated ? ratingTemperatureForGames(viewer.ratedGames) : null;
  return participant;
}

function findMatchingSpectator(room, viewer) {
  if (!room?.spectators?.length) {
    return null;
  }
  return room.spectators.find((spectator) => participantMatchesViewer(spectator, viewer)) || null;
}

function syncSpectatorFromViewer(room, viewer) {
  const spectator = findMatchingSpectator(room, viewer);
  if (!spectator) {
    return null;
  }
  syncParticipantFromViewer(spectator, viewer);
  return spectator;
}

function scoreForRole(game, role) {
  const result = game?.result;
  if (result?.draw) return 0.5;
  if (!result?.winner || !role) return null;
  const winnerRole = roleForColor(game, result.winner);
  if (!winnerRole) return null;
  return winnerRole === role ? 1 : 0;
}

function expectedScore(rating, opponentRating) {
  return 1 / (1 + 10 ** ((opponentRating - rating) / 400));
}

function outcomeForRole(game, role) {
  const result = game?.result;
  if (result?.draw) return "draw";
  if (!result?.winner || !role) return "unknown";
  const winnerRole = roleForColor(game, result.winner);
  if (!winnerRole) return "unknown";
  return winnerRole === role ? "win" : "loss";
}

function seatLabelForRole(game, role) {
  const color = colorForRole(game, role);
  return color ? pName(color) : null;
}

function copyRequests(requests) {
  return {
    rematch: { ...(requests?.rematch || createActionState()) },
    draw: { ...(requests?.draw || createActionState()) },
    takeback: { ...(requests?.takeback || createActionState()) },
  };
}

function copyChatMessages(messages = []) {
  return messages.map((message) => ({
    ...message,
    sender: message.sender ? { ...message.sender } : null,
  }));
}

function buildHistoricalParticipantSnapshot(participant, ratingSummary = null) {
  if (!participant) return null;
  return {
    ...participant,
    rating: ratingSummary ? ratingSummary.before : participant.rating ?? null,
    ratingBefore: ratingSummary ? ratingSummary.before : participant.rating ?? null,
    ratingAfter: ratingSummary ? ratingSummary.after : participant.rating ?? null,
    ratingDelta: ratingSummary ? ratingSummary.delta : 0,
    ratingTemperature: ratingSummary ? ratingSummary.temperatureBefore : participant.ratingTemperature ?? null,
  };
}

function applyFinishedGameRatings(room) {
  const game = room?.currentGame;
  if (!game || !game.result) {
    return null;
  }

  const hostUser = room.hostPlayer?.userId ? findUserById(room.hostPlayer.userId) : null;
  const guestUser = room.guestPlayer?.userId ? findUserById(room.guestPlayer.userId) : null;
  if (!hostUser || !guestUser || hostUser.id === guestUser.id) {
    return null;
  }

  const hostScore = scoreForRole(game, "host");
  const guestScore = scoreForRole(game, "guest");
  if (hostScore === null || guestScore === null) {
    return null;
  }

  const hostBefore = normalizeRatingValue(hostUser.rating, INITIAL_RATING);
  const guestBefore = normalizeRatingValue(guestUser.rating, INITIAL_RATING);
  const hostGamesBefore = normalizeRatedGames(hostUser.ratedGames);
  const guestGamesBefore = normalizeRatedGames(guestUser.ratedGames);
  const hostK = ratingKForGames(hostGamesBefore);
  const guestK = ratingKForGames(guestGamesBefore);
  const hostAfter = Math.max(100, Math.round(hostBefore + hostK * (hostScore - expectedScore(hostBefore, guestBefore))));
  const guestAfter = Math.max(100, Math.round(guestBefore + guestK * (guestScore - expectedScore(guestBefore, hostBefore))));

  hostUser.rating = hostAfter;
  hostUser.ratedGames = hostGamesBefore + 1;
  guestUser.rating = guestAfter;
  guestUser.ratedGames = guestGamesBefore + 1;

  if (room.hostPlayer) {
    room.hostPlayer.rating = hostAfter;
    room.hostPlayer.ratedGames = hostUser.ratedGames;
    room.hostPlayer.ratingTemperature = ratingTemperatureForGames(hostUser.ratedGames);
  }
  if (room.guestPlayer) {
    room.guestPlayer.rating = guestAfter;
    room.guestPlayer.ratedGames = guestUser.ratedGames;
    room.guestPlayer.ratingTemperature = ratingTemperatureForGames(guestUser.ratedGames);
  }

  return {
    rated: true,
    host: {
      before: hostBefore,
      after: hostAfter,
      delta: hostAfter - hostBefore,
      gamesBefore: hostGamesBefore,
      gamesAfter: hostUser.ratedGames,
      temperatureBefore: ratingTemperatureForGames(hostGamesBefore),
      temperatureAfter: ratingTemperatureForGames(hostUser.ratedGames),
    },
    guest: {
      before: guestBefore,
      after: guestAfter,
      delta: guestAfter - guestBefore,
      gamesBefore: guestGamesBefore,
      gamesAfter: guestUser.ratedGames,
      temperatureBefore: ratingTemperatureForGames(guestGamesBefore),
      temperatureAfter: ratingTemperatureForGames(guestUser.ratedGames),
    },
  };
}

function buildCurrentGameSummary(room) {
  if (!room.currentGame) {
    return null;
  }

  return {
    id: room.currentGame.id,
    index: room.currentGame.index,
    roomId: room.id,
    startedAt: room.currentGame.startedAt,
    finishedAt: room.currentGame.finishedAt,
    result: cloneGameResult(room.currentGame.result),
    moves: Array.isArray(room.currentGame.moves) ? room.currentGame.moves.map((move) => ({ ...move })) : [],
    players: room.currentGame.players,
    seats: room.currentGame.seats,
    rating: room.currentGame.rating || null,
  };
}

function startNewGame(room) {
  const startedAt = new Date().toISOString();
  const seats = assignSeatsForGame(room);
  const game = {
    id: randomUUID(),
    index: room.games.length + 1,
    roomId: room.id,
    startedAt,
    finishedAt: null,
    result: null,
    moves: [],
    historyStates: [],
    historyRecorded: false,
    players: {
      host: publicParticipant(room.hostPlayer),
      guest: publicParticipant(room.guestPlayer),
    },
    seats,
  };

  room.games.push(game);
  room.currentGame = game;
  room.gameState = createMatchState(room.config);
  room.phase = "active";
  resetNegotiationState(room);
  room.updatedAt = startedAt;
  restartTimer(room);
  return game;
}

function finishCurrentGame(room) {
  if (!room?.currentGame || room.currentGame.finishedAt) {
    return;
  }

  room.currentGame.finishedAt = new Date().toISOString();
  room.currentGame.result = cloneGameResult(room.gameState?.result);
  room.currentGame.rating = applyFinishedGameRatings(room);
  recordFinishedGameHistory(room);
}

function upsertMatchHistoryEntry(entry) {
  const next = persistentState.matchHistory.filter((item) => item.id !== entry.id);
  next.push(entry);
  persistentState.matchHistory = next
    .sort((left, right) => String(right.finishedAt || "").localeCompare(String(left.finishedAt || "")))
    .slice(0, 500);
  void persistState();
}

function recordFinishedGameHistory(room) {
  const game = room?.currentGame;
  if (!game || game.historyRecorded || !game.finishedAt || !game.result) {
    return;
  }

  const hostOutcome = outcomeForRole(game, "host");
  const guestOutcome = outcomeForRole(game, "guest");

  if (room.hostPlayer?.userId) {
    upsertMatchHistoryEntry({
      id: `${game.id}:host:${room.hostPlayer.userId}`,
      userId: room.hostPlayer.userId,
      gameId: game.id,
      roomId: room.id,
      gameIndex: game.index,
      finishedAt: game.finishedAt,
      startedAt: game.startedAt,
      outcome: hostOutcome,
      role: "host",
      player: buildHistoricalParticipantSnapshot(game.players?.host, game.rating?.host),
      opponent: buildHistoricalParticipantSnapshot(game.players?.guest, game.rating?.guest),
      rating: game.rating?.host || null,
      config: room.config,
    });
  }

  if (room.guestPlayer?.userId) {
    upsertMatchHistoryEntry({
      id: `${game.id}:guest:${room.guestPlayer.userId}`,
      userId: room.guestPlayer.userId,
      gameId: game.id,
      roomId: room.id,
      gameIndex: game.index,
      finishedAt: game.finishedAt,
      startedAt: game.startedAt,
      outcome: guestOutcome,
      role: "guest",
      player: buildHistoricalParticipantSnapshot(game.players?.guest, game.rating?.guest),
      opponent: buildHistoricalParticipantSnapshot(game.players?.host, game.rating?.host),
      rating: game.rating?.guest || null,
      config: room.config,
    });
  }

  game.historyRecorded = true;
}

function sendChatMessage(room, access, viewer, text) {
  if (!room || !access?.mode) {
    throw createHttpError(409, "This room is not available for chat.");
  }
  const trimmed = String(text || "").trim().replace(/\s+/g, " ").slice(0, 280);
  if (!trimmed) {
    throw createHttpError(400, "Chat message cannot be empty.");
  }

  const sender = access.role === "host"
    ? publicParticipant(room.hostPlayer)
    : access.role === "guest"
      ? publicParticipant(room.guestPlayer)
      : publicParticipant(syncSpectatorFromViewer(room, viewer) || addSpectator(room, viewer));
  room.chatMessages.push({
    id: randomUUID(),
    role: access.role || "spectator",
    text: trimmed,
    createdAt: new Date().toISOString(),
    sender,
  });
  room.chatMessages = room.chatMessages.slice(-120);
  room.updatedAt = new Date().toISOString();
}

function undoLastMove(room) {
  if (!room?.currentGame?.historyStates?.length || !room.currentGame.moves.length) {
    throw createHttpError(409, "There is no move to take back.");
  }
  room.gameState = room.currentGame.historyStates.pop();
  room.currentGame.moves.pop();
  room.phase = "active";
  room.updatedAt = new Date().toISOString();
  clearLiveRequests(room);
  restartTimer(room);
}

function resolveRoomActionRequest(room, role, kind, operation = "request") {
  if (!room || !role) {
    throw createHttpError(409, "This room action is not available.");
  }
  if (!["rematch", "draw", "takeback"].includes(kind)) {
    throw createHttpError(400, "That room action is not supported.");
  }
  if (!["request", "decline", "cancel"].includes(operation)) {
    throw createHttpError(400, "That room action decision is not supported.");
  }
  if (kind === "rematch" && room.phase !== "finished") {
    throw createHttpError(409, "A rematch is only available after a finished game.");
  }
  if ((kind === "draw" || kind === "takeback") && room.phase !== "active") {
    throw createHttpError(409, `${kind === "draw" ? "Draw" : "Takeback"} requests are only available during an active game.`);
  }

  const actionState = room.requests?.[kind] || createActionState();
  room.requests[kind] = actionState;

  if (operation === "decline" || operation === "cancel") {
    clearActionState(actionState);
    if (kind === "rematch") {
      room.rematch = { host: false, guest: false };
    }
    room.updatedAt = new Date().toISOString();
    return;
  }

  actionState[role] = true;
  actionState.requestedBy = role;
  actionState.updatedAt = new Date().toISOString();
  if (kind === "rematch") {
    room.rematch[role] = true;
  }

  const otherRole = role === "host" ? "guest" : "host";
  if (!actionState[otherRole]) {
    room.updatedAt = actionState.updatedAt;
    return;
  }

  if (kind === "rematch") {
    startNewGame(room);
    return;
  }

  if (kind === "draw") {
    room.gameState = {
      ...room.gameState,
      result: {
        winner: null,
        draw: true,
        msg: "Draw agreed",
        sub: "Game drawn.",
        highlight: [],
      },
    };
    room.phase = "finished";
    stopTimer(room);
    room.updatedAt = new Date().toISOString();
    finishCurrentGame(room);
    clearLiveRequests(room);
    return;
  }

  undoLastMove(room);
}

function roomIsPubliclyVisible(room) {
  if (!room?.publicVisible) {
    return false;
  }
  return room.visibility === "public" || room.phase !== "waiting";
}

function roomCanAcceptSpectators(room) {
  return !!room && room.phase !== "closed" && room.phase !== "waiting" && !!room.currentGame;
}

function addSpectator(room, viewer) {
  if (!roomCanAcceptSpectators(room)) {
    throw createHttpError(409, `Room ${room?.id || ""} is not available for spectating.`);
  }
  if (!viewer?.sessionToken) {
    throw createHttpError(401, "A session is required to spectate a room.");
  }

  const existing = syncSpectatorFromViewer(room, viewer);
  if (existing) {
    return existing;
  }

  const spectator = participantFromViewer(viewer);
  room.spectators.push(spectator);
  room.updatedAt = new Date().toISOString();
  return spectator;
}

function removeSpectator(room, viewer) {
  if (!room?.spectators?.length || !viewer?.sessionToken) {
    return false;
  }
  const nextSpectators = room.spectators.filter((spectator) => !participantMatchesViewer(spectator, viewer));
  if (nextSpectators.length === room.spectators.length) {
    return false;
  }
  room.spectators = nextSpectators;
  room.updatedAt = new Date().toISOString();
  return true;
}

function findRoomAccess(roomId, viewer) {
  const room = rooms.get(normalizeRoomId(roomId));
  if (!room) {
    return { room: null, role: null, mode: null };
  }

  if (participantMatchesViewer(room.hostPlayer, viewer)) {
    syncParticipantFromViewer(room.hostPlayer, viewer);
    return { room, role: "host", mode: "host" };
  }
  if (participantMatchesViewer(room.guestPlayer, viewer)) {
    syncParticipantFromViewer(room.guestPlayer, viewer);
    return { room, role: "guest", mode: "guest" };
  }
  if (syncSpectatorFromViewer(room, viewer)) {
    return { room, role: null, mode: "spectate" };
  }
  return { room, role: null, mode: null };
}

function buildRoomSummary(room, viewer = null) {
  const access = findRoomAccess(room.id, viewer);
  const host = publicParticipant(room.hostPlayer);
  const guest = publicParticipant(room.guestPlayer);
  const isInvitedToViewer = !!(viewer?.userId && room.invitedUserId && viewer.userId === room.invitedUserId);
  const isSpectating = access.mode === "spectate";

  let canJoin = false;
  let canSpectate = false;
  let joinReason = "";

  if (room.phase === "closed") {
    joinReason = "closed";
  } else if (!viewer) {
    joinReason = "no_session";
  } else if (access.role === "host") {
    joinReason = "host";
  } else if (access.role === "guest") {
    joinReason = "guest";
  } else if (isSpectating) {
    joinReason = "spectating";
  } else if (room.phase === "waiting") {
    if (room.guestPlayer) {
      joinReason = "full";
    } else if (room.invitedUserId && viewer.userId !== room.invitedUserId) {
      joinReason = "invite_only";
    } else {
      canJoin = true;
    }
  } else if (roomCanAcceptSpectators(room)) {
    canSpectate = true;
    joinReason = "spectate";
  } else {
    joinReason = "unavailable";
  }

  return {
    id: room.id,
    phase: room.phase,
    visibility: room.visibility,
    publicVisible: !!room.publicVisible,
    listedPublicly: roomIsPubliclyVisible(room),
    createdAt: room.createdAt,
    updatedAt: room.updatedAt,
    config: room.config,
    host,
    guest,
    spectators: (room.spectators || []).map((spectator) => publicParticipant(spectator)),
    spectatorCount: room.spectators?.length || 0,
    invitedUser: room.invitedUserId ? publicUser(findUserById(room.invitedUserId)) : null,
    currentGameId: room.currentGame?.id || "",
    currentGameIndex: room.currentGame?.index || 0,
    isMine: access.role !== null,
    isSpectating,
    isInvitedToViewer,
    canJoin,
    canSpectate,
    joinReason,
  };
}

function roomNotice(room, access) {
  const roomLabel = room.currentGame ? `Room ${room.id} - Game ${room.currentGame.index}` : `Room ${room.id}`;
  const role = access?.role || null;

  if (role && room.phase === "active") {
    if (actionRequestedByOpponent(room.requests?.takeback, role)) {
      return `${roomLabel}. Opponent requested a takeback.`;
    }
    if (actionRequestedByOpponent(room.requests?.draw, role)) {
      return `${roomLabel}. Opponent offered a draw.`;
    }
    if (room.requests?.takeback?.[role] && !room.requests?.takeback?.[role === "host" ? "guest" : "host"]) {
      return `${roomLabel}. Takeback request sent. Waiting for opponent.`;
    }
    if (room.requests?.draw?.[role] && !room.requests?.draw?.[role === "host" ? "guest" : "host"]) {
      return `${roomLabel}. Draw offer sent. Waiting for opponent.`;
    }
  }
  if (room.phase === "finished" && actionRequestedByOpponent(room.requests?.rematch, role)) {
    return `${roomLabel}. Opponent requested a rematch.`;
  }
  if (room.phase === "waiting") {
    return role === "host" ? `${roomLabel} created. Share the link or wait for your invitee.` : `${roomLabel}. Waiting for host.`;
  }
  if (access?.mode === "spectate") {
    return room.phase === "finished"
      ? `${roomLabel}. Spectating a finished game.`
      : `${roomLabel}. Spectating live play.`;
  }
  if (room.phase === "active") {
    return `${roomLabel}. You are ${seatLabelForRole(room.currentGame, role) || "playing"}.`;
  }
  if (room.phase === "finished") {
    return room.rematch[role] ? `${roomLabel}. Rematch requested.` : `${roomLabel}. Game finished.`;
  }
  if (room.phase === "closed") {
    return room.closeMessages[role] || `${roomLabel} closed.`;
  }
  return roomLabel;
}

function snapshotFor(room, access, viewer) {
  const payload = {
    type: room.phase === "closed" ? "room_closed" : "snapshot",
    roomId: room.id,
    role: access?.role || null,
    mode: access?.mode || null,
    phase: room.phase,
    config: room.config,
    gameState: room.gameState,
    rematch: room.rematch,
    requests: copyRequests(room.requests),
    game: buildCurrentGameSummary(room),
    chatMessages: copyChatMessages(room.chatMessages),
    notice: roomNotice(room, access),
    roomSummary: buildRoomSummary(room, viewer),
  };

  if (room.phase === "closed") {
    const closeKey = access?.role || access?.mode || "spectate";
    payload.message = room.closeMessages[closeKey] || `${room.currentGame ? `Room ${room.id} - Game ${room.currentGame.index}` : `Room ${room.id}`} closed.`;
  }

  return payload;
}

function createRoom(config, hostViewer, options = {}) {
  const roomId = generateRoomId();
  const room = {
    id: roomId,
    hostPlayer: participantFromViewer(hostViewer),
    guestPlayer: null,
    invitedUserId: options.invitedUserId || null,
    visibility: options.invitedUserId ? "invite" : "public",
    publicVisible: options.publicVisible !== false,
    config: sanitizeConfig(config),
    gameState: null,
    phase: "waiting",
    games: [],
    currentGame: null,
    rematch: { host: false, guest: false },
    requests: {
      rematch: createActionState(),
      draw: createActionState(),
      takeback: createActionState(),
    },
    spectators: [],
    chatMessages: [],
    closeMessages: { host: "", guest: "", spectate: "" },
    timerId: null,
    cleanupId: null,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };

  rooms.set(roomId, room);
  return room;
}

function closeRoom(room, hostMessage, guestMessage, spectatorMessage = "") {
  if (!room || room.phase === "closed") {
    return;
  }

  stopTimer(room);
  room.phase = "closed";
  room.updatedAt = new Date().toISOString();
  room.closeMessages = {
    host: hostMessage,
    guest: guestMessage,
    spectate: spectatorMessage || `Room ${room.id} closed.`,
  };
  scheduleRoomCleanup(room);
}

function restartTimer(room) {
  stopTimer(room);
  if (!room.config || room.config.baseSeconds === null || room.phase !== "active" || !room.gameState) {
    return;
  }

  room.timerId = setInterval(() => {
    const next = tickClock(room.gameState, room.config);
    if (next === room.gameState) {
      return;
    }

    room.gameState = next;
    room.updatedAt = new Date().toISOString();
    if (room.gameState.result) {
      room.phase = "finished";
      stopTimer(room);
      finishCurrentGame(room);
    }
  }, 1000);
}

function joinRoom(roomId, viewer) {
  const cleanRoomId = normalizeRoomId(roomId);
  if (!cleanRoomId) {
    throw createHttpError(400, "Room code is required.");
  }
  if (!viewer?.sessionToken) {
    throw createHttpError(401, "A session is required to join a room.");
  }

  const room = rooms.get(cleanRoomId);
  if (!room || room.phase === "closed") {
    throw createHttpError(404, `Room ${cleanRoomId} does not exist.`);
  }
  if (participantMatchesViewer(room.hostPlayer, viewer)) {
    syncParticipantFromViewer(room.hostPlayer, viewer);
    return { room, role: "host", mode: "host" };
  }
  if (participantMatchesViewer(room.guestPlayer, viewer)) {
    syncParticipantFromViewer(room.guestPlayer, viewer);
    return { room, role: "guest", mode: "guest" };
  }
  if (syncSpectatorFromViewer(room, viewer)) {
    return { room, role: null, mode: "spectate" };
  }

  if (room.phase === "waiting") {
    if (room.guestPlayer) {
      throw createHttpError(409, `Room ${cleanRoomId} already has two players.`);
    }
    if (room.invitedUserId && room.invitedUserId !== viewer.userId) {
      throw createHttpError(403, `Room ${cleanRoomId} is reserved for another user.`);
    }

    room.guestPlayer = participantFromViewer(viewer);
    startNewGame(room);
    return { room, role: "guest", mode: "guest" };
  }

  addSpectator(room, viewer);
  return { room, role: null, mode: "spectate" };
}

function move(room, role, row, col) {
  if (!room || room.phase !== "active" || !room.gameState) {
    throw createHttpError(409, "This room is not accepting moves.");
  }

  const expectedRole = roleForColor(room.currentGame, room.gameState.turn);
  if (role !== expectedRole) {
    throw createHttpError(409, "It is not your turn.");
  }
  if (!Number.isInteger(row) || !Number.isInteger(col)) {
    throw createHttpError(400, "Move coordinates are invalid.");
  }

  const next = applyMove(room.gameState, room.config, row, col);
  if (!next) {
    throw createHttpError(409, "That move is not legal.");
  }

  room.currentGame?.historyStates?.push(cloneMatchState(room.gameState));
  room.currentGame?.moves?.push({
    row,
    col,
    player: room.gameState.turn,
    ply: (room.currentGame?.moves?.length || 0) + 1,
    notation: `${String.fromCharCode(65 + col)}${row + 1}`,
    playedAt: new Date().toISOString(),
  });
  clearLiveRequests(room);
  room.gameState = next;
  room.updatedAt = new Date().toISOString();
  if (room.gameState.result) {
    room.phase = "finished";
    stopTimer(room);
    finishCurrentGame(room);
  } else {
    restartTimer(room);
  }
}

function requestRematch(room, role) {
  resolveRoomActionRequest(room, role, "rematch", "request");
}

function leaveRoom(room, access, viewer) {
  if (!room || !access?.mode) {
    return;
  }

  if (access.mode === "spectate") {
    removeSpectator(room, viewer);
    return;
  }

  const role = access.role;

  if (role === "host") {
    closeRoom(room, `You left room ${room.id}.`, `Room ${room.id} closed because the host left.`);
    return;
  }

  closeRoom(room, `Room ${room.id} closed because the guest left. Host again to create a new room.`, `You left room ${room.id}.`);
}

function getLobbyState(viewer) {
  const summaries = [...rooms.values()]
    .filter((room) => room.phase !== "closed")
    .map((room) => buildRoomSummary(room, viewer))
    .sort((left, right) => String(right.updatedAt).localeCompare(String(left.updatedAt)));

  return {
    myRooms: summaries.filter((room) => room.isMine),
    spectatingRooms: summaries.filter((room) => room.isSpectating),
    invites: summaries.filter((room) => room.isInvitedToViewer && room.phase === "waiting"),
    publicRooms: summaries.filter((room) => room.listedPublicly && !room.isMine && !room.isSpectating),
    activeRooms: summaries.filter((room) => room.phase !== "waiting" && room.isMine),
  };
}

function isSessionRecentlySeen(session) {
  if (!session?.lastSeenAt) {
    return false;
  }
  const seenAt = Date.parse(session.lastSeenAt);
  return Number.isFinite(seenAt) && Date.now() - seenAt <= ACTIVE_SESSION_WINDOW_MS;
}

function findBestRoomPresence(matchParticipant) {
  const candidates = [];

  for (const room of rooms.values()) {
    if (room.phase === "closed") {
      continue;
    }

    if (matchParticipant(room.hostPlayer) || matchParticipant(room.guestPlayer)) {
      candidates.push({
        room,
        status: room.phase === "waiting" ? "online" : "in_game",
        priority: room.phase === "waiting" ? 1 : 3,
      });
      continue;
    }

    if ((room.spectators || []).some((spectator) => matchParticipant(spectator))) {
      candidates.push({
        room,
        status: "spectating",
        priority: 2,
      });
    }
  }

  candidates.sort((left, right) => (
    right.priority - left.priority
    || String(right.room.updatedAt || "").localeCompare(String(left.room.updatedAt || ""))
  ));
  return candidates[0] || null;
}

function buildPresencePayload(status, room = null, { revealRoomId = false } = {}) {
  return {
    status,
    roomId: revealRoomId && room ? room.id : "",
    roomPhase: room?.phase || null,
    canSpectate: !!(room && revealRoomId && roomCanAcceptSpectators(room)),
    listedPublicly: !!(room && roomIsPubliclyVisible(room)),
  };
}

function getPresenceForViewer(viewer) {
  if (!viewer?.sessionToken) {
    return buildPresencePayload("offline");
  }

  const roomPresence = findBestRoomPresence((participant) => participantMatchesViewer(participant, viewer));
  if (roomPresence) {
    return buildPresencePayload(roomPresence.status, roomPresence.room, { revealRoomId: true });
  }

  const session = findSessionByToken(viewer.sessionToken);
  return buildPresencePayload(session && isSessionRecentlySeen(session) ? "online" : "offline");
}

function getPresenceForUser(user, viewer = null) {
  if (!user?.id) {
    return buildPresencePayload("offline");
  }

  const roomPresence = findBestRoomPresence((participant) => participant?.userId === user.id);
  if (roomPresence) {
    const revealRoomId = !!(viewer?.userId && viewer.userId === user.id) || roomIsPubliclyVisible(roomPresence.room);
    return buildPresencePayload(roomPresence.status, roomPresence.room, { revealRoomId });
  }

  const isOnline = persistentState.sessions.some((session) => session.kind === "user" && session.userId === user.id && isSessionRecentlySeen(session));
  return buildPresencePayload(isOnline ? "online" : "offline");
}

function sortMatchHistoryEntries(entries = []) {
  return [...entries].sort((left, right) => String(right.finishedAt || "").localeCompare(String(left.finishedAt || "")));
}

function getMatchHistoryEntriesForUserId(userId) {
  if (!userId) {
    return [];
  }

  return sortMatchHistoryEntries(persistentState.matchHistory.filter((entry) => entry.userId === userId));
}

function isRatedHistoryEntry(entry) {
  const before = Number(entry?.rating?.before ?? entry?.player?.ratingBefore);
  const after = Number(entry?.rating?.after ?? entry?.player?.ratingAfter);
  return Number.isFinite(before) && Number.isFinite(after);
}

function roundSummaryNumber(value, decimals = 1) {
  if (!Number.isFinite(value)) {
    return 0;
  }
  const factor = 10 ** decimals;
  return Math.round(value * factor) / factor;
}

function buildHistorySummary(entries = []) {
  const history = sortMatchHistoryEntries(entries);
  const summary = {
    totalGames: history.length,
    wins: 0,
    losses: 0,
    draws: 0,
    winRate: 0,
    nonLossRate: 0,
    ratedGames: 0,
    unratedGames: 0,
    totalRatedDelta: 0,
    averageRatedDelta: 0,
    bestRatedGain: 0,
    worstRatedDrop: 0,
    currentStreak: { outcome: null, length: 0 },
    bestWinStreak: 0,
    firstPlayedAt: history.length ? history[history.length - 1].finishedAt || "" : "",
    lastPlayedAt: history[0]?.finishedAt || "",
  };

  const ratedDeltas = [];
  let currentWinStreak = 0;
  let currentStreakLocked = false;

  history.forEach((entry, index) => {
    const outcome = entry?.outcome;
    if (outcome === "win") {
      summary.wins += 1;
      currentWinStreak += 1;
      summary.bestWinStreak = Math.max(summary.bestWinStreak, currentWinStreak);
    } else if (outcome === "loss") {
      summary.losses += 1;
      currentWinStreak = 0;
    } else if (outcome === "draw") {
      summary.draws += 1;
      currentWinStreak = 0;
    } else {
      currentWinStreak = 0;
    }

    if (!currentStreakLocked) {
      if (index === 0 && ["win", "loss", "draw"].includes(outcome)) {
        summary.currentStreak = { outcome, length: 1 };
      } else if (summary.currentStreak.outcome && outcome === summary.currentStreak.outcome) {
        summary.currentStreak.length += 1;
      } else {
        currentStreakLocked = true;
      }
    }

    if (!isRatedHistoryEntry(entry)) {
      return;
    }

    summary.ratedGames += 1;
    const delta = Number(entry?.rating?.delta ?? entry?.player?.ratingDelta ?? 0);
    if (Number.isFinite(delta)) {
      ratedDeltas.push(delta);
    }
  });

  summary.unratedGames = Math.max(0, summary.totalGames - summary.ratedGames);
  summary.winRate = summary.totalGames ? roundSummaryNumber((summary.wins / summary.totalGames) * 100, 1) : 0;
  summary.nonLossRate = summary.totalGames ? roundSummaryNumber(((summary.wins + summary.draws) / summary.totalGames) * 100, 1) : 0;

  if (ratedDeltas.length) {
    summary.totalRatedDelta = ratedDeltas.reduce((accumulator, delta) => accumulator + delta, 0);
    summary.averageRatedDelta = roundSummaryNumber(summary.totalRatedDelta / ratedDeltas.length, 1);
    summary.bestRatedGain = Math.max(...ratedDeltas);
    summary.worstRatedDrop = Math.min(...ratedDeltas);
  }

  return summary;
}

function buildHeadToHead(viewer, user, limit = 8) {
  if (!viewer?.userId || !user?.id || viewer.userId === user.id) {
    return null;
  }

  const history = getMatchHistoryEntriesForUserId(viewer.userId)
    .filter((entry) => entry?.opponent?.userId === user.id || (entry?.opponent?.loginId && entry.opponent.loginId === user.loginId));
  const recent = history.slice(0, Math.max(1, limit));

  return {
    opponent: publicUser(user),
    summary: buildHistorySummary(history),
    recent,
  };
}

function searchUsers(query, viewer) {
  const cleanQuery = normalizeLoginId(query);
  if (!cleanQuery) {
    return [];
  }

  return persistentState.users
    .filter((user) => user.id !== viewer?.userId)
    .filter((user) => user.loginId.includes(cleanQuery) || user.displayName.toLowerCase().includes(cleanQuery))
    .slice(0, 12)
    .map(publicUser);
}

async function readJsonBody(req) {
  const chunks = [];
  let totalLength = 0;

  for await (const chunk of req) {
    totalLength += chunk.length;
    if (totalLength > 64 * 1024) {
      throw createHttpError(413, "Request body is too large.");
    }
    chunks.push(chunk);
  }

  if (!chunks.length) {
    return {};
  }

  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw createHttpError(400, "Could not parse the request body.");
  }
}

function writeCorsHeaders(res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", `Content-Type, Authorization, ${SESSION_STORAGE_KEY}`);
  res.setHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
}

function writeJson(res, statusCode, payload) {
  writeCorsHeaders(res);
  res.writeHead(statusCode, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
  res.end(JSON.stringify(payload));
}

function writeEmpty(res, statusCode) {
  writeCorsHeaders(res);
  res.writeHead(statusCode);
  res.end();
}

async function serveFile(res, filePath) {
  try {
    const content = await readFile(filePath);
    const ext = path.extname(filePath).toLowerCase();
    res.writeHead(200, {
      "Content-Type": MIME_TYPES[ext] || "application/octet-stream",
      "Cache-Control": ext === ".html" ? "no-cache" : "public, max-age=300",
    });
    res.end(content);
  } catch {
    res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("Not found");
  }
}

function safeStaticPath(pathname) {
  const decoded = decodeURIComponent(pathname);
  const relativePath = decoded === "/" ? "index.html" : decoded.replace(/^\/+/, "");
  const absolutePath = path.resolve(staticRoot, relativePath);
  if (!absolutePath.startsWith(path.resolve(staticRoot))) {
    return null;
  }
  return absolutePath;
}

async function serveStatic(res, pathname) {
  let targetPath = safeStaticPath(pathname);
  if (!targetPath) {
    res.writeHead(403, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("Forbidden");
    return;
  }

  const hasExtension = path.extname(pathname) !== "";
  if (!hasExtension) {
    targetPath = path.join(staticRoot, "index.html");
  }

  await serveFile(res, targetPath);
}

async function handleAuthApi(req, res, pathname) {
  if (pathname === "/api/auth/guest" && req.method === "POST") {
    const body = await readJsonBody(req);
    const { session, viewer } = createGuestSession(body.displayName);
    await persistState();
    writeJson(res, 201, { sessionToken: session.token, viewer: exposeViewer(viewer) });
    return;
  }

  if (pathname === "/api/auth/register" && req.method === "POST") {
    const body = await readJsonBody(req);
    const { session, viewer } = createUserAccount(body);
    await persistState();
    writeJson(res, 201, { sessionToken: session.token, viewer: exposeViewer(viewer) });
    return;
  }

  if (pathname === "/api/auth/login" && req.method === "POST") {
    const body = await readJsonBody(req);
    const { session, viewer } = loginUserAccount(body);
    await persistState();
    writeJson(res, 200, { sessionToken: session.token, viewer: exposeViewer(viewer) });
    return;
  }

  if (pathname === "/api/auth/logout" && req.method === "POST") {
    const body = await readJsonBody(req);
    const token = String(body.sessionToken || "").trim() || readTokenFromRequest(req);
    if (token) {
      logoutSession(token);
      await persistState();
    }
    writeJson(res, 200, { ok: true });
    return;
  }

  writeJson(res, 404, { type: "error", message: "Auth route not found." });
}

async function handleApi(req, res, pathname, searchParams) {
  if (req.method === "OPTIONS") {
    writeEmpty(res, 204);
    return;
  }

  if (pathname === "/health" && req.method === "GET") {
    writeJson(res, 200, { ok: true });
    return;
  }

  if (pathname.startsWith("/api/auth/")) {
    await handleAuthApi(req, res, pathname);
    return;
  }

  const sessionToken = readTokenFromRequest(req);
  const session = findSessionByToken(sessionToken);
  touchSession(session);
  const viewer = buildViewer(session);

  if (pathname === "/api/me" && req.method === "GET") {
    writeJson(res, 200, { viewer: exposeViewerFromSession(session) });
    return;
  }

  if (pathname === "/api/me/history" && req.method === "GET") {
    if (!viewer) {
      throw createHttpError(401, "A session is required to load match history.");
    }
    const requestedLimit = Number(searchParams.get("limit") || 12);
    const limit = Number.isFinite(requestedLimit) ? Math.max(1, Math.min(50, requestedLimit)) : 12;
    const fullHistory = getMatchHistoryEntriesForUserId(viewer.userId);
    writeJson(res, 200, {
      viewer: exposeViewerFromSession(session),
      history: fullHistory.slice(0, limit),
      summary: buildHistorySummary(fullHistory),
    });
    return;
  }

  if (pathname === "/api/lobby" && req.method === "GET") {
    if (!viewer) {
      throw createHttpError(401, "A session is required to load the lobby.");
    }
    writeJson(res, 200, {
      viewer: exposeViewerFromSession(session),
      rooms: getLobbyState(viewer),
    });
    return;
  }

  if (pathname === "/api/users/search" && req.method === "GET") {
    writeJson(res, 200, {
      users: searchUsers(searchParams.get("q") || "", viewer),
    });
    return;
  }

  const userMatch = pathname.match(/^\/api\/users\/([a-z0-9_.-]{1,24})$/i);
  if (userMatch && req.method === "GET") {
    const user = findUserByLoginId(userMatch[1]);
    if (!user) {
      throw createHttpError(404, `User ${userMatch[1]} does not exist.`);
    }
    const history = getMatchHistoryEntriesForUserId(user.id);
    writeJson(res, 200, {
      user: {
        ...publicUser(user),
        presence: getPresenceForUser(user, viewer),
        stats: buildHistorySummary(history),
      },
      headToHead: buildHeadToHead(viewer, user),
    });
    return;
  }

  if (pathname === "/api/rooms" && req.method === "POST") {
    if (!viewer) {
      throw createHttpError(401, "A session is required to create a room.");
    }

    const body = await readJsonBody(req);
    const invitedUser = body.invitedLoginId ? findUserByLoginId(body.invitedLoginId) : null;
    if (body.invitedLoginId && !invitedUser) {
      throw createHttpError(404, `User ${body.invitedLoginId} does not exist.`);
    }
    if (invitedUser && invitedUser.id === viewer.userId) {
      throw createHttpError(409, "You cannot invite yourself.");
    }

    const room = createRoom(body.config, viewer, {
      invitedUserId: invitedUser?.id || null,
      publicVisible: body.publicVisible !== false,
    });
    writeJson(res, 201, {
      viewer: exposeViewerFromSession(session),
      ...snapshotFor(room, { role: "host", mode: "host" }, viewer),
    });
    return;
  }

  const roomMatch = pathname.match(/^\/api\/rooms\/([A-Z0-9]{1,6})(?:\/(join|move|rematch|leave|request|chat))?$/i);
  if (!roomMatch) {
    writeJson(res, 404, { type: "error", message: "API route not found." });
    return;
  }

  const roomId = normalizeRoomId(roomMatch[1]);
  const action = roomMatch[2] || "";

  if (action === "join" && req.method === "POST") {
    if (!viewer) {
      throw createHttpError(401, "A session is required to join a room.");
    }
    const access = joinRoom(roomId, viewer);
    writeJson(res, 200, {
      viewer: exposeViewerFromSession(session),
      ...snapshotFor(access.room, access, viewer),
    });
    return;
  }

  if (!viewer) {
    throw createHttpError(401, "A session is required for room actions.");
  }

  const { room, role, mode } = findRoomAccess(roomId, viewer);
  if (!room) {
    throw createHttpError(404, `Room ${roomId} does not exist.`);
  }
  if (!mode) {
    throw createHttpError(403, "This room session is not valid anymore.");
  }
  const access = { room, role, mode };

  if (!action && req.method === "GET") {
    writeJson(res, 200, {
      viewer: exposeViewerFromSession(session),
      ...snapshotFor(room, access, viewer),
    });
    return;
  }

  if (action === "move" && req.method === "POST") {
    if (!role) {
      throw createHttpError(403, "Spectators cannot make moves.");
    }
    const body = await readJsonBody(req);
    move(room, role, body.row, body.col);
    writeJson(res, 200, {
      viewer: exposeViewerFromSession(session),
      ...snapshotFor(room, access, viewer),
    });
    return;
  }

  if (action === "rematch" && req.method === "POST") {
    if (!role) {
      throw createHttpError(403, "Spectators cannot request rematches.");
    }
    requestRematch(room, role);
    writeJson(res, 200, {
      viewer: exposeViewerFromSession(session),
      ...snapshotFor(room, access, viewer),
    });
    return;
  }

  if (action === "request" && req.method === "POST") {
    if (!role) {
      throw createHttpError(403, "Spectators cannot use player-only room actions.");
    }
    const body = await readJsonBody(req);
    resolveRoomActionRequest(room, role, body.kind, body.operation || "request");
    writeJson(res, 200, {
      viewer: exposeViewerFromSession(session),
      ...snapshotFor(room, access, viewer),
    });
    return;
  }

  if (action === "chat" && req.method === "POST") {
    const body = await readJsonBody(req);
    sendChatMessage(room, access, viewer, body.text);
    writeJson(res, 200, {
      viewer: exposeViewerFromSession(session),
      ...snapshotFor(room, access, viewer),
    });
    return;
  }

  if (action === "leave" && req.method === "POST") {
    leaveRoom(room, access, viewer);
    writeJson(res, 200, {
      viewer: exposeViewerFromSession(session),
      ...snapshotFor(room, access, viewer),
    });
    return;
  }

  writeJson(res, 405, { type: "error", message: "Method not allowed." });
}

async function handleRequest(req, res) {
  try {
    const url = new URL(req.url || "/", `http://${req.headers.host || "127.0.0.1"}`);
    if (url.pathname.startsWith("/api/") || url.pathname === "/health") {
      await handleApi(req, res, url.pathname, url.searchParams);
      return;
    }

    await serveStatic(res, url.pathname);
  } catch (error) {
    const statusCode = error?.statusCode || 500;
    writeJson(res, statusCode, {
      type: "error",
      message: error instanceof Error ? error.message : "Internal server error.",
    });
  }
}

async function createAppServer() {
  const keyPath = process.env.HTTPS_KEY_PATH;
  const certPath = process.env.HTTPS_CERT_PATH;

  if (keyPath && certPath) {
    const [key, cert] = await Promise.all([readFile(keyPath), readFile(certPath)]);
    return {
      protocol: "https",
      server: createHttpsServer(
        {
          key,
          cert,
          passphrase: process.env.HTTPS_PASSPHRASE,
        },
        handleRequest,
      ),
    };
  }

  return {
    protocol: "http",
    server: createHttpServer(handleRequest),
  };
}

loadPersistentState()
  .then(() => createAppServer())
  .then(({ protocol, server }) => {
    server.listen(PORT, HOST, () => {
      console.log(`Anti-Gomoku web server listening on ${protocol}://${HOST}:${PORT}`);
      console.log(`Serving frontend from ${staticRoot}`);
      console.log(`Persisting account data in ${dataFile}`);
    });
  })
  .catch((error) => {
    console.error("Failed to start the Anti-Gomoku web server.");
    console.error(error);
    process.exit(1);
  });
