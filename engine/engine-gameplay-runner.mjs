import { applyEngineRoomMove, markEngineThinking, setEngineRoomError } from "../engine-room.mjs";
import { LocalEngineClient } from "./engine-client.mjs";
import { searchMove as searchMoveSync } from "./engine-search.mjs";
import { getOpeningBookMove } from "./opening-book.mjs";

export const GAMEPLAY_ENGINE_PACK = {
  search: {
    defaultMoveTimeMs: 60,
    maxDepth: 4,
    candidateLimit: 4,
    preferredRadius: 1,
    fallbackRadius: 2,
    minCandidateCount: 3,
  },
};

export const GAMEPLAY_UNTIMED_SEARCH_BUDGET_MS = 45;
export const GAMEPLAY_TIMED_SEARCH_BUDGET_MS = 60;
export const GAMEPLAY_SEARCH_MAX_DEPTH = 4;

export const GAMEPLAY_FALLBACK_ENGINE_PACK = {
  search: {
    defaultMoveTimeMs: 20,
    maxDepth: 1,
    candidateLimit: 3,
    preferredRadius: 1,
    fallbackRadius: 1,
    minCandidateCount: 2,
  },
};

export const GAMEPLAY_FALLBACK_BUDGET_MS = 20;
export const OPENING_CACHE_DELAY_PLIES = 4;
export const OPENING_FIRST_MOVE_DELAY_MIN_MS = 600;
export const OPENING_FIRST_MOVE_DELAY_MAX_MS = 1200;
export const OPENING_REPLY_DELAY_MIN_MS = 300;
export const OPENING_REPLY_DELAY_MAX_MS = 800;

function nowIso() {
  return new Date().toISOString();
}

function randomDelayInRange(minMs, maxMs) {
  return minMs + Math.floor(Math.random() * (maxMs - minMs + 1));
}

function randomOpeningDelayMs(plyCount) {
  if (plyCount >= OPENING_CACHE_DELAY_PLIES) {
    return 0;
  }
  if (plyCount === 0) {
    return randomDelayInRange(OPENING_FIRST_MOVE_DELAY_MIN_MS, OPENING_FIRST_MOVE_DELAY_MAX_MS);
  }
  return randomDelayInRange(OPENING_REPLY_DELAY_MIN_MS, OPENING_REPLY_DELAY_MAX_MS);
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

function buildAppliedAnalysis(move, timeMs) {
  return {
    bestMove: move,
    score: 0,
    mate: null,
    pv: [move],
    depth: 0,
    nodes: 1,
    timeMs,
  };
}

export class EngineGameplayRunner {
  constructor({
    enableOpeningWatchdog = false,
    enableWorkerFallback = true,
    clientFactory = null,
  } = {}) {
    this.enableOpeningWatchdog = enableOpeningWatchdog;
    this.enableWorkerFallback = enableWorkerFallback;
    this.clientFactory = clientFactory || (() => new LocalEngineClient());
    this.client = null;
    this.searchKey = "";
    this.timerId = null;
    this.watchdogId = null;
  }

  init() {
    if (!this.client) {
      this.client = this.clientFactory();
      void this.client.init({ enginePack: GAMEPLAY_ENGINE_PACK }).catch(() => {});
    }
  }

  clearTimers() {
    if (this.timerId) {
      clearTimeout(this.timerId);
      this.timerId = null;
    }
    if (this.watchdogId) {
      clearTimeout(this.watchdogId);
      this.watchdogId = null;
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

    if ((session.game.moves?.length || 0) === 0) {
      const middle = Math.floor((session.config.boardSize - 1) / 2);
      const delayMs = randomOpeningDelayMs(session.game.moves.length);
      this.scheduleOpeningCenter({
        middle,
        delayMs,
        sessionGameId,
        searchKey,
        sessionRef,
        setSession,
      });
      return;
    }

    const openingMove = getOpeningBookMove(session.gameState, session.config);
    if (openingMove) {
      const delayMs = randomOpeningDelayMs(session.game.moves.length);
      this.scheduleOpeningBook({
        openingMove,
        delayMs,
        sessionGameId,
        searchKey,
        sessionRef,
        setSession,
      });
      return;
    }

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

  applyAnnotatedMove(setSession, liveSession, move, {
    searchKey,
    source,
    stage = "applied",
    reason = "",
    timeMs = 0,
    debugPatch = {},
  }) {
    setSession(withEngineDebug(applyEngineRoomMove(liveSession, move, {
      actor: "engine",
      analysis: buildAppliedAnalysis(move, timeMs),
    }), {
      searchKey,
      source,
      stage,
      reason,
      appliedAt: nowIso(),
      ...debugPatch,
    }));
  }

  scheduleTurn({
    session,
    sessionGameId,
    searchKey,
    source,
    delayMs = 10,
    setSession,
    execute,
    watchdog,
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

    if (watchdog) {
      const watchdogDelayMs = Math.max(50, delayMs + 250);
      const watchdogId = setTimeout(() => {
        if (this.watchdogId === watchdogId) {
          this.watchdogId = null;
        }
        watchdog();
      }, watchdogDelayMs);
      this.watchdogId = watchdogId;
    }
  }

  applySyncFallbackMove({
    session,
    sessionGameId,
    searchKey,
    reason,
    sessionRef,
    setSession,
  }) {
    try {
      const analysis = searchMoveSync({
        state: session.gameState,
        config: session.config,
        enginePack: GAMEPLAY_FALLBACK_ENGINE_PACK,
        timeBudgetMs: GAMEPLAY_FALLBACK_BUDGET_MS,
        maxDepth: 1,
      });
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
        setSession(withEngineDebug(setEngineRoomError(liveSession, "Fallback search did not return a move."), {
          searchKey,
          source: "sync-fallback",
          stage: "error",
          reason,
          appliedAt: nowIso(),
        }));
        return;
      }

      setSession(withEngineDebug(applyEngineRoomMove(liveSession, analysis.bestMove, {
        actor: "engine",
        analysis,
      }), {
        searchKey,
        source: "sync-fallback",
        stage: "applied",
        reason,
        appliedAt: nowIso(),
      }));
    } catch (error) {
      setSession((prev) => (
        prev?.game?.id === sessionGameId && this.searchKey === searchKey
          ? (() => {
            this.searchKey = "";
            return withEngineDebug(setEngineRoomError(prev, error instanceof Error ? error.message : "Fallback search failed."), {
              searchKey,
              source: "sync-fallback",
              stage: "error",
              reason,
              appliedAt: nowIso(),
            });
          })()
          : prev
      ));
    }
  }

  scheduleOpeningCenter({
    middle,
    delayMs,
    sessionGameId,
    searchKey,
    sessionRef,
    setSession,
  }) {
    this.scheduleTurn({
      sessionGameId,
      searchKey,
      source: "opening-center",
      delayMs,
      setSession,
      execute: () => {
        try {
          const liveSession = sessionRef.current;
          if (this.searchKey !== searchKey) {
            this.markStale(setSession, liveSession, {
              sessionGameId,
              searchKey,
              source: "opening-center",
              reason: "search-key-changed",
            });
            return;
          }
          if (
            !liveSession
            || liveSession.game.id !== sessionGameId
            || liveSession.game.moves.length !== 0
            || liveSession.gameState.turn !== liveSession.engineSide
          ) {
            this.markStale(setSession, liveSession, {
              sessionGameId,
              searchKey,
              source: "opening-center",
              reason: "position-changed-before-apply",
            });
            return;
          }

          this.searchKey = "";
          this.applyAnnotatedMove(setSession, liveSession, { row: middle, col: middle }, {
            searchKey,
            source: "opening-center",
            timeMs: delayMs,
          });
        } catch (error) {
          this.searchKey = "";
          this.markError(setSession, sessionRef.current, {
            searchKey,
            source: "opening-center",
            message: error instanceof Error ? error.message : "Opening center move failed.",
            reason: "opening-center-failed",
          });
        }
      },
      watchdog: this.enableOpeningWatchdog
        ? () => {
          setSession((prev) => {
            if (!prev || prev.phase !== "active" || prev.engineStatus !== "thinking") {
              return prev;
            }
            const currentDebug = prev.engineDebug || {};
            if (currentDebug.source !== "opening-center" || !["scheduled", "triggered"].includes(currentDebug.stage)) {
              return prev;
            }
            if (prev.game.moves.length !== 0 || prev.gameState.turn !== prev.engineSide) {
              return withEngineDebug(prev, {
                ...currentDebug,
                stage: "watchdog-stale",
                reason: "scheduled-timeout-no-apply",
                appliedAt: nowIso(),
              });
            }

            this.searchKey = "";
            return withEngineDebug(applyEngineRoomMove(prev, { row: middle, col: middle }, {
              actor: "engine",
              analysis: buildAppliedAnalysis({ row: middle, col: middle }, delayMs),
            }), {
              ...currentDebug,
              searchKey,
              source: "opening-center",
              stage: "watchdog-applied",
              reason: "scheduled-timeout",
              appliedAt: nowIso(),
            });
          });
        }
        : null,
    });
  }

  scheduleOpeningBook({
    openingMove,
    delayMs,
    sessionGameId,
    searchKey,
    sessionRef,
    setSession,
  }) {
    this.scheduleTurn({
      sessionGameId,
      searchKey,
      source: "opening-book",
      delayMs,
      setSession,
      execute: () => {
        const liveSession = sessionRef.current;
        if (this.searchKey !== searchKey) {
          this.markStale(setSession, liveSession, {
            sessionGameId,
            searchKey,
            source: "opening-book",
            reason: "search-key-changed",
          });
          return;
        }
        if (
          !liveSession
          || liveSession.game.id !== sessionGameId
          || liveSession.phase !== "active"
          || liveSession.gameState.turn !== liveSession.engineSide
        ) {
          this.markStale(setSession, liveSession, {
            sessionGameId,
            searchKey,
            source: "opening-book",
            reason: "position-changed-before-apply",
          });
          return;
        }

        this.searchKey = "";
        try {
          this.applyAnnotatedMove(setSession, liveSession, openingMove, {
            searchKey,
            source: "opening-book",
            timeMs: delayMs,
          });
        } catch (error) {
          this.markError(setSession, liveSession, {
            searchKey,
            source: "opening-book",
            message: error instanceof Error ? error.message : "The opening cache returned an illegal move.",
            reason: "opening-book-failed",
          });
        }
      },
      watchdog: this.enableOpeningWatchdog
        ? () => {
          setSession((prev) => {
            if (!prev || prev.phase !== "active" || prev.engineStatus !== "thinking") {
              return prev;
            }
            const currentDebug = prev.engineDebug || {};
            if (currentDebug.source !== "opening-book" || !["scheduled", "triggered"].includes(currentDebug.stage)) {
              return prev;
            }

            const fallbackMove = getOpeningBookMove(prev.gameState, prev.config);
            if (!fallbackMove || prev.gameState.turn !== prev.engineSide) {
              return withEngineDebug(prev, {
                ...currentDebug,
                stage: "watchdog-stale",
                reason: "scheduled-timeout-no-apply",
                appliedAt: nowIso(),
              });
            }

            this.searchKey = "";
            return withEngineDebug(applyEngineRoomMove(prev, fallbackMove, {
              actor: "engine",
              analysis: buildAppliedAnalysis(fallbackMove, delayMs),
            }), {
              ...currentDebug,
              searchKey,
              source: "opening-book",
              stage: "watchdog-applied",
              reason: "scheduled-timeout",
              appliedAt: nowIso(),
            });
          });
        }
        : null,
    });
  }

  scheduleSearch({
    session,
    sessionGameId,
    searchKey,
    sessionRef,
    setSession,
  }) {
    const searchSource = this.client?.sourceName || "engine-search";
    const waitingStage = searchSource === "remote-search" ? "waiting-server" : "waiting-worker";
    const handleSearchFailure = (reason) => {
      if (!this.enableWorkerFallback) {
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
            message: typeof reason === "string" && reason ? reason : "Engine search failed.",
            reason: typeof reason === "string" && reason ? reason : "engine-search-failed",
          });
        }
        return;
      }

      setSession((prev) => (
        prev?.game?.id === sessionGameId
          ? withEngineDebug(prev, {
            searchKey,
            source: searchSource,
            stage: "fallback",
            transportReady: false,
            workerReady: false,
            reason: typeof reason === "string" && reason ? reason : "engine-search-failed",
          })
          : prev
      ));
      this.applySyncFallbackMove({
        session,
        sessionGameId,
        searchKey,
        reason: typeof reason === "string" && reason ? reason : "engine-search-failed",
        sessionRef,
        setSession,
      });
    };

    this.scheduleTurn({
      session,
      sessionGameId,
      searchKey,
      source: searchSource,
      delayMs: 10,
      setSession,
      execute: () => {
        this.init();
        const engineClient = this.client;
        if (!engineClient) {
          handleSearchFailure("engine-unavailable");
          return;
        }

        setSession((prev) => (
          prev?.game?.id === sessionGameId
            ? withEngineDebug(prev, {
              searchKey,
              source: searchSource,
              stage: waitingStage,
              transportReady: true,
              workerReady: true,
            })
            : prev
        ));

        void engineClient.searchMove({
          state: session.gameState,
          config: session.config,
          enginePack: GAMEPLAY_ENGINE_PACK,
          timeBudgetMs: session.config.baseSeconds === null ? GAMEPLAY_UNTIMED_SEARCH_BUDGET_MS : GAMEPLAY_TIMED_SEARCH_BUDGET_MS,
          maxDepth: GAMEPLAY_SEARCH_MAX_DEPTH,
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
          handleSearchFailure(error instanceof Error ? error.message : "engine-search-failed");
        });
      },
    });
  }
}
