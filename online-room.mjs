import { createMatchState, sanitizeConfig } from "./game-core.mjs";

export const DEFAULT_MATCH_CONFIG = { boardSize: 11, timerVal: null };
export const POLL_INTERVAL_MS = 1000;

export function defaultServerUrl() {
  if (typeof window === "undefined") return "http://127.0.0.1:8787";
  if (window.location.protocol === "file:") return "http://127.0.0.1:8787";
  return window.location.origin;
}

export function normalizeServerUrl(input) {
  const raw = String(input || "").trim();
  if (!raw) return "";
  try {
    const parsed = /^https?:\/\//i.test(raw) ? new URL(raw) : new URL(`http://${raw}`);
    return `${parsed.protocol}//${parsed.host}`;
  } catch {
    return "";
  }
}

export function normalizeRoomId(input) {
  return String(input || "").trim().toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 6);
}

export function readInviteFromLocation() {
  if (typeof window === "undefined") return { roomId: "", autoJoin: false };
  const params = new URLSearchParams(window.location.search);
  return {
    roomId: normalizeRoomId(params.get("room") || ""),
    autoJoin: params.get("autojoin") === "1",
  };
}

function canEditBrowserUrl() {
  return typeof window !== "undefined" && window.location.protocol !== "file:" && typeof window.history?.replaceState === "function";
}

export function writeInviteToBrowserUrl(roomId, { autoJoin = false } = {}) {
  if (!canEditBrowserUrl() || !roomId) return;
  const url = new URL(window.location.href);
  url.searchParams.set("room", normalizeRoomId(roomId));
  if (autoJoin) url.searchParams.set("autojoin", "1");
  else url.searchParams.delete("autojoin");
  window.history.replaceState(null, "", url.toString());
}

export function clearInviteFromBrowserUrl() {
  if (!canEditBrowserUrl()) return;
  const url = new URL(window.location.href);
  url.searchParams.delete("room");
  url.searchParams.delete("autojoin");
  window.history.replaceState(null, "", url.toString());
}

export function consumeInviteAutoJoin() {
  if (!canEditBrowserUrl()) return;
  const url = new URL(window.location.href);
  if (url.searchParams.get("autojoin") !== "1") return;
  url.searchParams.delete("autojoin");
  window.history.replaceState(null, "", url.toString());
}

export function buildInviteLink(serverUrl, roomId, { autoJoin = true } = {}) {
  const cleanRoomId = normalizeRoomId(roomId);
  const baseUrl = normalizeServerUrl(serverUrl || defaultServerUrl());
  if (!cleanRoomId || !baseUrl) return "";
  try {
    const url = new URL(baseUrl);
    url.pathname = "/";
    url.searchParams.set("room", cleanRoomId);
    if (autoJoin) url.searchParams.set("autojoin", "1");
    return url.toString();
  } catch {
    return "";
  }
}

export function createPendingOnlineSession(mode, serverUrl, roomId, config) {
  const cleanConfig = sanitizeConfig(config || DEFAULT_MATCH_CONFIG);
  const cleanRoomId = normalizeRoomId(roomId);
  return {
    mode,
    role: mode === "host" ? "host" : null,
    phase: "connecting",
    roomId: mode === "join" ? cleanRoomId : "",
    config: cleanConfig,
    gameState: createMatchState(cleanConfig),
    rematch: { host: false, guest: false },
    notice: mode === "host" ? "Creating room on server..." : "Joining server room...",
    lastError: "",
    playerId: "",
    serverUrl,
  };
}

export async function apiRequest(baseUrl, route, { method = "GET", body, signal, keepalive = false, headers } = {}) {
  const response = await fetch(`${baseUrl}${route}`, {
    method,
    headers: {
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...(headers || {}),
    },
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
    signal,
    keepalive,
  });

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    throw new Error(payload?.message || "Server request failed.");
  }

  return payload;
}

export function applySnapshot(prev, payload, extras = {}) {
  const baseConfig = payload.config || prev?.config || DEFAULT_MATCH_CONFIG;
  return {
    ...(prev || {}),
    ...extras,
    role: payload.role ?? prev?.role ?? null,
    phase: payload.phase || prev?.phase || "connecting",
    roomId: payload.roomId || prev?.roomId || "",
    config: sanitizeConfig(baseConfig),
    gameState: payload.gameState || prev?.gameState || createMatchState(baseConfig),
    rematch: payload.rematch || prev?.rematch || { host: false, guest: false },
    notice: payload.notice || "",
    lastError: "",
    playerId: payload.playerId || prev?.playerId || "",
    serverUrl: extras.serverUrl || prev?.serverUrl || "",
    mode: extras.mode || prev?.mode || "join",
  };
}

export async function copyTextToClipboard(text) {
  if (!text) return false;

  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return true;
  }

  if (typeof document === "undefined") {
    return false;
  }

  const element = document.createElement("textarea");
  element.value = text;
  element.setAttribute("readonly", "readonly");
  element.style.position = "fixed";
  element.style.opacity = "0";
  element.style.pointerEvents = "none";
  document.body.appendChild(element);
  element.focus();
  element.select();

  let copied = false;
  try {
    copied = document.execCommand("copy");
  } finally {
    document.body.removeChild(element);
  }

  return copied;
}
