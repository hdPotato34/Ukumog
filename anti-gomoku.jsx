import { useEffect, useRef, useState } from "react";
import {
  CELL,
  GOLD,
  MARGIN,
  PR,
  SIZE_OPTIONS,
  TIMER_OPTIONS,
  applyMove,
  createMatchState,
  formatTime,
  pName,
  sanitizeConfig,
  starPoints,
  tickClock,
} from "./game-core.mjs";

const BASE_CSS = `@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;600;700&family=DM+Sans:wght@300;400;500&display=swap');*{box-sizing:border-box}button,input{transition:all .15s ease}@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}.tb-btn:hover:not(:disabled){color:#c8b060!important;border-color:#6a5030!important}.ng-btn:hover:not(:disabled),.start-btn:hover:not(:disabled){filter:brightness(1.08);transform:translateY(-1px)}.menu-btn:hover{color:#a89060!important;border-color:#4a3820!important}.chip-btn:hover{opacity:.85}.mode-tab:hover{border-color:#6a5030!important;color:#d9c08a!important}.panel-input:focus{outline:none;border-color:#8d713e!important;box-shadow:0 0 0 2px rgba(232,201,106,.08)}`;

const shellStyle = {
  minHeight: "100vh",
  background: "#0d1117",
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  justifyContent: "center",
  fontFamily: "'Cormorant Garamond', Georgia, serif",
  color: "#e8dcc8",
  padding: 16,
};

function cloneState(state) {
  return {
    board: state.board.map((row) => [...row]),
    turn: state.turn,
    times: { ...state.times },
    result: state.result ? { ...state.result, highlight: state.result.highlight.map(([r, c]) => [r, c]) } : null,
    last: state.last ? [...state.last] : null,
  };
}

function defaultServerUrl() {
  if (typeof window === "undefined") return "ws://127.0.0.1:8787";
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.hostname || "127.0.0.1";
  return `${protocol}://${host}:8787`;
}

function hasPort(raw) {
  if (raw.startsWith("[")) return raw.includes("]:");
  return (raw.match(/:/g) || []).length === 1;
}

function normalizeServerUrl(input) {
  const raw = input.trim();
  if (!raw) return "";
  if (/^wss?:\/\//i.test(raw)) return raw;
  if (/^https?:\/\//i.test(raw)) {
    const parsed = new URL(raw);
    parsed.protocol = parsed.protocol === "https:" ? "wss:" : "ws:";
    if (!parsed.port) parsed.port = "8787";
    return parsed.toString();
  }
  return `ws://${hasPort(raw) ? raw : `${raw}:8787`}`;
}

function canRoleMove(role, state) {
  return !!state && !state.result && ((role === "host" && state.turn === "B") || (role === "guest" && state.turn === "W"));
}

function roleLabel(role, mode) {
  if (role === "host") return "Host / Black";
  if (role === "guest") return "Join / White";
  return mode === "host" ? "Hosting" : "Joining";
}

function chip(active, disabled = false) {
  return {
    padding: "7px 14px",
    border: `1px solid ${active ? GOLD : "#252015"}`,
    borderRadius: 5,
    background: active ? GOLD : "transparent",
    color: active ? "#1a1208" : "#6a5838",
    fontFamily: "'DM Sans', sans-serif",
    fontSize: 12,
    fontWeight: active ? 600 : 400,
    letterSpacing: 1,
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.35 : 1,
  };
}

function Lobby({ notice, onStartLocal, onHost, onJoin }) {
  const [mode, setMode] = useState("local");
  const [boardSize, setBoardSize] = useState(11);
  const [timerVal, setTimerVal] = useState(null);
  const [serverUrl, setServerUrl] = useState(defaultServerUrl);
  const submit = () => {
    const config = sanitizeConfig({ boardSize, timerVal });
    if (mode === "local") return onStartLocal(config);
    if (mode === "host") return onHost({ config, serverUrl });
    onJoin({ serverUrl });
  };
  return (
    <div style={{ ...shellStyle, padding: 20 }}>
      <style>{BASE_CSS}</style>
      <div style={{ textAlign: "center", marginBottom: 34 }}>
        <div style={{ fontSize: 36, fontWeight: 700, letterSpacing: 8, color: GOLD, textTransform: "uppercase", lineHeight: 1 }}>Anti-Gomoku</div>
        <div style={{ fontFamily: "'DM Sans'", fontSize: 10, letterSpacing: 4, color: "#3a3020", marginTop: 6, textTransform: "uppercase" }}>Pattern Strategy . Local And Online</div>
      </div>
      {notice ? <div style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 8, border: "1px solid #3c2818", background: "#15100b", color: "#c8a86a", fontFamily: "'DM Sans'", fontSize: 11, maxWidth: 420, textAlign: "center" }}>{notice}</div> : null}
      <div style={{ background: "#111820", border: "1px solid #1c1810", borderRadius: 12, padding: "30px 38px", display: "flex", flexDirection: "column", gap: 24, minWidth: 360, maxWidth: 420, boxShadow: "0 24px 80px rgba(0,0,0,0.6)" }}>
        <div style={{ display: "flex", gap: 8 }}>
          {["local", "host", "join"].map((item) => (
            <button key={item} className="mode-tab" onClick={() => setMode(item)} style={{ ...chip(mode === item), flex: 1, fontSize: 11, textTransform: "uppercase", letterSpacing: 2 }}>
              {item}
            </button>
          ))}
        </div>
        <div>
          <div style={{ fontFamily: "'DM Sans'", fontSize: 10, letterSpacing: 3, color: "#4a3c20", textTransform: "uppercase", marginBottom: 11 }}>Server</div>
          <input className="panel-input" value={serverUrl} onChange={(e) => setServerUrl(e.target.value)} placeholder="127.0.0.1:8787" disabled={mode === "local"} style={{ width: "100%", padding: "11px 12px", borderRadius: 7, border: `1px solid ${mode === "local" ? "#181410" : "#2e2818"}`, background: mode === "local" ? "#0d1117" : "#0c1117", color: mode === "local" ? "#56462a" : "#dcc798", fontFamily: "'DM Sans'", fontSize: 12 }} />
          <div style={{ marginTop: 8, fontFamily: "'DM Sans'", fontSize: 10, color: "#5f5032", lineHeight: 1.7 }}>{mode === "local" ? "Local mode does not use the server." : "Enter the server IP or ws:// address. Port 8787 is used by default."}</div>
        </div>
        <div>
          <div style={{ fontFamily: "'DM Sans'", fontSize: 10, letterSpacing: 3, color: "#4a3c20", textTransform: "uppercase", marginBottom: 11 }}>Board Size</div>
          <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>{SIZE_OPTIONS.map((size) => <button key={size} className="chip-btn" onClick={() => setBoardSize(size)} disabled={mode === "join"} style={chip(boardSize === size, mode === "join")}>{size} x {size}</button>)}</div>
        </div>
        <div>
          <div style={{ fontFamily: "'DM Sans'", fontSize: 10, letterSpacing: 3, color: "#4a3c20", textTransform: "uppercase", marginBottom: 11 }}>Time Per Player</div>
          <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>{TIMER_OPTIONS.map((option) => <button key={option.label} className="chip-btn" onClick={() => setTimerVal(option.value)} disabled={mode === "join"} style={chip(timerVal === option.value, mode === "join")}>{option.label}</button>)}</div>
          {mode === "join" ? <div style={{ marginTop: 8, fontFamily: "'DM Sans'", fontSize: 10, color: "#5f5032", lineHeight: 1.7 }}>Join follows the host&apos;s board size and clock automatically.</div> : null}
        </div>
        <div style={{ borderTop: "1px solid #181410", paddingTop: 20, fontFamily: "'DM Sans'", fontSize: 11, color: "#4a3c20", lineHeight: 1.9 }}>
          <div><span style={{ color: "#a88040" }}>Pattern of 5</span>  -&gt; win</div>
          <div><span style={{ color: "#904030" }}>Pattern of 4</span>  -&gt; opponent wins</div>
          <div style={{ color: "#2e2618", marginTop: 3 }}>n pieces . collinear . equally spaced . any direction</div>
        </div>
      </div>
      <button className="start-btn" onClick={submit} style={{ marginTop: 22, padding: "11px 50px", fontSize: 11, fontFamily: "'DM Sans'", fontWeight: 500, letterSpacing: 4, textTransform: "uppercase", background: GOLD, color: "#1a1208", border: "none", borderRadius: 6, cursor: "pointer", boxShadow: "0 4px 24px rgba(232,201,106,0.22)" }}>
        {mode === "local" ? "Start Local Game" : mode === "host" ? "Host Room" : "Join Room"}
      </button>
    </div>
  );
}

function TimerBox({ player, time, isActive, noTimer }) {
  const isBlack = player === "B";
  const low = !noTimer && isActive && time !== null && time < 15;
  return (
    <div style={{ padding: "9px 18px", borderRadius: 7, minWidth: 88, textAlign: "center", border: `1px solid ${isActive ? (isBlack ? "#383028" : "#ccc8bc") : "#181410"}`, background: isBlack ? (isActive ? "#0e0c0a" : "#090807") : isActive ? "#ede9dd" : "#d4d0c4", opacity: isActive ? 1 : 0.35 }}>
      <div style={{ fontFamily: "'DM Sans'", fontSize: 9, letterSpacing: 2, textTransform: "uppercase", color: isBlack ? "#504030" : "#907050", marginBottom: 3 }}>{isBlack ? "Black" : "White"}</div>
      <div style={{ fontFamily: "'Cormorant Garamond'", fontSize: 22, fontWeight: 700, lineHeight: 1, color: low ? "#c03020" : isBlack ? "#c8b888" : "#2a2010", animation: low ? "pulse .75s ease-in-out infinite" : "none" }}>{noTimer ? "INF" : formatTime(time)}</div>
    </div>
  );
}

function Status({ state, message, sub }) {
  if (state.result) {
    return (
      <>
        <div style={{ fontFamily: "'DM Sans'", fontSize: 11, color: "#a88850", letterSpacing: 0.3, lineHeight: 1.4 }}>{state.result.msg}</div>
        <div style={{ fontFamily: "'Cormorant Garamond'", fontSize: 19, fontWeight: 700, marginTop: 1 }}>{state.result.sub}</div>
        {message ? <div style={{ fontFamily: "'DM Sans'", fontSize: 10, color: "#6b5a36", marginTop: 6, lineHeight: 1.6 }}>{message}</div> : null}
      </>
    );
  }
  return (
    <>
      <div style={{ fontFamily: "'DM Sans'", fontSize: 11, color: state.turn === "B" ? "#b8a878" : "#706050", letterSpacing: 1 }}>{message}</div>
      {sub ? <div style={{ fontFamily: "'DM Sans'", fontSize: 10, color: "#6b5a36", marginTop: 4, lineHeight: 1.6 }}>{sub}</div> : null}
    </>
  );
}

function Board({ config, state, canPlace, onPlace }) {
  const n = config.boardSize;
  const size = (n - 1) * CELL + 2 * MARGIN;
  const stars = starPoints(n);
  const hi = state.result ? new Set(state.result.highlight.map(([r, c]) => `${r},${c}`)) : new Set();
  return (
    <svg width={size} height={size} style={{ borderRadius: 8, boxShadow: "0 12px 60px rgba(0,0,0,.75)", display: "block", flexShrink: 0 }}>
      <defs>
        <radialGradient id="bg2" cx="38%" cy="32%"><stop offset="0%" stopColor="#c89030" /><stop offset="100%" stopColor="#8a5c18" /></radialGradient>
        <radialGradient id="gB2" cx="34%" cy="28%"><stop offset="0%" stopColor="#5a5a5a" /><stop offset="100%" stopColor="#060606" /></radialGradient>
        <radialGradient id="gW2" cx="34%" cy="28%"><stop offset="0%" stopColor="#ffffff" /><stop offset="100%" stopColor="#c0b8a8" /></radialGradient>
        <filter id="ps2"><feDropShadow dx="1" dy="2" stdDeviation="2" floodOpacity="0.4" /></filter>
        <filter id="glow2"><feGaussianBlur stdDeviation="3.5" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      </defs>
      <rect width={size} height={size} fill="url(#bg2)" rx={8} />
      {Array.from({ length: n }, (_, i) => <g key={i}><line x1={MARGIN} y1={MARGIN + i * CELL} x2={MARGIN + (n - 1) * CELL} y2={MARGIN + i * CELL} stroke="#6a4010" strokeWidth={i === 0 || i === n - 1 ? 1.5 : 0.8} /><line x1={MARGIN + i * CELL} y1={MARGIN} x2={MARGIN + i * CELL} y2={MARGIN + (n - 1) * CELL} stroke="#6a4010" strokeWidth={i === 0 || i === n - 1 ? 1.5 : 0.8} /></g>)}
      {stars.map(([r, c]) => <circle key={`s-${r}-${c}`} cx={MARGIN + c * CELL} cy={MARGIN + r * CELL} r={3} fill="#6a4010" />)}
      {state.result ? state.result.highlight.map(([r, c]) => <rect key={`hl-${r}-${c}`} x={MARGIN + c * CELL - CELL / 2} y={MARGIN + r * CELL - CELL / 2} width={CELL} height={CELL} fill={GOLD} opacity={0.15} rx={2} />) : null}
      {state.board.flatMap((row, r) => row.map((cell, c) => {
        if (!cell) return null;
        const x = MARGIN + c * CELL, y = MARGIN + r * CELL, last = state.last?.[0] === r && state.last?.[1] === c;
        return <g key={`p-${r}-${c}`} filter="url(#ps2)"><circle cx={x} cy={y} r={PR} fill={`url(#g${cell}2)`} stroke={cell === "B" ? "#383838" : "#a8a098"} strokeWidth={0.8} />{last && !state.result ? <circle cx={x} cy={y} r={4} fill={cell === "B" ? GOLD : "#b83020"} opacity={0.85} /> : null}{hi.has(`${r},${c}`) ? <circle cx={x} cy={y} r={PR} fill="none" stroke={GOLD} strokeWidth={2.5} opacity={0.9} filter="url(#glow2)" /> : null}</g>;
      }))}
      {state.board.flatMap((row, r) => row.map((cell, c) => <rect key={`h-${r}-${c}`} x={MARGIN + c * CELL - CELL / 2} y={MARGIN + r * CELL - CELL / 2} width={CELL} height={CELL} fill="transparent" style={{ cursor: canPlace && !cell ? "pointer" : "default" }} onClick={() => { if (canPlace && !cell) onPlace(r, c); }} />))}
    </svg>
  );
}

function Shell({ config, state, active, canPlace, onPlace, onBack, backLabel, rightLabel, status, controls }) {
  const n = config.boardSize;
  const size = (n - 1) * CELL + 2 * MARGIN;
  return (
    <div style={shellStyle}>
      <style>{BASE_CSS}</style>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 13, width: "100%", maxWidth: size + 20 }}>
        <button className="menu-btn" onClick={onBack} style={{ background: "transparent", border: "1px solid #2a2018", color: "#5a4a28", fontFamily: "'DM Sans'", fontSize: 9, letterSpacing: 2, textTransform: "uppercase", padding: "6px 13px", borderRadius: 4, cursor: "pointer" }}>{backLabel}</button>
        <div style={{ flex: 1, textAlign: "center", fontSize: 18, fontWeight: 700, letterSpacing: 5, color: GOLD, textTransform: "uppercase" }}>Anti-Gomoku</div>
        <div style={{ fontFamily: "'DM Sans'", fontSize: 10, color: "#3a3020", minWidth: 110, textAlign: "right" }}>{n} x {n} | {rightLabel}</div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12, width: "100%", maxWidth: size + 20 }}>
        <TimerBox player="B" time={state.times.B} isActive={active === "B"} noTimer={config.timerVal === null} />
        <div style={{ flex: 1, textAlign: "center", padding: "0 6px", minWidth: 0 }}>{status}</div>
        <TimerBox player="W" time={state.times.W} isActive={active === "W"} noTimer={config.timerVal === null} />
      </div>
      <Board config={config} state={state} canPlace={canPlace} onPlace={onPlace} />
      <div style={{ display: "flex", gap: 10, marginTop: 13, flexWrap: "wrap", justifyContent: "center" }}>{controls}</div>
    </div>
  );
}

function actionBtn(kind, disabled = false) {
  return {
    padding: kind === "ghost" ? "8px 20px" : "8px 22px",
    fontSize: 10,
    fontFamily: "'DM Sans'",
    fontWeight: kind === "ghost" ? 400 : 500,
    letterSpacing: 3,
    textTransform: "uppercase",
    background: kind === "ghost" ? "transparent" : GOLD,
    color: kind === "ghost" ? (disabled ? "#252018" : "#7a6840") : "#1a1208",
    border: kind === "ghost" ? `1px solid ${disabled ? "#1a1610" : "#2e2818"}` : "none",
    borderRadius: 5,
    cursor: disabled ? "not-allowed" : "pointer",
    boxShadow: kind === "ghost" ? "none" : "0 2px 14px rgba(232,201,106,0.2)",
  };
}

function LocalGame({ config, onMenu }) {
  const [state, setState] = useState(() => createMatchState(config));
  const [history, setHistory] = useState([]);
  useEffect(() => {
    if (config.timerVal === null || state.result) return undefined;
    const id = setInterval(() => setState((prev) => tickClock(prev, config)), 1000);
    return () => clearInterval(id);
  }, [config, state.result]);
  const place = (r, c) => {
    const next = applyMove(state, config, r, c);
    if (!next) return;
    setHistory((prev) => [...prev, cloneState(state)]);
    setState(next);
  };
  const takeback = () => {
    if (!history.length) return;
    setState(history[history.length - 1]);
    setHistory((prev) => prev.slice(0, -1));
  };
  return <Shell config={config} state={state} active={state.result ? null : state.turn} canPlace={!state.result} onPlace={place} onBack={onMenu} backLabel="<- Menu" rightLabel="Local" status={<Status state={state} message={`${pName(state.turn)}'s turn`} />} controls={<><button className="tb-btn" onClick={takeback} disabled={!history.length} style={actionBtn("ghost", !history.length)}>Takeback</button><button className="ng-btn" onClick={onMenu} style={actionBtn("solid")}>New Game</button></>} />;
}

function OnlineGame({ session, onMove, onLeave, onRematch }) {
  const config = session.config;
  const state = session.gameState || createMatchState(config);
  const canPlace = session.phase === "active" && canRoleMove(session.role, state);
  const requested = session.role ? session.rematch?.[session.role] : false;
  let message = session.notice || "";
  let sub = "";
  if (!state.result) {
    if (session.phase === "waiting") sub = session.mode === "host" ? "Stay here while the other player joins this server." : "Waiting for the host to start.";
    if (session.phase === "connecting") sub = "Opening the room connection.";
    if (session.phase === "active") { message = `${pName(state.turn)}'s turn`; sub = canPlace ? "Your move." : "Opponent's move."; }
  } else if (requested) sub = "Rematch requested. Waiting for the other player.";
  else if (session.phase === "finished") sub = "Rematch keeps the same room settings and players.";
  return <Shell config={config} state={state} active={session.phase === "active" && !state.result ? state.turn : null} canPlace={canPlace} onPlace={onMove} onBack={onLeave} backLabel="<- Leave" rightLabel={roleLabel(session.role, session.mode)} status={<Status state={state} message={message} sub={sub} />} controls={<><button className="tb-btn" onClick={onRematch} disabled={session.phase !== "finished" || requested} style={actionBtn("ghost", session.phase !== "finished" || requested)}>{requested ? "Waiting..." : "Rematch"}</button><button className="ng-btn" onClick={onLeave} style={actionBtn("solid")}>Exit Room</button></>} />;
}

export default function App() {
  const [screen, setScreen] = useState("menu");
  const [localConfig, setLocalConfig] = useState(() => sanitizeConfig({ boardSize: 11, timerVal: null }));
  const [localGameKey, setLocalGameKey] = useState(0);
  const [onlineSession, setOnlineSession] = useState(null);
  const [lobbyNotice, setLobbyNotice] = useState("");
  const socketRef = useRef(null);
  const onlineRef = useRef(null);

  useEffect(() => { onlineRef.current = onlineSession; }, [onlineSession]);
  useEffect(() => () => { if (socketRef.current) { try { socketRef.current.close(); } catch {} } }, []);

  const closeOnline = (notice = "", sendLeave = false) => {
    const socket = socketRef.current;
    socketRef.current = null;
    if (socket) {
      try { if (sendLeave && socket.readyState === 1) socket.send(JSON.stringify({ type: "leave" })); } catch {}
      try { socket.close(); } catch {}
    }
    setOnlineSession(null);
    setScreen("menu");
    setLobbyNotice(notice);
  };

  const startLocal = (config) => {
    setLobbyNotice("");
    setLocalConfig(sanitizeConfig(config));
    setLocalGameKey((key) => key + 1);
    setScreen("local");
  };

  const startOnline = (mode, { config, serverUrl }) => {
    const url = normalizeServerUrl(serverUrl);
    const clean = sanitizeConfig(config || { boardSize: 11, timerVal: null });
    if (!url) return setLobbyNotice("Please enter a valid server address.");
    setLobbyNotice("");
    setScreen("online");
    setOnlineSession({ mode, role: mode === "host" ? "host" : null, phase: "connecting", config: clean, gameState: createMatchState(clean), rematch: { host: false, guest: false }, notice: mode === "host" ? "Connecting to server..." : "Joining room..." });
    const socket = new WebSocket(url);
    socketRef.current = socket;
    let closeMessage = "Connection closed.";

    socket.onopen = () => socket.send(JSON.stringify(mode === "host" ? { type: "host_game", config: clean } : { type: "join_game" }));
    socket.onerror = () => { closeMessage = "Unable to reach the game server."; };
    socket.onmessage = (event) => {
      let payload = null;
      try { payload = JSON.parse(event.data); } catch { return closeOnline("Received an unreadable server message."); }
      if (payload.type === "snapshot") {
        return setOnlineSession((prev) => prev ? { ...prev, role: payload.role ?? prev.role, phase: payload.phase || prev.phase, config: sanitizeConfig(payload.config || prev.config), gameState: payload.gameState || prev.gameState, rematch: payload.rematch || prev.rematch, notice: payload.notice || "" } : prev);
      }
      if (payload.type === "error" || payload.type === "room_closed") {
        closeMessage = payload.message || (payload.type === "error" ? "Unable to join the room." : "The room was closed.");
        closeOnline(closeMessage);
      }
    };
    socket.onclose = () => {
      if (socketRef.current !== socket) return;
      socketRef.current = null;
      if (onlineRef.current) {
        setOnlineSession(null);
        setScreen("menu");
        setLobbyNotice(closeMessage);
      }
    };
  };

  const moveOnline = (row, col) => {
    const socket = socketRef.current;
    if (socket && socket.readyState === 1) socket.send(JSON.stringify({ type: "move", row, col }));
  };

  const requestRematch = () => {
    const socket = socketRef.current;
    if (socket && socket.readyState === 1) socket.send(JSON.stringify({ type: "rematch_request" }));
  };

  if (screen === "menu") return <Lobby notice={lobbyNotice} onStartLocal={startLocal} onHost={({ config, serverUrl }) => startOnline("host", { config, serverUrl })} onJoin={({ serverUrl }) => startOnline("join", { serverUrl, config: { boardSize: 11, timerVal: null } })} />;
  if (screen === "local") return <LocalGame key={localGameKey} config={localConfig} onMenu={() => setScreen("menu")} />;
  if (!onlineSession) return <Lobby notice="Room state was cleared. Please connect again." onStartLocal={startLocal} onHost={({ config, serverUrl }) => startOnline("host", { config, serverUrl })} onJoin={({ serverUrl }) => startOnline("join", { serverUrl, config: { boardSize: 11, timerVal: null } })} />;
  return <OnlineGame session={onlineSession} onMove={moveOnline} onLeave={() => closeOnline("", true)} onRematch={requestRematch} />;
}
