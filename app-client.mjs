import { apiRequest, defaultServerUrl, normalizeRoomId } from "./online-room.mjs";

const SESSION_TOKEN_KEY = "anti_gomoku_session_token";

function baseUrl() {
  return defaultServerUrl();
}

function withSessionToken(sessionToken, options = {}) {
  const headers = {
    ...(options.headers || {}),
  };

  if (sessionToken) {
    headers["x-session-token"] = sessionToken;
  }

  return {
    ...options,
    headers,
  };
}

export function loadStoredSessionToken() {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(SESSION_TOKEN_KEY) || "";
}

export function saveStoredSessionToken(sessionToken) {
  if (typeof window === "undefined") return;
  if (sessionToken) {
    window.localStorage.setItem(SESSION_TOKEN_KEY, sessionToken);
  } else {
    window.localStorage.removeItem(SESSION_TOKEN_KEY);
  }
}

export async function fetchViewer(sessionToken) {
  return apiRequest(baseUrl(), "/api/me", withSessionToken(sessionToken));
}

export async function createGuestSession(displayName = "") {
  return apiRequest(baseUrl(), "/api/auth/guest", {
    method: "POST",
    body: { displayName },
  });
}

export async function registerAccount(payload) {
  return apiRequest(baseUrl(), "/api/auth/register", {
    method: "POST",
    body: payload,
  });
}

export async function loginAccount(payload) {
  return apiRequest(baseUrl(), "/api/auth/login", {
    method: "POST",
    body: payload,
  });
}

export async function logoutAccount(sessionToken) {
  return apiRequest(baseUrl(), "/api/auth/logout", {
    method: "POST",
    body: { sessionToken },
  });
}

export async function fetchLobby(sessionToken) {
  return apiRequest(baseUrl(), "/api/lobby", withSessionToken(sessionToken));
}

export async function fetchMatchHistory(sessionToken, limit = 12) {
  return apiRequest(baseUrl(), `/api/me/history?limit=${encodeURIComponent(limit)}`, withSessionToken(sessionToken));
}

export async function searchUsers(sessionToken, query) {
  return apiRequest(baseUrl(), `/api/users/search?q=${encodeURIComponent(query)}`, withSessionToken(sessionToken));
}

export async function fetchUserProfile(sessionToken, loginId) {
  return apiRequest(baseUrl(), `/api/users/${encodeURIComponent(loginId)}`, withSessionToken(sessionToken));
}

export async function createRoomRequest(sessionToken, payload) {
  return apiRequest(baseUrl(), "/api/rooms", withSessionToken(sessionToken, {
    method: "POST",
    body: payload,
  }));
}

export async function joinRoomRequest(sessionToken, roomId) {
  return apiRequest(baseUrl(), `/api/rooms/${normalizeRoomId(roomId)}/join`, withSessionToken(sessionToken, {
    method: "POST",
    body: {},
  }));
}

export async function fetchRoomRequest(sessionToken, roomId) {
  return apiRequest(baseUrl(), `/api/rooms/${normalizeRoomId(roomId)}`, withSessionToken(sessionToken));
}

export async function moveRoomRequest(sessionToken, roomId, row, col) {
  return apiRequest(baseUrl(), `/api/rooms/${normalizeRoomId(roomId)}/move`, withSessionToken(sessionToken, {
    method: "POST",
    body: { row, col },
  }));
}

export async function rematchRoomRequest(sessionToken, roomId) {
  return apiRequest(baseUrl(), `/api/rooms/${normalizeRoomId(roomId)}/rematch`, withSessionToken(sessionToken, {
    method: "POST",
    body: {},
  }));
}

export async function requestRoomAction(sessionToken, roomId, kind, operation = "request") {
  return apiRequest(baseUrl(), `/api/rooms/${normalizeRoomId(roomId)}/request`, withSessionToken(sessionToken, {
    method: "POST",
    body: { kind, operation },
  }));
}

export async function sendRoomChat(sessionToken, roomId, text) {
  return apiRequest(baseUrl(), `/api/rooms/${normalizeRoomId(roomId)}/chat`, withSessionToken(sessionToken, {
    method: "POST",
    body: { text },
  }));
}

export async function leaveRoomRequest(sessionToken, roomId, keepalive = false) {
  return apiRequest(baseUrl(), `/api/rooms/${normalizeRoomId(roomId)}/leave`, withSessionToken(sessionToken, {
    method: "POST",
    body: {},
    keepalive,
  }));
}

export async function fetchEngineInfo() {
  return apiRequest(baseUrl(), "/api/engine/info");
}

export async function analyzePositionWithEngine(payload, { signal } = {}) {
  return apiRequest(baseUrl(), "/api/engine/analyze", {
    method: "POST",
    body: payload,
    signal,
  });
}

export async function clearEngineCache() {
  return apiRequest(baseUrl(), "/api/engine/cache", {
    method: "POST",
    body: {},
  });
}
