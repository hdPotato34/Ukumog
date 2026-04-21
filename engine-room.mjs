import { applyMove, createMatchState, opp, sanitizeConfig } from "./game-core.mjs";
import { moveToNotation } from "./game-record.mjs";

function generateId(prefix = "engine") {
  if (globalThis.crypto?.randomUUID) {
    return `${prefix}-${globalThis.crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function buildViewerParticipant(viewer, side) {
  return {
    side,
    displayName: viewer?.displayName || viewer?.loginId || "You",
    loginId: viewer?.loginId || "",
    authenticated: !!viewer?.authenticated,
    rating: viewer?.rating ?? null,
  };
}

function buildEngineParticipant(side, name = "Engine") {
  return {
    side,
    displayName: name,
    loginId: "local-engine",
    authenticated: false,
    rating: null,
  };
}

function resolveSides(config) {
  const cleanConfig = sanitizeConfig(config);
  let playerSide = "B";

  if (cleanConfig.colorMode === "white") {
    playerSide = "W";
  } else if (cleanConfig.colorMode === "random") {
    playerSide = Math.random() < 0.5 ? "B" : "W";
  }

  return {
    config: cleanConfig,
    playerSide,
    engineSide: opp(playerSide),
  };
}

function appendMove(session, move, actor) {
  return {
    row: move.row,
    col: move.col,
    player: session.gameState.turn,
    ply: session.game.moves.length + 1,
    notation: moveToNotation(move.row, move.col),
    playedAt: new Date().toISOString(),
    actor,
  };
}

export function createEngineRoomSession(config, viewer, options = {}) {
  const sides = resolveSides(config);
  const state = createMatchState(sides.config);
  const gameId = generateId("engine-game");
  const player = buildViewerParticipant(viewer, sides.playerSide);
  const engine = buildEngineParticipant(sides.engineSide, options.engineName || "Engine");

  return {
    mode: "engine",
    phase: "active",
    roomId: "LOCAL-AI",
    config: sides.config,
    gameState: state,
    playerSide: sides.playerSide,
    engineSide: sides.engineSide,
    engineStatus: "idle",
    notice: `Local engine room ready. You play ${sides.playerSide === "B" ? "Black" : "White"}.`,
    lastError: "",
    analysis: null,
    engineDebug: {
      source: "init",
      stage: "idle",
      searchKey: "",
      delayMs: 0,
      moveCount: 0,
      turn: state.turn,
      scheduledAt: new Date().toISOString(),
      appliedAt: "",
      transportReady: false,
      workerReady: false,
    },
    game: {
      id: gameId,
      index: 1,
      moves: [],
      seats: {
        B: sides.playerSide === "B" ? "host" : "guest",
        W: sides.playerSide === "W" ? "host" : "guest",
      },
      players: {
        host: player,
        guest: engine,
        B: sides.playerSide === "B" ? player : engine,
        W: sides.playerSide === "W" ? player : engine,
      },
      config: sides.config,
      createdAt: new Date().toISOString(),
    },
  };
}

export function canPlayerMoveInEngineRoom(session) {
  return !!session && session.phase === "active" && !session.gameState.result && session.engineStatus !== "thinking" && session.gameState.turn === session.playerSide;
}

export function markEngineThinking(session) {
  return {
    ...session,
    engineStatus: "thinking",
    lastError: "",
    notice: "Engine is thinking...",
  };
}

export function setEngineRoomError(session, message) {
  return {
    ...session,
    engineStatus: "error",
    lastError: message,
    notice: "The local engine hit an error.",
  };
}

export function clearEngineRoomError(session) {
  return {
    ...session,
    engineStatus: "idle",
    lastError: "",
  };
}

export function applyEngineRoomMove(session, move, {
  actor = "player",
  analysis = null,
} = {}) {
  const nextState = applyMove(session.gameState, session.config, move.row, move.col);
  if (!nextState) {
    throw new Error("That move is not legal in the current engine room position.");
  }

  const nextMoves = [...session.game.moves, appendMove(session, move, actor)];
  return {
    ...session,
    phase: nextState.result ? "finished" : "active",
    gameState: nextState,
    engineStatus: actor === "engine" && !nextState.result ? "idle" : session.engineStatus === "thinking" ? "idle" : session.engineStatus,
    notice: nextState.result
      ? `${actor === "engine" ? "Engine" : "You"} completed the final move.`
      : actor === "engine"
        ? "Engine move applied."
        : "Move applied.",
    lastError: "",
    analysis: analysis ? { ...analysis } : session.analysis,
    game: {
      ...session.game,
      moves: nextMoves,
    },
  };
}
