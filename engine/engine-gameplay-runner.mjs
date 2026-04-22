import { applyEngineRoomMove, markEngineThinking, setEngineRoomError } from "../engine-room.mjs";
import { resolveGameplayRequestSettings } from "./engine-settings.mjs";
import { RemoteEngineClient } from "./engine-client.mjs";

function nowIso() {
  return new Date().toISOString();
}

export function withEngineDebug(session, patch = {}) {
  return {
    ...session,
    engineDebug: {
      ...(session?.engineDebug || {}),
      ...patch,
    },
  };
}

function buildScheduledDebug({ searchKey, source, delayMs, moveCount, turn }) {
  return {
    searchKey,
    source,
    stage: "scheduled",
    delayMs,
    moveCount,
    turn,
    scheduledAt: nowIso(),
    appliedAt: "",
  };
}

export class EngineGameplayRunner {
  constructor({
    enableOpeningWatchdog = false,
    enableWorkerFallback = false,
    clientFactory = null,
  } = {}) {
    this.enableOpeningWatchdog = enableOpeningWatchdog;
    this.enableWorkerFallback = enableWorkerFallback;
    this.clientFactory = clientFactory || (() => new RemoteEngineClient());
    this.client = null;
    this.searchKey = "";
    this.timerId = null;
  }

  init() {
    if (!this.client) {
      this.client = this.clientFactory();
      void this.client.init().catch(() => {});
    }
  }

  clearTimers() {
    if (this.timerId) {
      clearTimeout(this.timerId);
      this.timerId = null;
    }
  }

  cancel() {
    this.clearTimers();
    if (this.client) {
      void this.client.cancel().catch(() => {});
    }
    this.searchKey = "";
  }

  dispose() {
    this.clearTimers();
    this.searchKey = "";
    if (this.client) {
      this.client.dispose();
      this.client = null;
    }
  }

  runTurn({ screen, session, sessionRef, setSession }) {
    if (screen !== "engine" || !session || session.phase !== "active" || session.engineStatus !== "idle") {
      return;
    }
    if (session.gameState.result || session.gameState.turn !== session.engineSide) {
      return;
    }

    const sessionGameId = session.game.id;
    const searchKey = `${sessionGameId}:${session.game.moves.length}:${session.gameState.turn}`;
    if (this.searchKey === searchKey) {
      return;
    }
    this.searchKey = searchKey;

    this.scheduleSearch({
      session,
      sessionGameId,
      searchKey,
      sessionRef,
      setSession,
    });
  }

  updateDebug(setSession, sessionGameId, patch) {
    setSession((prev) => (
      prev?.game?.id === sessionGameId
        ? withEngineDebug(prev, patch)
        : prev
    ));
  }

  markStale(setSession, liveSession, {
    sessionGameId,
    searchKey,
    source,
    reason,
  }) {
    if (liveSession?.game?.id !== sessionGameId) {
      return;
    }
    setSession(withEngineDebug(liveSession, {
      searchKey,
      source,
      stage: "stale",
      reason,
      appliedAt: nowIso(),
    }));
  }

  markError(setSession, liveSession, {
    searchKey,
    source,
    message,
    reason = "",
  }) {
    if (!liveSession) {
      return;
    }
    setSession(withEngineDebug(setEngineRoomError(liveSession, message), {
      searchKey,
      source,
      stage: "error",
      reason,
      appliedAt: nowIso(),
    }));
  }

  scheduleTurn({
    sessionGameId,
    searchKey,
    source,
    delayMs = 10,
    setSession,
    execute,
  }) {
    this.clearTimers();

    setSession((prev) => {
      if (!prev || prev.game.id !== sessionGameId) {
        return prev;
      }
      return withEngineDebug(markEngineThinking(prev), buildScheduledDebug({
        searchKey,
        source,
        delayMs,
        moveCount: prev.game.moves.length,
        turn: prev.gameState.turn,
      }));
    });

    const timerId = setTimeout(() => {
      if (this.timerId === timerId) {
        this.timerId = null;
      }
      this.updateDebug(setSession, sessionGameId, {
        searchKey,
        source,
        stage: "triggered",
        delayMs,
        appliedAt: nowIso(),
      });
      execute();
    }, delayMs);
    this.timerId = timerId;
  }

  scheduleSearch({
    session,
    sessionGameId,
    searchKey,
    sessionRef,
    setSession,
  }) {
    const searchSource = this.client?.sourceName || "remote-search";

    this.scheduleTurn({
      sessionGameId,
      searchKey,
      source: searchSource,
      delayMs: 10,
      setSession,
      execute: () => {
        this.init();
        const engineClient = this.client;
        if (!engineClient) {
          this.searchKey = "";
          this.markError(setSession, sessionRef.current, {
            searchKey,
            source: searchSource,
            message: "The engine service is currently unavailable.",
            reason: "engine-unavailable",
          });
          return;
        }

        setSession((prev) => (
          prev?.game?.id === sessionGameId
            ? withEngineDebug(prev, {
              searchKey,
              source: searchSource,
              stage: "waiting-server",
              transportReady: true,
              workerReady: false,
            })
            : prev
        ));

        void engineClient.searchMove({
          state: session.gameState,
          config: session.config,
          ...resolveGameplayRequestSettings(session.config, session.engineSettings),
        }).then((analysis) => {
          const liveSession = sessionRef.current;
          if (
            this.searchKey !== searchKey
            || !liveSession
            || liveSession.game.id !== sessionGameId
            || liveSession.phase !== "active"
            || liveSession.gameState.turn !== liveSession.engineSide
          ) {
            return;
          }

          this.searchKey = "";
          if (!analysis?.bestMove) {
            setSession(withEngineDebug(setEngineRoomError(liveSession, "The engine service did not return a move."), {
              searchKey,
              source: searchSource,
              stage: "error",
              appliedAt: nowIso(),
            }));
            return;
          }

          try {
            setSession(withEngineDebug(applyEngineRoomMove(liveSession, analysis.bestMove, {
              actor: "engine",
              analysis,
            }), {
              searchKey,
              source: searchSource,
              stage: "applied",
              appliedAt: nowIso(),
            }));
          } catch (error) {
            setSession(withEngineDebug(setEngineRoomError(liveSession, error instanceof Error ? error.message : "The engine returned an illegal move."), {
              searchKey,
              source: searchSource,
              stage: "error",
              appliedAt: nowIso(),
            }));
          }
        }).catch((error) => {
          const liveSession = sessionRef.current;
          if (
            liveSession
            && liveSession.game.id === sessionGameId
            && this.searchKey === searchKey
          ) {
            this.searchKey = "";
            this.markError(setSession, liveSession, {
              searchKey,
              source: searchSource,
              message: error instanceof Error && error.message ? error.message : "Engine search failed.",
              reason: "engine-search-failed",
            });
          }
        });
      },
    });
  }
}
