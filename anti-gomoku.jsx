import { useEffect, useRef, useState } from "react";
import { DEFAULT_MATCH_CONFIG, sanitizeConfig, tickClock } from "./game-core.mjs";
import { EngineGame, LocalGame, OnlineGame, ReviewGame } from "./game-ui.jsx";
import { HallPage, LoadingPage, ProfilePage } from "./hub-ui.jsx";
import {
  buildInviteLink,
  clearInviteFromBrowserUrl,
  consumeInviteAutoJoin,
  copyTextToClipboard,
  readInviteFromLocation,
  writeInviteToBrowserUrl,
} from "./online-room.mjs";
import {
  createGuestSession,
  createRoomRequest,
  fetchMatchHistory,
  fetchLobby,
  fetchRoomRequest,
  fetchUserProfile,
  fetchViewer,
  joinRoomRequest,
  leaveRoomRequest,
  loadStoredSessionToken,
  loginAccount,
  logoutAccount,
  moveRoomRequest,
  requestRoomAction,
  registerAccount,
  rematchRoomRequest,
  saveStoredSessionToken,
  searchUsers,
  sendRoomChat,
} from "./app-client.mjs";
import {
  buildRecordFromMoves,
  findArchivedRecordByGameId,
  findDeepestMainlineNode,
  loadArchivedRecords,
  upsertArchivedRecord,
  deleteArchivedRecord,
} from "./game-record.mjs";
import { applyEngineRoomMove, canPlayerMoveInEngineRoom, createEngineRoomSession } from "./engine-room.mjs";
import { RemoteEngineClient } from "./engine/engine-client.mjs";
import { EngineGameplayRunner, withEngineDebug } from "./engine/engine-gameplay-runner.mjs";

const LOBBY_POLL_MS = 4000;
const ROOM_POLL_MS = 1000;

function resolveRoomMode(payload, fallback = "join") {
  if (payload?.mode) {
    return payload.mode;
  }
  if (payload?.role === "host") {
    return "host";
  }
  if (payload?.role === "guest") {
    return "guest";
  }
  return fallback;
}

function applyRoomPayload(prev, payload, modeFallback = "join") {
  return {
    ...(prev || {}),
    mode: resolveRoomMode(payload, prev?.mode || modeFallback),
    role: payload.role ?? prev?.role ?? null,
    phase: payload.phase || prev?.phase || "connecting",
    roomId: payload.roomId || prev?.roomId || "",
    config: sanitizeConfig(payload.config || prev?.config || DEFAULT_MATCH_CONFIG),
    gameState: payload.gameState || prev?.gameState || null,
    rematch: payload.rematch || prev?.rematch || { host: false, guest: false },
    notice: payload.notice || "",
    lastError: "",
    game: payload.game || prev?.game || null,
    gameId: payload.game?.id || prev?.gameId || "",
    gameIndex: payload.game?.index || prev?.gameIndex || 0,
    roomSummary: payload.roomSummary || prev?.roomSummary || null,
    requests: payload.requests || prev?.requests || null,
    chatMessages: payload.chatMessages || prev?.chatMessages || [],
  };
}

export default function App() {
  const initialInvite = readInviteFromLocation();
  const [bootstrapping, setBootstrapping] = useState(true);
  const [screen, setScreen] = useState("hall");
  const [viewer, setViewer] = useState(null);
  const [profileUser, setProfileUser] = useState(null);
  const [sessionToken, setSessionToken] = useState(() => loadStoredSessionToken());
  const [notice, setNotice] = useState("");
  const [roomCode, setRoomCode] = useState(() => initialInvite.roomId || "");
  const [createConfig, setCreateConfig] = useState(() => sanitizeConfig(DEFAULT_MATCH_CONFIG));
  const [createPublicVisible, setCreatePublicVisible] = useState(true);
  const [challengeConfig, setChallengeConfig] = useState(() => sanitizeConfig(DEFAULT_MATCH_CONFIG));
  const [challengePublicVisible, setChallengePublicVisible] = useState(true);
  const [onlineSession, setOnlineSession] = useState(null);
  const [engineSession, setEngineSession] = useState(null);
  const [reviewSession, setReviewSession] = useState(null);
  const [localConfig, setLocalConfig] = useState(() => sanitizeConfig(DEFAULT_MATCH_CONFIG));
  const [localGameKey, setLocalGameKey] = useState(0);
  const [inviteCopied, setInviteCopied] = useState(false);
  const [archiveRecords, setArchiveRecords] = useState(() => loadArchivedRecords());
  const [matchHistory, setMatchHistory] = useState([]);
  const [matchHistorySummary, setMatchHistorySummary] = useState(null);
  const [profileStats, setProfileStats] = useState(null);
  const [profileHeadToHead, setProfileHeadToHead] = useState(null);
  const [lobbyData, setLobbyData] = useState({
    myRooms: [],
    spectatingRooms: [],
    invites: [],
    publicRooms: [],
    activeRooms: [],
  });
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [sessionMenuOpen, setSessionMenuOpen] = useState(false);
  const [authMode, setAuthMode] = useState("login");
  const [authForm, setAuthForm] = useState({
    loginId: "",
    displayName: "",
    password: "",
  });

  const roomPollTimerRef = useRef(null);
  const lobbyPollTimerRef = useRef(null);
  const roomAbortRef = useRef(null);
  const lobbyAbortRef = useRef(null);
  const searchTimerRef = useRef(null);
  const inviteCopiedTimerRef = useRef(null);
  const noticeTimerRef = useRef(null);
  const sessionTokenRef = useRef(sessionToken);
  const pendingInviteRef = useRef(initialInvite);
  const screenRef = useRef(screen);
  const onlineSessionRef = useRef(onlineSession);
  const engineSessionRef = useRef(engineSession);
  const roomPollKeyRef = useRef(0);
  const savedOnlineGameIdsRef = useRef(new Set());
  const savedEngineGameIdsRef = useRef(new Set());
  const lastRoomAlertRef = useRef("");
  const engineRunnerRef = useRef(null);

  useEffect(() => {
    sessionTokenRef.current = sessionToken;
  }, [sessionToken]);

  useEffect(() => {
    screenRef.current = screen;
  }, [screen]);

  useEffect(() => {
    onlineSessionRef.current = onlineSession;
  }, [onlineSession]);

  useEffect(() => {
    engineSessionRef.current = engineSession;
  }, [engineSession]);

  useEffect(() => () => {
    if (roomPollTimerRef.current) clearTimeout(roomPollTimerRef.current);
    if (lobbyPollTimerRef.current) clearTimeout(lobbyPollTimerRef.current);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    if (inviteCopiedTimerRef.current) clearTimeout(inviteCopiedTimerRef.current);
    if (noticeTimerRef.current) clearTimeout(noticeTimerRef.current);
    if (roomAbortRef.current) roomAbortRef.current.abort();
    if (lobbyAbortRef.current) lobbyAbortRef.current.abort();
    engineRunnerRef.current?.dispose();
  }, []);

  useEffect(() => {
    if (!engineRunnerRef.current) {
      engineRunnerRef.current = new EngineGameplayRunner({
        enableOpeningWatchdog: true,
        enableWorkerFallback: false,
        clientFactory: () => new RemoteEngineClient({
          getSessionToken: () => sessionTokenRef.current,
        }),
      });
      engineRunnerRef.current.init();
    }

    return () => {
      engineRunnerRef.current?.dispose();
      engineRunnerRef.current = null;
    };
  }, []);

  const closeMenus = () => {
    setSessionMenuOpen(false);
  };

  const setAppNotice = (message) => {
    setNotice(message);
  };

  useEffect(() => {
    if (noticeTimerRef.current) {
      clearTimeout(noticeTimerRef.current);
      noticeTimerRef.current = null;
    }

    if (!notice) {
      return undefined;
    }

    noticeTimerRef.current = setTimeout(() => {
      setNotice("");
      noticeTimerRef.current = null;
    }, 3600);

    return () => {
      if (noticeTimerRef.current) {
        clearTimeout(noticeTimerRef.current);
        noticeTimerRef.current = null;
      }
    };
  }, [notice]);

  const resetInviteCopied = () => {
    if (inviteCopiedTimerRef.current) {
      clearTimeout(inviteCopiedTimerRef.current);
      inviteCopiedTimerRef.current = null;
    }
    setInviteCopied(false);
  };

  const refreshArchiveRecords = () => {
    setArchiveRecords(loadArchivedRecords());
  };

  const refreshMatchHistoryData = async (tokenOverride = sessionTokenRef.current) => {
    const currentToken = tokenOverride;
    if (!currentToken) {
      setMatchHistory([]);
      setMatchHistorySummary(null);
      return;
    }

    try {
      const payload = await fetchMatchHistory(currentToken, 50);
      setMatchHistory(payload.history || []);
      setMatchHistorySummary(payload.summary || null);
    } catch {
      setMatchHistory([]);
      setMatchHistorySummary(null);
    }
  };

  const saveRecordArchive = (record, nextNotice = "") => {
    const saved = upsertArchivedRecord(record);
    refreshArchiveRecords();
    if (nextNotice) {
      setAppNotice(nextNotice);
    }
    return saved;
  };

  const openReviewRecord = (record, { backScreen = "profile", currentNodeId = null } = {}) => {
    setReviewSession({
      record,
      backScreen,
      currentNodeId: currentNodeId || findDeepestMainlineNode(record),
    });
    setScreen("review");
  };

  const saveAuthSession = (token, nextViewer) => {
    saveStoredSessionToken(token);
    sessionTokenRef.current = token;
    setSessionToken(token);
    setViewer(nextViewer);
  };

  const stopRoomPolling = () => {
    roomPollKeyRef.current += 1;
    if (roomPollTimerRef.current) {
      clearTimeout(roomPollTimerRef.current);
      roomPollTimerRef.current = null;
    }
    if (roomAbortRef.current) {
      roomAbortRef.current.abort();
      roomAbortRef.current = null;
    }
  };

  const stopLobbyPolling = () => {
    if (lobbyPollTimerRef.current) {
      clearTimeout(lobbyPollTimerRef.current);
      lobbyPollTimerRef.current = null;
    }
    if (lobbyAbortRef.current) {
      lobbyAbortRef.current.abort();
      lobbyAbortRef.current = null;
    }
  };

  const refreshLobby = async (tokenOverride = sessionTokenRef.current) => {
    const currentToken = tokenOverride;
    if (!currentToken) return;

    const controller = new AbortController();
    lobbyAbortRef.current = controller;
    try {
      const payload = await fetchLobby(currentToken);
      if (lobbyAbortRef.current !== controller) return;
      lobbyAbortRef.current = null;
      setViewer(payload.viewer || null);
      setLobbyData(payload.rooms || {
        myRooms: [],
        spectatingRooms: [],
        invites: [],
        publicRooms: [],
        activeRooms: [],
      });
    } catch (error) {
      if (controller.signal.aborted) return;
      lobbyAbortRef.current = null;
      setAppNotice(error instanceof Error ? error.message : "Could not refresh the hall.");
    }
  };

  const scheduleLobbyPolling = () => {
    stopLobbyPolling();
    const tick = async () => {
      if (screenRef.current === "room" || screenRef.current === "local" || screenRef.current === "engine") return;
      await refreshLobby();
      lobbyPollTimerRef.current = setTimeout(tick, LOBBY_POLL_MS);
    };
    lobbyPollTimerRef.current = setTimeout(tick, 0);
  };

  const openOwnProfile = () => {
    setProfileUser(viewer || null);
    setProfileStats(null);
    setProfileHeadToHead(null);
    setSearchQuery("");
    setSearchResults([]);
    closeMenus();
    setScreen("profile");
  };

  const openUserProfile = async (user) => {
    try {
      setProfileStats(null);
      setProfileHeadToHead(null);
      const payload = await fetchUserProfile(sessionTokenRef.current, user.loginId);
      setProfileUser(payload.user || null);
      setProfileStats(payload.user?.stats || null);
      setProfileHeadToHead(payload.headToHead || null);
      closeMenus();
      setSearchQuery("");
      setSearchResults([]);
      setScreen("profile");
    } catch (error) {
      setAppNotice(error instanceof Error ? error.message : "Could not open that profile.");
    }
  };

  const openUserProfileByLoginId = async (loginId) => {
    if (!loginId) return;
    await openUserProfile({ loginId });
  };

  useEffect(() => {
    if (screen !== "profile" || !viewer || !profileUser) {
      return;
    }
    const isSelf = (
      (viewer.loginId && profileUser.loginId && viewer.loginId === profileUser.loginId)
      || (!viewer.loginId && !profileUser.loginId && viewer.displayName === profileUser.displayName)
    );
    if (isSelf) {
      setProfileUser(viewer);
      setProfileStats(null);
      setProfileHeadToHead(null);
    }
  }, [screen, viewer, profileUser]);

  const closeRoomView = async (nextNotice = "", { sendLeave = false, navigateTo = "hall" } = {}) => {
    const current = onlineSessionRef.current;
    stopRoomPolling();
    resetInviteCopied();

    if (sendLeave && current?.roomId && sessionTokenRef.current) {
      leaveRoomRequest(sessionTokenRef.current, current.roomId, true).catch(() => {});
    }

    clearInviteFromBrowserUrl();
    setOnlineSession(null);
    setScreen(navigateTo);
    setAppNotice(nextNotice);
    await refreshLobby();
    scheduleLobbyPolling();
  };

  const updateOnlineSession = (payload) => {
    if (payload.type === "room_closed") {
      void closeRoomView(payload.message || "The room was closed.");
      return;
    }

    if (payload.type === "snapshot") {
      setOnlineSession((prev) => prev ? applyRoomPayload(prev, payload, prev.mode) : prev);
    }
  };

  const scheduleRoomPolling = (roomId) => {
    stopRoomPolling();
    const pollKey = roomPollKeyRef.current;

    const tick = async () => {
      const currentToken = sessionTokenRef.current;
      const liveSession = onlineSessionRef.current;
      if (!currentToken || !roomId || screenRef.current !== "room" || liveSession?.roomId !== roomId || pollKey !== roomPollKeyRef.current) {
        return;
      }

      const controller = new AbortController();
      roomAbortRef.current = controller;

      try {
        const payload = await fetchRoomRequest(currentToken, roomId);
        if (roomAbortRef.current !== controller || pollKey !== roomPollKeyRef.current) return;
        roomAbortRef.current = null;
        if (payload.viewer) setViewer(payload.viewer);
        if (screenRef.current !== "room" || onlineSessionRef.current?.roomId !== roomId) return;
        updateOnlineSession(payload);
      } catch (error) {
        if (controller.signal.aborted || pollKey !== roomPollKeyRef.current) return;
        roomAbortRef.current = null;
        if (screenRef.current === "room" && onlineSessionRef.current?.roomId === roomId) {
          await closeRoomView(error instanceof Error ? error.message : "Could not refresh the room.");
        }
        return;
      }

      roomPollTimerRef.current = setTimeout(tick, ROOM_POLL_MS);
    };

    roomPollTimerRef.current = setTimeout(tick, ROOM_POLL_MS);
  };

  const openRoomPayload = (payload, mode) => {
    if (payload.viewer) setViewer(payload.viewer);
    const nextSession = applyRoomPayload(null, payload, mode);

    writeInviteToBrowserUrl(nextSession.roomId);
    stopLobbyPolling();
    resetInviteCopied();
    closeMenus();
    setAppNotice("");
    setOnlineSession(nextSession);
    setScreen("room");
    scheduleRoomPolling(nextSession.roomId);
  };

  const createGuestAndBootstrap = async () => {
    const payload = await createGuestSession();
    saveAuthSession(payload.sessionToken, payload.viewer);
    return payload;
  };

  useEffect(() => {
    let ignore = false;

    const bootstrap = async () => {
      try {
        let token = loadStoredSessionToken();
        let viewerPayload = null;

        if (token) {
          try {
            viewerPayload = await fetchViewer(token);
          } catch {
            token = "";
          }
        }

        if (!token || !viewerPayload?.viewer) {
          const guestPayload = await createGuestAndBootstrap();
          if (ignore) return;
          token = guestPayload.sessionToken;
          viewerPayload = { viewer: guestPayload.viewer };
        } else if (!ignore) {
          saveAuthSession(token, viewerPayload.viewer);
        }

        if (ignore) return;
        setViewer(viewerPayload.viewer || null);
        setProfileUser(viewerPayload.viewer || null);
        setProfileStats(null);
        setProfileHeadToHead(null);
        setBootstrapping(false);
      } catch (error) {
        if (ignore) return;
        setAppNotice(error instanceof Error ? error.message : "Could not initialize the app.");
        setBootstrapping(false);
      }
    };

    void bootstrap();
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    if (bootstrapping || !sessionToken) return;
    if (screen === "room" || screen === "local" || screen === "engine") return;
    scheduleLobbyPolling();
    return () => stopLobbyPolling();
  }, [bootstrapping, sessionToken, screen]);

  useEffect(() => {
    if (bootstrapping || !sessionToken) return;
    void refreshMatchHistoryData(sessionToken);
  }, [bootstrapping, sessionToken, viewer?.userId]);

  useEffect(() => {
    if (screen !== "room") {
      stopRoomPolling();
    }
  }, [screen]);

  useEffect(() => {
    if (screen !== "engine" || !engineSession || engineSession.config.baseSeconds === null || engineSession.phase !== "active" || engineSession.gameState.result) {
      return undefined;
    }

    const id = setInterval(() => {
      setEngineSession((prev) => {
        if (!prev || prev.phase !== "active" || prev.gameState.result) {
          return prev;
        }
        const nextState = tickClock(prev.gameState, prev.config);
        if (nextState === prev.gameState) {
          return prev;
        }
        return {
          ...prev,
          gameState: nextState,
          phase: nextState.result ? "finished" : prev.phase,
          engineStatus: nextState.result ? "idle" : prev.engineStatus,
        };
      });
    }, 1000);

    return () => clearInterval(id);
  }, [screen, engineSession]);

  useEffect(() => {
    if (screen === "engine") {
      return undefined;
    }
    engineRunnerRef.current?.cancel();
    return undefined;
  }, [screen]);

  useEffect(() => {
    const game = onlineSession?.game;
    if (!game?.id || onlineSession?.phase !== "finished" || !onlineSession?.gameState?.result) {
      return;
    }
    if (savedOnlineGameIdsRef.current.has(game.id)) {
      return;
    }

    const moves = Array.isArray(game.moves) ? game.moves : [];
    if (!moves.length) {
      return;
    }

    const record = buildRecordFromMoves(onlineSession.config, moves, {
      title: `Room ${onlineSession.roomId}${onlineSession.gameIndex ? ` - Game ${onlineSession.gameIndex}` : ""}`,
      sourceKind: "online",
      sourceLabel: "Online Match",
      roomId: onlineSession.roomId,
      gameId: game.id,
      gameIndex: onlineSession.gameIndex,
      players: game.players || null,
      result: onlineSession.gameState.result,
    });

    saveRecordArchive(record);
    savedOnlineGameIdsRef.current.add(game.id);
    void refreshMatchHistoryData();
  }, [onlineSession]);

  useEffect(() => {
    const game = engineSession?.game;
    if (!game?.id || engineSession?.phase !== "finished" || !engineSession?.gameState?.result) {
      return;
    }
    if (savedEngineGameIdsRef.current.has(game.id)) {
      return;
    }
    if (!game.moves?.length) {
      return;
    }

    const record = buildRecordFromMoves(engineSession.config, game.moves, {
      title: `Local Engine Match ${engineSession.config.boardSize}x${engineSession.config.boardSize}`,
      sourceKind: "local",
      sourceLabel: "Local Engine Match",
      gameId: game.id,
      gameIndex: game.index,
      players: game.players || null,
      result: engineSession.gameState.result,
      tags: ["engine"],
    });
    saveRecordArchive(record, "Engine match saved to your archive.");
    savedEngineGameIdsRef.current.add(game.id);
  }, [engineSession]);

  useEffect(() => {
    engineRunnerRef.current?.runTurn({
      screen,
      session: engineSession,
      sessionRef: engineSessionRef,
      setSession: setEngineSession,
    });
  }, [
    screen,
    engineSession?.game?.id,
    engineSession?.phase,
    engineSession?.engineStatus,
    engineSession?.gameState?.turn,
    engineSession?.gameState?.result,
    engineSession?.game?.moves?.length,
    engineSession?.engineSide,
  ]);

  useEffect(() => {
    if (screen !== "room" || !onlineSession?.requests || !onlineSession?.role) {
      return;
    }
    const role = onlineSession.role;
    const oppositeRole = role === "host" ? "guest" : "host";
    const opponent = oppositeRole === "host" ? onlineSession.roomSummary?.host : onlineSession.roomSummary?.guest;
    const checks = [
      { kind: "draw", label: "offered a draw" },
      { kind: "takeback", label: "requested a takeback" },
      { kind: "rematch", label: "requested a rematch" },
    ];
    for (const item of checks) {
      const request = onlineSession.requests[item.kind];
      if (request?.requestedBy === oppositeRole && request[oppositeRole] && !request[role]) {
        const key = `${item.kind}:${request.updatedAt || ""}`;
        if (key && key !== lastRoomAlertRef.current) {
          lastRoomAlertRef.current = key;
          setAppNotice(`${opponent?.displayName || "Opponent"} ${item.label}.`);
        }
        return;
      }
    }
  }, [screen, onlineSession]);

  useEffect(() => {
    if (bootstrapping || !sessionToken) return;
    const invite = pendingInviteRef.current;
    if (!invite?.roomId || screen === "room") return;

    pendingInviteRef.current = { roomId: "", autoJoin: false };
    if (invite.autoJoin) {
      consumeInviteAutoJoin();
    }

    let cancelled = false;

    const recoverRoom = async () => {
      try {
        const payload = await fetchRoomRequest(sessionToken, invite.roomId);
        if (cancelled) return;
        openRoomPayload(payload, resolveRoomMode(payload, "join"));
        return;
      } catch {
        if (!invite.autoJoin) {
          return;
        }
      }

      try {
        const payload = await joinRoomRequest(sessionToken, invite.roomId);
        if (cancelled) return;
        openRoomPayload(payload, resolveRoomMode(payload, "join"));
      } catch (error) {
        if (cancelled) return;
        setAppNotice(error instanceof Error ? error.message : "Could not join the invited room.");
      }
    };

    void recoverRoom();
    return () => {
      cancelled = true;
    };
  }, [bootstrapping, sessionToken, screen]);

  useEffect(() => {
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);

    if (!searchQuery.trim() || screen !== "hall") {
      setSearchResults([]);
      setSearchLoading(false);
      return undefined;
    }

    setSearchLoading(true);
    searchTimerRef.current = setTimeout(() => {
      const currentToken = sessionTokenRef.current;
      if (!currentToken) {
        setSearchResults([]);
        setSearchLoading(false);
        return;
      }

      searchUsers(currentToken, searchQuery)
        .then((payload) => {
          setSearchResults(payload.users || []);
          setSearchLoading(false);
        })
        .catch(() => {
          setSearchResults([]);
          setSearchLoading(false);
        });
    }, 220);

    return () => {
      if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    };
  }, [searchQuery, screen]);

  const handleAuthFieldChange = (field, value) => {
    setAuthForm((prev) => ({ ...prev, [field]: value }));
  };

  const clearAuthForm = () => {
    setAuthForm({ loginId: "", displayName: "", password: "" });
  };

  const handleLogin = async () => {
    try {
      const payload = await loginAccount({
        loginId: authForm.loginId,
        password: authForm.password,
      });
      saveAuthSession(payload.sessionToken, payload.viewer);
      setProfileUser(payload.viewer);
      setProfileStats(null);
      setProfileHeadToHead(null);
      clearAuthForm();
      closeMenus();
      setAppNotice(`Signed in as @${payload.viewer.loginId}.`);
      await refreshLobby(payload.sessionToken);
      await refreshMatchHistoryData(payload.sessionToken);
    } catch (error) {
      setAppNotice(error instanceof Error ? error.message : "Login failed.");
    }
  };

  const handleRegister = async () => {
    try {
      const payload = await registerAccount({
        loginId: authForm.loginId,
        displayName: authForm.displayName,
        password: authForm.password,
      });
      saveAuthSession(payload.sessionToken, payload.viewer);
      setProfileUser(payload.viewer);
      setProfileStats(null);
      setProfileHeadToHead(null);
      clearAuthForm();
      setAuthMode("login");
      closeMenus();
      setAppNotice(`Account @${payload.viewer.loginId} created and signed in.`);
      await refreshLobby(payload.sessionToken);
      await refreshMatchHistoryData(payload.sessionToken);
    } catch (error) {
      setAppNotice(error instanceof Error ? error.message : "Registration failed.");
    }
  };

  const handleResetSession = async () => {
    closeMenus();
    try {
      const currentToken = sessionTokenRef.current;
      if (currentToken) {
        await logoutAccount(currentToken);
      }
    } catch {
      // Ignore and continue with guest bootstrap.
    }

    try {
      const guestPayload = await createGuestSession();
      saveAuthSession(guestPayload.sessionToken, guestPayload.viewer);
      setProfileUser(guestPayload.viewer);
      setProfileStats(null);
      setProfileHeadToHead(null);
      setSearchQuery("");
      setSearchResults([]);
      setScreen("hall");
      setAppNotice("You are now using a fresh anonymous guest session.");
      await refreshLobby(guestPayload.sessionToken);
      await refreshMatchHistoryData(guestPayload.sessionToken);
    } catch (error) {
      setAppNotice(error instanceof Error ? error.message : "Could not reset the session.");
    }
  };

  const handleCreatePublicRoom = async () => {
    try {
      const payload = await createRoomRequest(sessionTokenRef.current, {
        config: createConfig,
        publicVisible: createPublicVisible,
      });
      openRoomPayload(payload, "host");
    } catch (error) {
      setAppNotice(error instanceof Error ? error.message : "Could not create the room.");
    }
  };

  const handleChallengeUser = async () => {
    if (!profileUser?.loginId || (viewer?.loginId && profileUser.loginId === viewer.loginId)) {
      setAppNotice("Open another player profile to send a direct challenge.");
      return;
    }

    try {
      const payload = await createRoomRequest(sessionTokenRef.current, {
        config: challengeConfig,
        invitedLoginId: profileUser.loginId,
        publicVisible: challengePublicVisible,
      });
      openRoomPayload(payload, "host");
    } catch (error) {
      setAppNotice(error instanceof Error ? error.message : "Could not create the direct challenge.");
    }
  };

  const handleJoinByCode = async () => {
    try {
      const payload = await joinRoomRequest(sessionTokenRef.current, roomCode);
      openRoomPayload(payload, "join");
    } catch (error) {
      setAppNotice(error instanceof Error ? error.message : "Could not join that room.");
    }
  };

  const handleOpenRoom = async (room) => {
    try {
      const payload = room.isMine || room.isSpectating
        ? await fetchRoomRequest(sessionTokenRef.current, room.id)
        : await joinRoomRequest(sessionTokenRef.current, room.id);
      openRoomPayload(payload, resolveRoomMode(payload, room.isMine ? "host" : room.isSpectating ? "spectate" : "join"));
    } catch (error) {
      setAppNotice(error instanceof Error ? error.message : "Could not open the room.");
    }
  };

  const handleStartLocal = () => {
    closeMenus();
    setLocalConfig(sanitizeConfig(createConfig));
    setLocalGameKey((key) => key + 1);
    setScreen("local");
    setAppNotice("");
  };

  const handleStartEngine = () => {
    closeMenus();
    engineRunnerRef.current?.cancel();
    setEngineSession(createEngineRoomSession(createConfig, viewer));
    setScreen("engine");
    setAppNotice("");
  };

  const handleSaveLocalRecord = ({ config, moves, state }) => {
    if (!moves?.length) return;
    const record = buildRecordFromMoves(config, moves, {
      title: `Local Practice ${config.boardSize}x${config.boardSize}`,
      sourceKind: "local",
      sourceLabel: "Local Practice",
      result: state.result || null,
    });
    const saved = saveRecordArchive(record, "Local record saved to your archive.");
    openReviewRecord(saved, { backScreen: "hall" });
  };

  const buildCurrentEngineRecord = () => {
    if (!engineSession?.game?.moves?.length) {
      return null;
    }
    return buildRecordFromMoves(engineSession.config, engineSession.game.moves, {
      title: `Local Engine Match ${engineSession.config.boardSize}x${engineSession.config.boardSize}`,
      sourceKind: "local",
      sourceLabel: "Local Engine Match",
      gameId: engineSession.game.id,
      gameIndex: engineSession.game.index,
      players: engineSession.game.players || null,
      result: engineSession.gameState?.result || null,
      tags: ["engine"],
    });
  };

  const handleSaveEngineRecord = ({ openReview = false } = {}) => {
    const record = buildCurrentEngineRecord();
    if (!record) {
      setAppNotice("This engine match has no moves to save yet.");
      return null;
    }
    const saved = saveRecordArchive(record, "Engine match saved to your archive.");
    if (openReview) {
      openReviewRecord(saved, { backScreen: "engine" });
    }
    return saved;
  };

  const handleOpenCurrentOnlineRecord = () => {
    const gameId = onlineSession?.gameId || onlineSession?.game?.id;
    if (!gameId) {
      setAppNotice("This game is not ready for review yet.");
      return;
    }
    let record = findArchivedRecordByGameId(gameId);
    if (!record && onlineSession?.game?.moves?.length) {
      record = saveRecordArchive(buildRecordFromMoves(onlineSession.config, onlineSession.game.moves, {
        title: `Room ${onlineSession.roomId}${onlineSession.gameIndex ? ` - Game ${onlineSession.gameIndex}` : ""}`,
        sourceKind: "online",
        sourceLabel: "Online Match",
        roomId: onlineSession.roomId,
        gameId,
        gameIndex: onlineSession.gameIndex,
        players: onlineSession.game.players || null,
        result: onlineSession.gameState?.result || null,
      }));
    }
    if (!record) {
      setAppNotice("The record archive entry for this game is missing.");
      return;
    }
    openReviewRecord(record, { backScreen: "room" });
  };

  const handleOpenCurrentEngineRecord = () => {
    const gameId = engineSession?.game?.id;
    if (!gameId) {
      setAppNotice("This engine match is not ready for review yet.");
      return;
    }
    let record = findArchivedRecordByGameId(gameId);
    if (!record) {
      record = handleSaveEngineRecord();
    }
    if (!record) {
      return;
    }
    openReviewRecord(record, { backScreen: "engine" });
  };

  const handleOpenHistoryRecord = (entry) => {
    const record = findArchivedRecordByGameId(entry.gameId);
    if (!record) {
      setAppNotice("This match is still listed in history, but its local record archive entry has already been deleted.");
      return;
    }
    openReviewRecord(record, { backScreen: "profile" });
  };

  const handleOpenArchivedRecord = (record) => {
    openReviewRecord(record, { backScreen: "profile" });
  };

  const handleDeleteArchivedRecord = (recordId) => {
    deleteArchivedRecord(recordId);
    refreshArchiveRecords();
    if (reviewSession?.record?.id === recordId) {
      setReviewSession(null);
      setScreen("profile");
    }
    setAppNotice("Record removed from your archive.");
  };

  const handleMove = async (row, col) => {
    if (!onlineSession?.roomId) return;
    try {
      const payload = await moveRoomRequest(sessionTokenRef.current, onlineSession.roomId, row, col);
      if (payload.viewer) setViewer(payload.viewer);
      updateOnlineSession(payload);
    } catch (error) {
      setOnlineSession((prev) => prev ? { ...prev, lastError: error instanceof Error ? error.message : "Could not submit the move." } : prev);
    }
  };

  const handleEngineMove = (row, col) => {
    setEngineSession((prev) => {
      if (!prev || !canPlayerMoveInEngineRoom(prev)) {
        return prev;
      }
      try {
        return withEngineDebug(applyEngineRoomMove(prev, { row, col }, { actor: "player" }), {
          source: "player-move",
          stage: "awaiting-engine",
          searchKey: "",
          delayMs: 0,
          moveCount: prev.game.moves.length + 1,
          turn: prev.engineSide,
          scheduledAt: new Date().toISOString(),
        });
      } catch (error) {
        return {
          ...prev,
          lastError: error instanceof Error ? error.message : "Could not submit the local move.",
        };
      }
    });
  };

  const closeEngineView = (nextNotice = "") => {
    engineRunnerRef.current?.cancel();
    setEngineSession(null);
    setScreen("hall");
    setAppNotice(nextNotice);
    scheduleLobbyPolling();
  };

  const handleRematch = async () => {
    if (!onlineSession?.roomId) return;
    try {
      const payload = await rematchRoomRequest(sessionTokenRef.current, onlineSession.roomId);
      if (payload.viewer) setViewer(payload.viewer);
      updateOnlineSession(payload);
    } catch (error) {
      setOnlineSession((prev) => prev ? { ...prev, lastError: error instanceof Error ? error.message : "Could not request a rematch." } : prev);
    }
  };

  const handleRoomAction = async (kind, operation = "request") => {
    if (!onlineSession?.roomId) return;
    try {
      const payload = await requestRoomAction(sessionTokenRef.current, onlineSession.roomId, kind, operation);
      if (payload.viewer) setViewer(payload.viewer);
      updateOnlineSession(payload);
    } catch (error) {
      setOnlineSession((prev) => prev ? { ...prev, lastError: error instanceof Error ? error.message : "Could not send that room request." } : prev);
    }
  };

  const handleSendChat = async (text) => {
    if (!onlineSession?.roomId) return;
    try {
      const payload = await sendRoomChat(sessionTokenRef.current, onlineSession.roomId, text);
      if (payload.viewer) setViewer(payload.viewer);
      updateOnlineSession(payload);
    } catch (error) {
      setOnlineSession((prev) => prev ? { ...prev, lastError: error instanceof Error ? error.message : "Could not send the chat message." } : prev);
    }
  };

  const handleCopyInvite = async () => {
    if (!onlineSession?.roomId) return;
    const link = buildInviteLink("", onlineSession.roomId, { autoJoin: true });
    try {
      const copied = await copyTextToClipboard(link);
      if (!copied) throw new Error("Copy blocked");
      resetInviteCopied();
      setInviteCopied(true);
      inviteCopiedTimerRef.current = setTimeout(() => {
        setInviteCopied(false);
        inviteCopiedTimerRef.current = null;
      }, 1800);
    } catch {
      setOnlineSession((prev) => prev ? { ...prev, lastError: "Could not copy the invite link automatically." } : prev);
    }
  };

  if (bootstrapping) {
    return <LoadingPage message="Preparing your lobby session..." />;
  }

  if (screen === "local") {
    return <LocalGame key={localGameKey} config={localConfig} onMenu={() => setScreen("hall")} onSaveRecord={handleSaveLocalRecord} />;
  }

  if (screen === "engine" && engineSession) {
    return (
      <EngineGame
        session={engineSession}
        onMove={handleEngineMove}
        onBackToHall={() => { closeEngineView(""); }}
        onLeave={() => { closeEngineView(""); }}
        onSaveRecord={() => { handleSaveEngineRecord({ openReview: false }); }}
        onReview={handleOpenCurrentEngineRecord}
      />
    );
  }

  if (screen === "room" && onlineSession) {
    return <OnlineGame session={onlineSession} shareLink={buildInviteLink("", onlineSession.roomId, { autoJoin: true })} inviteCopied={inviteCopied} onCopyInvite={() => { void handleCopyInvite(); }} onMove={(row, col) => { void handleMove(row, col); }} onBackToHall={() => { void closeRoomView("", { sendLeave: false }); }} onLeave={() => { void closeRoomView("", { sendLeave: true }); }} onRematch={() => { void handleRematch(); }} onReview={handleOpenCurrentOnlineRecord} onRoomAction={(kind, operation) => { void handleRoomAction(kind, operation); }} onSendChat={(text) => { void handleSendChat(text); }} />;
  }

  if (screen === "review" && reviewSession?.record) {
    return (
      <ReviewGame
        record={reviewSession.record}
        currentNodeId={reviewSession.currentNodeId}
        onBack={() => {
          setScreen(reviewSession.backScreen || "profile");
          setReviewSession(null);
        }}
        onChangeRecord={(record, currentNodeId) => {
          setReviewSession((prev) => prev ? { ...prev, record, currentNodeId } : prev);
        }}
        onSaveRecord={(record) => {
          const saved = saveRecordArchive(record);
          setReviewSession((prev) => prev ? { ...prev, record: saved, currentNodeId: prev.currentNodeId || findDeepestMainlineNode(saved) } : prev);
          return saved;
        }}
      />
    );
  }

  if (screen === "profile") {
    return (
      <ProfilePage
        viewer={viewer}
        notice={notice}
        onDismissNotice={() => setNotice("")}
        activeTab="profile"
        onTabChange={(tab) => {
          closeMenus();
          if (tab === "hall") setScreen("hall");
          if (tab === "profile") openOwnProfile();
        }}
        profileUser={profileUser}
        challengeConfig={challengeConfig}
        challengePublicVisible={challengePublicVisible}
        onChallengeConfigChange={setChallengeConfig}
        onChallengePublicVisibleChange={setChallengePublicVisible}
        onChallenge={() => { void handleChallengeUser(); }}
        onOpenPresenceRoom={(roomId) => {
          if (!roomId) return;
          void handleOpenRoom({ id: roomId, isMine: false, isSpectating: false });
        }}
        matchHistory={matchHistory}
        matchHistorySummary={matchHistorySummary}
        profileStats={profileStats}
        headToHead={profileHeadToHead}
        archiveRecords={archiveRecords}
        onOpenHistoryRecord={handleOpenHistoryRecord}
        onOpenArchivedRecord={handleOpenArchivedRecord}
        onDeleteArchivedRecord={handleDeleteArchivedRecord}
        onOpenOpponentProfile={(loginId) => { void openUserProfileByLoginId(loginId); }}
        onOpenSelfProfile={openOwnProfile}
        sessionMenuOpen={sessionMenuOpen}
        onToggleSessionMenu={() => setSessionMenuOpen((open) => !open)}
        authMode={authMode}
        authForm={authForm}
        onAuthModeChange={setAuthMode}
        onAuthFieldChange={handleAuthFieldChange}
        onLogin={() => { void handleLogin(); }}
        onRegister={() => { void handleRegister(); }}
        onResetSession={() => { void handleResetSession(); }}
      />
    );
  }

  return (
    <HallPage
      viewer={viewer}
      notice={notice}
      onDismissNotice={() => setNotice("")}
      activeTab="hall"
      onTabChange={(tab) => {
        closeMenus();
        if (tab === "hall") setScreen("hall");
        if (tab === "profile") openOwnProfile();
      }}
      rooms={lobbyData}
      roomCode={roomCode}
      onRoomCodeChange={setRoomCode}
      onJoinByCode={() => { void handleJoinByCode(); }}
      createConfig={createConfig}
      createPublicVisible={createPublicVisible}
      onConfigChange={setCreateConfig}
      onCreatePublicVisibleChange={setCreatePublicVisible}
      onCreatePublic={() => { void handleCreatePublicRoom(); }}
      onOpenRoom={(room) => { void handleOpenRoom(room); }}
      onStartLocal={handleStartLocal}
      onStartEngine={handleStartEngine}
      searchQuery={searchQuery}
      searchResults={searchResults}
      searchLoading={searchLoading}
      onSearchChange={setSearchQuery}
      onSelectSearchResult={(user) => { void openUserProfile(user); }}
      onOpenSelfProfile={openOwnProfile}
      sessionMenuOpen={sessionMenuOpen}
      onToggleSessionMenu={() => setSessionMenuOpen((open) => !open)}
      authMode={authMode}
      authForm={authForm}
      onAuthModeChange={setAuthMode}
      onAuthFieldChange={handleAuthFieldChange}
      onLogin={() => { void handleLogin(); }}
      onRegister={() => { void handleRegister(); }}
      onResetSession={() => { void handleResetSession(); }}
    />
  );
}
