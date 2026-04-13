import { useEffect, useRef, useState } from "react";
import {
  CELL,
  GOLD,
  MARGIN,
  PR,
  applyMove,
  createMatchState,
  formatClockSetting,
  formatTime,
  pName,
  starPoints,
  tickClock,
} from "./game-core.mjs";
import {
  addVariation,
  exportRecordText,
  findDeepestMainlineNode,
  getChildNodes,
  getNodePath,
  getTimeline,
  importRecordText,
  moveToNotation,
  promoteNodePathToMain,
  replayRecord,
} from "./game-record.mjs";
import { copyTextToClipboard } from "./online-room.mjs";

const BASE_CSS = `@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;600;700&family=DM+Sans:wght@300;400;500&display=swap');*{box-sizing:border-box}button,input{transition:all .15s ease}button,input,textarea{font:inherit}@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}.tb-btn:hover:not(:disabled){color:#c8b060!important;border-color:#6a5030!important}.ng-btn:hover:not(:disabled),.start-btn:hover:not(:disabled){filter:brightness(1.08);transform:translateY(-1px)}.menu-btn:hover{color:#a89060!important;border-color:#4a3820!important}.panel-input:focus{outline:none;border-color:#8d713e!important;box-shadow:0 0 0 2px rgba(232,201,106,.08)}`;

const shellStyle = {
  minHeight: "100vh",
  width: "100%",
  background: "#0d1117",
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  justifyContent: "flex-start",
  fontFamily: "'Cormorant Garamond', Georgia, serif",
  color: "#e8dcc8",
  padding: "clamp(12px, 3vw, 28px)",
};

function cloneState(state) {
  return {
    board: state.board.map((row) => [...row]),
    turn: state.turn,
    times: { ...state.times },
    result: state.result ? { ...state.result, highlight: state.result.highlight.map(([row, col]) => [row, col]) } : null,
    last: state.last ? [...state.last] : null,
  };
}

function colorForRole(game, role) {
  if (!game?.seats || !role) return null;
  if (game.seats.B === role) return "B";
  if (game.seats.W === role) return "W";
  return null;
}

function canRoleMove(role, state, game) {
  return !!state && !state.result && colorForRole(game, role) === state.turn;
}

function roleLabel(role, mode, game) {
  const color = colorForRole(game, role);
  if (role === "host") return `Host${color ? ` / ${pName(color)}` : ""}`;
  if (role === "guest") return `Join${color ? ` / ${pName(color)}` : ""}`;
  if (mode === "spectate") return "Spectating";
  return mode === "host" ? "Hosting" : "Joining";
}

function formatRatingValue(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.round(parsed) : null;
}

function formatPlayerLabel(player) {
  if (!player) return "Open seat";
  const rating = formatRatingValue(player.rating);
  return [
    player.displayName || "Unknown",
    player.loginId ? `@${player.loginId}` : player.authenticated ? "" : "guest",
    rating === null ? "" : `R${rating}`,
  ].filter(Boolean).join(" | ");
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

function ghostButton(disabled = false) {
  return {
    padding: "10px 14px",
    borderRadius: 10,
    border: `1px solid ${disabled ? "#221b11" : "#2f2618"}`,
    background: "transparent",
    color: disabled ? "#57472b" : "#d6bd89",
    fontFamily: "'DM Sans'",
    fontSize: 11,
    letterSpacing: 2,
    textTransform: "uppercase",
    cursor: disabled ? "not-allowed" : "pointer",
  };
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

function pointKey(row, col) {
  return `${row}:${col}`;
}

function samePoint(left, right) {
  return !!left && !!right && left.row === right.row && left.col === right.col;
}

function normalizeLineEndpoints(start, end) {
  if (!start || !end) return [start, end];
  const startKey = pointKey(start.row, start.col);
  const endKey = pointKey(end.row, end.col);
  return startKey <= endKey ? [start, end] : [end, start];
}

function lineKey(start, end) {
  const [first, second] = normalizeLineEndpoints(start, end);
  return `${pointKey(first.row, first.col)}|${pointKey(second.row, second.col)}`;
}

function boardPixelPoint(row, col) {
  return {
    x: MARGIN + col * CELL,
    y: MARGIN + row * CELL,
  };
}

function distanceToSegment(pointX, pointY, startX, startY, endX, endY) {
  const segmentX = endX - startX;
  const segmentY = endY - startY;
  const segmentLengthSquared = segmentX * segmentX + segmentY * segmentY;
  if (!segmentLengthSquared) {
    return Math.hypot(pointX - startX, pointY - startY);
  }
  const projection = Math.max(0, Math.min(1, ((pointX - startX) * segmentX + (pointY - startY) * segmentY) / segmentLengthSquared));
  const projectedX = startX + projection * segmentX;
  const projectedY = startY + projection * segmentY;
  return Math.hypot(pointX - projectedX, pointY - projectedY);
}

function Board({ config, state, canPlace, onPlace, annotationScopeKey = "board", annotationResetToken = 0 }) {
  const boardSize = config.boardSize;
  const size = (boardSize - 1) * CELL + 2 * MARGIN;
  const stars = starPoints(boardSize);
  const highlights = state.result ? new Set(state.result.highlight.map(([row, col]) => `${row},${col}`)) : new Set();
  const svgRef = useRef(null);
  const rightDragRef = useRef(null);
  const [annotations, setAnnotations] = useState(() => ({ points: [], lines: [] }));
  const [annotationPreview, setAnnotationPreview] = useState(null);

  useEffect(() => {
    setAnnotations({ points: [], lines: [] });
    setAnnotationPreview(null);
    rightDragRef.current = null;
  }, [annotationScopeKey, annotationResetToken, boardSize]);

  const syncAnnotationPreview = (preview) => {
    rightDragRef.current = preview
      ? {
        ...(rightDragRef.current || {}),
        pointerId: preview.pointerId,
        start: preview.start,
        current: preview.current,
      }
      : null;
    setAnnotationPreview(preview ? { start: preview.start, current: preview.current } : null);
  };

  const resolveBoardGesture = (clientX, clientY) => {
    const svg = svgRef.current;
    if (!svg) return null;
    const rect = svg.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const rawX = ((clientX - rect.left) / rect.width) * size;
    const rawY = ((clientY - rect.top) / rect.height) * size;
    const col = Math.max(0, Math.min(boardSize - 1, Math.round((rawX - MARGIN) / CELL)));
    const row = Math.max(0, Math.min(boardSize - 1, Math.round((rawY - MARGIN) / CELL)));
    return { row, col, rawX, rawY };
  };

  const togglePointAnnotation = (point) => {
    const id = pointKey(point.row, point.col);
    setAnnotations((prev) => (
      prev.points.some((entry) => entry.id === id)
        ? { ...prev, points: prev.points.filter((entry) => entry.id !== id) }
        : { ...prev, points: [...prev.points, { id, row: point.row, col: point.col }] }
    ));
  };

  const toggleLineAnnotation = (start, end) => {
    const [from, to] = normalizeLineEndpoints(start, end);
    const id = lineKey(from, to);
    setAnnotations((prev) => (
      prev.lines.some((entry) => entry.id === id)
        ? { ...prev, lines: prev.lines.filter((entry) => entry.id !== id) }
        : { ...prev, lines: [...prev.lines, { id, from, to }] }
    ));
  };

  return (
    <div style={{ width: "100%", maxWidth: size, alignSelf: "center" }}>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${size} ${size}`}
        style={{ width: "100%", height: "auto", display: "block", borderRadius: 8, boxShadow: "0 12px 60px rgba(0,0,0,.75)", touchAction: "manipulation" }}
        onContextMenu={(event) => event.preventDefault()}
        onPointerDown={(event) => {
          if (event.button !== 2) return;
          const gesturePoint = resolveBoardGesture(event.clientX, event.clientY);
          if (!gesturePoint) return;
          event.preventDefault();
          syncAnnotationPreview({
            pointerId: event.pointerId,
            start: { row: gesturePoint.row, col: gesturePoint.col },
            current: { row: gesturePoint.row, col: gesturePoint.col },
          });
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          if (!rightDragRef.current || rightDragRef.current.pointerId !== event.pointerId) {
            return;
          }
          const gesturePoint = resolveBoardGesture(event.clientX, event.clientY);
          if (!gesturePoint) return;
          event.preventDefault();
          syncAnnotationPreview({
            ...rightDragRef.current,
            current: { row: gesturePoint.row, col: gesturePoint.col },
          });
        }}
        onPointerUp={(event) => {
          if (!rightDragRef.current || rightDragRef.current.pointerId !== event.pointerId) {
            return;
          }
          const gesturePoint = resolveBoardGesture(event.clientX, event.clientY);
          const preview = {
            ...rightDragRef.current,
            current: gesturePoint ? { row: gesturePoint.row, col: gesturePoint.col } : rightDragRef.current.current,
          };
          syncAnnotationPreview(null);
          if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
            event.currentTarget.releasePointerCapture(event.pointerId);
          }
          if (!preview) return;
          event.preventDefault();
          if (samePoint(preview.start, preview.current)) {
            togglePointAnnotation(preview.start);
            return;
          }
          toggleLineAnnotation(preview.start, preview.current);
        }}
        onPointerCancel={(event) => {
          if (rightDragRef.current?.pointerId === event.pointerId) {
            rightDragRef.current = null;
            setAnnotationPreview(null);
          }
        }}
      >
        <defs>
          <radialGradient id="bg2" cx="38%" cy="32%"><stop offset="0%" stopColor="#c89030" /><stop offset="100%" stopColor="#8a5c18" /></radialGradient>
          <radialGradient id="gB2" cx="34%" cy="28%"><stop offset="0%" stopColor="#5a5a5a" /><stop offset="100%" stopColor="#060606" /></radialGradient>
          <radialGradient id="gW2" cx="34%" cy="28%"><stop offset="0%" stopColor="#ffffff" /><stop offset="100%" stopColor="#c0b8a8" /></radialGradient>
          <filter id="ps2"><feDropShadow dx="1" dy="2" stdDeviation="2" floodOpacity="0.4" /></filter>
          <filter id="glow2"><feGaussianBlur stdDeviation="3.5" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
          <filter id="annotationGlow"><feDropShadow dx="0" dy="0" stdDeviation="2.3" floodColor="#f4d99a" floodOpacity="0.48" /></filter>
        </defs>
        <rect width={size} height={size} fill="url(#bg2)" rx={8} />
        {Array.from({ length: boardSize }, (_, index) => (
          <g key={index}>
            <line x1={MARGIN} y1={MARGIN + index * CELL} x2={MARGIN + (boardSize - 1) * CELL} y2={MARGIN + index * CELL} stroke="#6a4010" strokeWidth={index === 0 || index === boardSize - 1 ? 1.5 : 0.8} />
            <line x1={MARGIN + index * CELL} y1={MARGIN} x2={MARGIN + index * CELL} y2={MARGIN + (boardSize - 1) * CELL} stroke="#6a4010" strokeWidth={index === 0 || index === boardSize - 1 ? 1.5 : 0.8} />
          </g>
        ))}
        {stars.map(([row, col]) => <circle key={`star-${row}-${col}`} cx={MARGIN + col * CELL} cy={MARGIN + row * CELL} r={3} fill="#6a4010" />)}
        {state.result ? state.result.highlight.map(([row, col]) => <rect key={`hl-${row}-${col}`} x={MARGIN + col * CELL - CELL / 2} y={MARGIN + row * CELL - CELL / 2} width={CELL} height={CELL} fill={GOLD} opacity={0.15} rx={2} />) : null}
        {state.board.flatMap((row, rowIndex) => row.map((cell, colIndex) => {
          if (!cell) return null;
          const x = MARGIN + colIndex * CELL;
          const y = MARGIN + rowIndex * CELL;
          const isLast = state.last?.[0] === rowIndex && state.last?.[1] === colIndex;
          return (
            <g key={`piece-${rowIndex}-${colIndex}`} filter="url(#ps2)">
              <circle cx={x} cy={y} r={PR} fill={`url(#g${cell}2)`} stroke={cell === "B" ? "#383838" : "#a8a098"} strokeWidth={0.8} />
              {isLast && !state.result ? <circle cx={x} cy={y} r={4} fill={cell === "B" ? GOLD : "#b83020"} opacity={0.85} /> : null}
              {highlights.has(`${rowIndex},${colIndex}`) ? <circle cx={x} cy={y} r={PR} fill="none" stroke={GOLD} strokeWidth={2.5} opacity={0.9} filter="url(#glow2)" /> : null}
            </g>
          );
        }))}
        {annotations.lines.map((line) => {
          const from = boardPixelPoint(line.from.row, line.from.col);
          const to = boardPixelPoint(line.to.row, line.to.col);
          return (
            <g key={line.id} pointerEvents="none">
              <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke="rgba(184,122,36,0.96)" strokeWidth={8.4} strokeLinecap="round" />
              <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke="rgba(78,46,13,0.82)" strokeWidth={5.6} strokeLinecap="round" />
              <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke="rgba(244,217,154,0.96)" strokeWidth={3.1} strokeLinecap="round" />
              <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke="rgba(255,245,211,0.46)" strokeWidth={1.3} strokeLinecap="round" />
            </g>
          );
        })}
        {annotationPreview && !samePoint(annotationPreview.start, annotationPreview.current) ? (() => {
          const from = boardPixelPoint(annotationPreview.start.row, annotationPreview.start.col);
          const to = boardPixelPoint(annotationPreview.current.row, annotationPreview.current.col);
          return (
            <g pointerEvents="none">
              <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke="rgba(184,122,36,0.94)" strokeWidth={8} strokeDasharray="12 8" strokeLinecap="round" />
              <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke="rgba(97,60,18,0.78)" strokeWidth={5.2} strokeDasharray="12 8" strokeLinecap="round" />
              <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke="rgba(240,205,128,0.96)" strokeWidth={3} strokeDasharray="12 8" strokeLinecap="round" />
            </g>
          );
        })() : null}
        {annotations.points.map((point) => {
          const center = boardPixelPoint(point.row, point.col);
          return (
            <g key={point.id} pointerEvents="none" filter="url(#annotationGlow)">
              <circle cx={center.x} cy={center.y} r={PR + 4.4} fill="none" stroke="rgba(78,46,13,0.52)" strokeWidth={5.4} />
              <circle cx={center.x} cy={center.y} r={PR + 3.1} fill="none" stroke="rgba(242,214,143,0.92)" strokeWidth={2.7} />
              <circle cx={center.x} cy={center.y} r={PR + 1.5} fill="none" stroke="rgba(255,246,216,0.42)" strokeWidth={1.1} />
            </g>
          );
        })}
        {annotationPreview && samePoint(annotationPreview.start, annotationPreview.current) ? (() => {
          const center = boardPixelPoint(annotationPreview.start.row, annotationPreview.start.col);
          return (
            <g pointerEvents="none" filter="url(#annotationGlow)">
              <circle cx={center.x} cy={center.y} r={PR + 3.8} fill="none" stroke="rgba(97,60,18,0.46)" strokeWidth={5} strokeDasharray="10 7" />
              <circle cx={center.x} cy={center.y} r={PR + 2.5} fill="none" stroke="rgba(240,205,128,0.94)" strokeWidth={2.6} strokeDasharray="10 7" />
            </g>
          );
        })() : null}
        {state.board.flatMap((row, rowIndex) => row.map((cell, colIndex) => (
          <rect
            key={`hit-${rowIndex}-${colIndex}`}
            x={MARGIN + colIndex * CELL - CELL / 2}
            y={MARGIN + rowIndex * CELL - CELL / 2}
            width={CELL}
            height={CELL}
            fill="transparent"
            style={{ cursor: canPlace && !cell ? "pointer" : "default" }}
            onClick={() => {
              if (canPlace && !cell) onPlace(rowIndex, colIndex);
            }}
          />
        )))}
      </svg>
    </div>
  );
}

function Shell({ config, state, active, canPlace, onPlace, onBack, backLabel, rightLabel, status, banner, controls, footerPanels, annotationScopeKey, annotationResetToken = 0 }) {
  const boardSize = config.boardSize;
  const size = (boardSize - 1) * CELL + 2 * MARGIN;
  const frameWidth = footerPanels ? Math.min(Math.max(size + 20, 1020), 1200) : Math.min(size + 20, 920);

  return (
    <div style={shellStyle}>
      <style>{BASE_CSS}</style>
      <div style={{ width: "100%", maxWidth: frameWidth }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 13 }}>
          <button className="menu-btn" onClick={onBack} style={{ background: "transparent", border: "1px solid #2a2018", color: "#5a4a28", fontFamily: "'DM Sans'", fontSize: 9, letterSpacing: 2, textTransform: "uppercase", padding: "6px 13px", borderRadius: 4, cursor: "pointer" }}>{backLabel}</button>
          <div style={{ flex: "1 1 240px", textAlign: "center", fontSize: 18, fontWeight: 700, letterSpacing: 5, color: GOLD, textTransform: "uppercase" }}>Anti-Gomoku</div>
          <div style={{ fontFamily: "'DM Sans'", fontSize: 10, color: "#3a3020", textAlign: "right", flex: "1 1 140px" }}>{boardSize} x {boardSize} | {rightLabel}</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
          <TimerBox player="B" time={state.times.B} isActive={active === "B"} noTimer={config.baseSeconds === null} />
          <div style={{ flex: "1 1 240px", minWidth: 0, textAlign: "center", padding: "0 6px" }}>{status}</div>
          <TimerBox player="W" time={state.times.W} isActive={active === "W"} noTimer={config.baseSeconds === null} />
        </div>
        {banner}
        <Board config={config} state={state} canPlace={canPlace} onPlace={onPlace} annotationScopeKey={annotationScopeKey} annotationResetToken={annotationResetToken} />
        <div style={{ display: "flex", gap: 10, marginTop: 13, flexWrap: "wrap", justifyContent: "center" }}>{controls}</div>
        {footerPanels ? <div style={{ marginTop: 16 }}>{footerPanels}</div> : null}
      </div>
    </div>
  );
}

function SharePanel({ link, copied, onCopy }) {
  if (!link) return null;

  return (
    <div style={{ width: "100%", maxWidth: 640, margin: "0 auto 12px", padding: "10px 12px", borderRadius: 8, border: "1px solid #2a2018", background: "#11161d" }}>
      <div style={{ fontFamily: "'DM Sans'", fontSize: 10, letterSpacing: 2, textTransform: "uppercase", color: "#7b6740", marginBottom: 8 }}>Invite Link</div>
      <div style={{ display: "flex", gap: 8, alignItems: "stretch", flexWrap: "wrap" }}>
        <input
          readOnly
          value={link}
          onFocus={(event) => event.currentTarget.select()}
          onClick={(event) => event.currentTarget.select()}
          style={{ flex: "1 1 320px", minWidth: 0, padding: "10px 11px", borderRadius: 6, border: "1px solid #2e2818", background: "#0c1117", color: "#dcc798", fontFamily: "'DM Sans'", fontSize: 11 }}
        />
        <button className="tb-btn" onClick={onCopy} style={actionBtn("ghost", false)}>{copied ? "Copied" : "Copy Link"}</button>
      </div>
      <div style={{ marginTop: 8, fontFamily: "'DM Sans'", fontSize: 10, color: "#6b5a36", lineHeight: 1.6 }}>The field stays selectable as a fallback, so the link can still be copied manually if the clipboard is blocked.</div>
    </div>
  );
}

function PlayerRosterPanel({ roomSummary, game }) {
  if (!roomSummary?.host && !roomSummary?.guest) {
    return null;
  }

  const hasSeats = !!game?.seats;
  const blackPlayer = game?.seats?.B === "host" ? roomSummary.host : game?.seats?.B === "guest" ? roomSummary.guest : roomSummary.host;
  const whitePlayer = game?.seats?.W === "host" ? roomSummary.host : game?.seats?.W === "guest" ? roomSummary.guest : roomSummary.guest;
  const spectators = roomSummary?.spectators || [];

  return (
    <div style={{ width: "100%", maxWidth: 640, margin: "0 auto 12px", padding: "10px 12px", borderRadius: 8, border: "1px solid #2a2018", background: "#11161d", display: "grid", gap: 8 }}>
      <div style={{ fontFamily: "'DM Sans'", fontSize: 10, letterSpacing: 2, textTransform: "uppercase", color: "#7b6740" }}>Players</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 8, fontFamily: "'DM Sans'", fontSize: 11, color: "#dcc798" }}>
        <div><span style={{ color: "#8f7546" }}>{hasSeats ? "Black" : "Host"}:</span> {blackPlayer ? formatPlayerLabel(blackPlayer) : "Waiting for player"}</div>
        <div><span style={{ color: "#8f7546" }}>{hasSeats ? "White" : "Guest"}:</span> {whitePlayer ? formatPlayerLabel(whitePlayer) : "Waiting for player"}</div>
        <div><span style={{ color: "#8f7546" }}>Clock:</span> {formatClockSetting(roomSummary?.config || game?.config || {})}</div>
      </div>
      <div style={{ fontFamily: "'DM Sans'", fontSize: 11, color: "#dcc798", lineHeight: 1.7 }}>
        <span style={{ color: "#8f7546" }}>Spectators:</span> {spectators.length ? spectators.map((spectator) => formatPlayerLabel(spectator)).join(" . ") : "None yet"}
      </div>
    </div>
  );
}

function requestStateForRole(request, role) {
  if (!request || !role) return "idle";
  const otherRole = role === "host" ? "guest" : "host";
  if (request[role] && request[otherRole]) return "accepted";
  if (request[otherRole] && !request[role]) return "incoming";
  if (request[role] && !request[otherRole]) return "outgoing";
  return "idle";
}

function negotiationButtonLabel(kind, requestState) {
  if (requestState === "incoming") {
    if (kind === "draw") return "Accept Draw";
    if (kind === "takeback") return "Accept Takeback";
    return "Accept Rematch";
  }
  if (requestState === "outgoing") {
    return "Waiting...";
  }
  if (kind === "draw") return "Offer Draw";
  if (kind === "takeback") return "Request Takeback";
  return "Rematch";
}

function RoomActionPanel({ session, onRoomAction }) {
  if (!session.role) {
    return (
      <div style={{ padding: "14px 15px", borderRadius: 14, border: "1px solid #211a11", background: "#0f151c", display: "grid", gap: 12 }}>
        <div style={{ fontSize: 20, color: GOLD }}>Room Actions</div>
        <div style={{ fontFamily: "'DM Sans'", fontSize: 11, color: "#d4c08f", lineHeight: 1.8 }}>
          Spectators can follow the board and chat, but draw, takeback, and rematch controls stay with the two players.
        </div>
      </div>
    );
  }

  const role = session.role;
  const drawState = requestStateForRole(session.requests?.draw, role);
  const takebackState = requestStateForRole(session.requests?.takeback, role);
  const rematchState = requestStateForRole(session.requests?.rematch, role);
  const canDrawOrTakeback = session.phase === "active";
  const canRematch = session.phase === "finished";

  const renderActionRow = (kind, requestState, enabled) => (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
      <button
        className="tb-btn"
        onClick={() => onRoomAction(kind, "request")}
        disabled={!enabled || requestState === "outgoing"}
        style={actionBtn("ghost", !enabled || requestState === "outgoing")}
      >
        {negotiationButtonLabel(kind, requestState)}
      </button>
      {requestState === "incoming" ? <button className="tb-btn" onClick={() => onRoomAction(kind, "decline")} style={actionBtn("ghost", false)}>Decline</button> : null}
      {requestState === "outgoing" ? <button className="tb-btn" onClick={() => onRoomAction(kind, "cancel")} style={actionBtn("ghost", false)}>Cancel</button> : null}
    </div>
  );

  return (
    <div style={{ padding: "14px 15px", borderRadius: 14, border: "1px solid #211a11", background: "#0f151c", display: "grid", gap: 12 }}>
      <div style={{ fontSize: 20, color: GOLD }}>Room Actions</div>
      <div style={{ fontFamily: "'DM Sans'", fontSize: 11, color: "#d4c08f", lineHeight: 1.7, display: "grid", gap: 10 }}>
        <div>
          <div style={{ color: "#8f7546", marginBottom: 6 }}>Draw</div>
          {renderActionRow("draw", drawState, canDrawOrTakeback)}
        </div>
        <div>
          <div style={{ color: "#8f7546", marginBottom: 6 }}>Takeback</div>
          {renderActionRow("takeback", takebackState, canDrawOrTakeback)}
        </div>
        <div>
          <div style={{ color: "#8f7546", marginBottom: 6 }}>Rematch</div>
          {renderActionRow("rematch", rematchState, canRematch)}
        </div>
      </div>
    </div>
  );
}

function ChatPanel({ messages, onSend }) {
  const [draft, setDraft] = useState("");
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <div style={{ padding: "14px 15px", borderRadius: 14, border: "1px solid #211a11", background: "#0f151c", display: "grid", gap: 10 }}>
      <div style={{ fontSize: 20, color: GOLD }}>Chat</div>
      <div ref={scrollRef} style={{ maxHeight: 220, overflowY: "auto", display: "grid", gap: 8, paddingRight: 4 }}>
        {!messages?.length ? <div style={{ fontFamily: "'DM Sans'", fontSize: 11, color: "#7c6841" }}>No messages yet.</div> : messages.map((message) => (
          <div key={message.id} style={{ padding: "9px 10px", borderRadius: 12, border: "1px solid #20170f", background: "#111820" }}>
            <div style={{ fontFamily: "'DM Sans'", fontSize: 10, color: "#8f7546", marginBottom: 4 }}>
              {formatPlayerLabel(message.sender)} {message.createdAt ? `| ${new Date(message.createdAt).toLocaleTimeString()}` : ""}
            </div>
            <div style={{ fontFamily: "'DM Sans'", fontSize: 12, color: "#e1d1ae", lineHeight: 1.6 }}>{message.text}</div>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && draft.trim()) {
              onSend(draft);
              setDraft("");
            }
          }}
          placeholder="Send a message"
          style={{ flex: "1 1 220px", minWidth: 0, padding: "10px 11px", borderRadius: 10, border: "1px solid #2e2818", background: "#0c1117", color: "#dcc798", fontFamily: "'DM Sans'", fontSize: 12 }}
        />
        <button
          className="tb-btn"
          onClick={() => {
            if (!draft.trim()) return;
            onSend(draft);
            setDraft("");
          }}
          disabled={!draft.trim()}
          style={actionBtn("ghost", !draft.trim())}
        >
          Send
        </button>
      </div>
    </div>
  );
}

function jumpToMainlineEnd(record, nodeId) {
  let cursor = nodeId;
  while (getChildNodes(record, cursor).length) {
    cursor = getChildNodes(record, cursor)[0].id;
  }
  return cursor;
}

function getNearestBranchGroup(record, nodeId) {
  const path = getNodePath(record, nodeId);
  for (let index = path.length - 1; index > 0; index -= 1) {
    const currentId = path[index];
    const parentId = path[index - 1];
    const siblings = getChildNodes(record, parentId);
    if (siblings.length > 1) {
      return {
        groupIds: siblings.map((node) => node.id),
        currentId,
      };
    }
  }

  const children = getChildNodes(record, nodeId);
  if (children.length > 1) {
    return {
      groupIds: children.map((node) => node.id),
      currentId: children[0].id,
    };
  }

  return null;
}

function cycleBranchNode(record, nodeId, direction = 1) {
  const group = getNearestBranchGroup(record, nodeId);
  if (!group || group.groupIds.length < 2) {
    return null;
  }
  const index = group.groupIds.indexOf(group.currentId);
  const nextIndex = index === -1
    ? 0
    : (index + direction + group.groupIds.length) % group.groupIds.length;
  return group.groupIds[nextIndex];
}

function buildBranchMapLayout(record) {
  const positions = {};
  const edges = [];
  let nextRow = 1;
  let maxDepth = 0;
  let maxRow = 0;

  const walk = (nodeId, depth, row) => {
    positions[nodeId] = { depth, row };
    maxDepth = Math.max(maxDepth, depth);
    maxRow = Math.max(maxRow, row);
    const children = getChildNodes(record, nodeId);
    if (!children.length) return;

    const [mainChild, ...branchChildren] = children;
    if (mainChild) {
      edges.push({ from: nodeId, to: mainChild.id, main: true });
      walk(mainChild.id, depth + 1, row);
    }
    branchChildren.forEach((child) => {
      const branchRow = nextRow;
      nextRow += 1;
      edges.push({ from: nodeId, to: child.id, main: false });
      walk(child.id, depth + 1, branchRow);
    });
  };

  walk(record.rootId, 0, 0);
  return {
    positions,
    edges,
    width: maxDepth + 1,
    height: maxRow + 1,
  };
}

function overlayStyle() {
  return {
    position: "fixed",
    inset: 0,
    background: "rgba(8,10,14,0.72)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
    zIndex: 90,
  };
}

function modalCardStyle(width = 560) {
  return {
    width: `min(100%, ${width}px)`,
    borderRadius: 18,
    border: "1px solid #1f1810",
    background: "#111820",
    boxShadow: "0 20px 80px rgba(0,0,0,0.45)",
    padding: "18px 20px",
  };
}

function EndgameModal({ open, title, sub, details = null, actions, onClose }) {
  if (!open) return null;
  return (
    <div style={overlayStyle()}>
      <div style={modalCardStyle(540)}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "start" }}>
          <div style={{ fontSize: 28, color: GOLD }}>{title}</div>
          {onClose ? <button className="tb-btn" onClick={onClose} style={actionBtn("ghost", false)}>Close</button> : null}
        </div>
        <div style={{ fontFamily: "'DM Sans'", fontSize: 12, color: "#b59b67", lineHeight: 1.7, marginTop: 8 }}>{sub}</div>
        {details ? <div style={{ marginTop: 16 }}>{details}</div> : null}
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 18 }}>
          {actions.map((action) => (
            <button
              key={action.label}
              className={action.kind === "ghost" ? "tb-btn" : "ng-btn"}
              onClick={action.onClick}
              disabled={action.disabled}
              style={action.kind === "ghost" ? actionBtn("ghost", !!action.disabled) : actionBtn("solid", !!action.disabled)}
            >
              {action.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function displayRatingDelta(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || !parsed) return "0";
  const rounded = Math.round(parsed);
  return `${rounded > 0 ? "+" : ""}${rounded}`;
}

function formatTemperature(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(2) : "1.00";
}

function EndgameRatingPanel({ session }) {
  const role = session.role;
  if (!role) {
    return (
      <div style={{ padding: "12px 14px", borderRadius: 14, border: "1px solid #241a11", background: "#0d1319", fontFamily: "'DM Sans'", fontSize: 12, lineHeight: 1.7, color: "#ccb17a" }}>
        Spectators do not gain or lose rating from the games they watch.
      </div>
    );
  }
  const ratingSummary = session.game?.rating || null;
  const rating = role ? session.game?.rating?.[role] : null;
  const opponentRole = role === "host" ? "guest" : role === "guest" ? "host" : null;
  const opponentRating = opponentRole ? session.game?.rating?.[opponentRole] : null;
  const selfPlayer = role ? session.game?.players?.[role] : null;
  const opponentPlayer = opponentRole ? session.game?.players?.[opponentRole] : null;

  if (!ratingSummary?.rated || !rating) {
    return (
      <div style={{ padding: "12px 14px", borderRadius: 14, border: "1px solid #241a11", background: "#0d1319", fontFamily: "'DM Sans'", fontSize: 12, lineHeight: 1.7, color: "#ccb17a" }}>
        This game did not affect rating. Rated updates only apply when two registered accounts finish an online game.
      </div>
    );
  }

  const positive = (rating.delta || 0) >= 0;
  return (
    <div style={{ display: "grid", gap: 10 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10 }}>
        <div style={{ padding: "12px 14px", borderRadius: 14, border: `1px solid ${positive ? "#335a34" : "#5f2d2d"}`, background: positive ? "rgba(100,176,106,0.12)" : "rgba(196,104,104,0.1)" }}>
          <div style={{ fontFamily: "'DM Sans'", fontSize: 10, letterSpacing: 2, textTransform: "uppercase", color: positive ? "#a9e2af" : "#f0a8a8", marginBottom: 8 }}>Your Rated Result</div>
          <div style={{ fontSize: 24, color: "#f1dbab" }}>{displayRatingDelta(rating.delta)}</div>
          <div style={{ fontFamily: "'DM Sans'", fontSize: 11, lineHeight: 1.8, color: "#d7c395", marginTop: 4 }}>
            <div>{selfPlayer?.displayName || "You"}: R{Math.round(rating.before)} {"->"} R{Math.round(rating.after)}</div>
            <div>Temperature: x{formatTemperature(rating.temperatureBefore)} {"->"} x{formatTemperature(rating.temperatureAfter)}</div>
          </div>
        </div>
        <div style={{ padding: "12px 14px", borderRadius: 14, border: "1px solid #241a11", background: "#0d1319" }}>
          <div style={{ fontFamily: "'DM Sans'", fontSize: 10, letterSpacing: 2, textTransform: "uppercase", color: "#8fb3d2", marginBottom: 8 }}>Opponent Snapshot</div>
          <div style={{ fontSize: 20, color: "#f1dbab" }}>{opponentPlayer?.displayName || "Opponent"}</div>
          <div style={{ fontFamily: "'DM Sans'", fontSize: 11, lineHeight: 1.8, color: "#d7c395", marginTop: 4 }}>
            <div>{opponentPlayer?.loginId ? `@${opponentPlayer.loginId}` : "Guest / hidden"}</div>
            <div>{opponentRating ? `R${Math.round(opponentRating.before)} -> R${Math.round(opponentRating.after)} (${displayRatingDelta(opponentRating.delta)})` : "Unrated opponent result"}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ReviewModal({ open, title, sub, width = 620, children, onClose }) {
  if (!open) return null;
  return (
    <div style={overlayStyle()}>
      <div style={modalCardStyle(width)}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "start", marginBottom: 14 }}>
          <div>
            <div style={{ fontSize: 28, color: GOLD }}>{title}</div>
            {sub ? <div style={{ fontFamily: "'DM Sans'", fontSize: 12, color: "#b59b67", lineHeight: 1.7, marginTop: 8 }}>{sub}</div> : null}
          </div>
          {onClose ? <button className="tb-btn" onClick={onClose} style={actionBtn("ghost", false)}>Close</button> : null}
        </div>
        {children}
      </div>
    </div>
  );
}

function ReviewToast({ message }) {
  if (!message) return null;
  return (
    <div style={{ position: "fixed", right: 20, bottom: 20, zIndex: 110, padding: "12px 14px", maxWidth: 360, borderRadius: 14, border: "1px solid #3f2f18", background: "rgba(18,16,12,0.96)", color: "#e4c88f", fontFamily: "'DM Sans'", fontSize: 12, lineHeight: 1.6, boxShadow: "0 18px 50px rgba(0,0,0,0.4)" }}>
      {message}
    </div>
  );
}

function ReviewMoveList({ record, currentNodeId, onJump }) {
  return (
    <div style={{ borderRadius: 14, border: "1px solid #20170f", overflow: "hidden", background: "#0e141b" }}>
      <div style={{ display: "grid", gridTemplateColumns: "56px minmax(0, 1fr) minmax(0, 1fr)", gap: 0, borderBottom: "1px solid #241b11", background: "#121922", fontFamily: "'DM Sans'", fontSize: 10, letterSpacing: 2, textTransform: "uppercase", color: "#8d7444" }}>
        <div style={{ padding: "10px 8px" }}>Move</div>
        <div style={{ padding: "10px 10px", borderLeft: "1px solid #241b11" }}>Black</div>
        <div style={{ padding: "10px 10px", borderLeft: "1px solid #241b11" }}>White</div>
      </div>
      <div style={{ maxHeight: 260, overflowY: "auto" }}>
        {Array.from({ length: Math.ceil((getNodePath(record, currentNodeId).length - 1) / 2) }, (_, rowIndex) => {
          const path = getNodePath(record, currentNodeId);
          const blackIndex = rowIndex * 2 + 1;
          const whiteIndex = rowIndex * 2 + 2;
          const blackNodeId = path[blackIndex];
          const whiteNodeId = path[whiteIndex];
          const blackNode = blackNodeId ? record.nodes[blackNodeId] : null;
          const whiteNode = whiteNodeId ? record.nodes[whiteNodeId] : null;
          return (
            <div key={`row-${rowIndex}`} style={{ display: "grid", gridTemplateColumns: "56px minmax(0, 1fr) minmax(0, 1fr)", borderBottom: rowIndex === Math.ceil((path.length - 1) / 2) - 1 ? "none" : "1px solid #19130c" }}>
              <div style={{ padding: "10px 8px", fontFamily: "'DM Sans'", fontSize: 11, color: "#9b8253" }}>{rowIndex + 1}</div>
              <button className="ghost-btn" onClick={() => blackNodeId && onJump(blackNodeId)} disabled={!blackNodeId} style={{ ...ghostButton(!blackNodeId), border: "none", borderLeft: "1px solid #241b11", borderRadius: 0, textAlign: "left", padding: "10px 10px", background: currentNodeId === blackNodeId ? "rgba(232,201,106,0.12)" : "transparent", color: blackNode ? "#e8dcc8" : "#57472b" }}>{blackNode ? blackNode.move.notation : ""}</button>
              <button className="ghost-btn" onClick={() => whiteNodeId && onJump(whiteNodeId)} disabled={!whiteNodeId} style={{ ...ghostButton(!whiteNodeId), border: "none", borderLeft: "1px solid #241b11", borderRadius: 0, textAlign: "left", padding: "10px 10px", background: currentNodeId === whiteNodeId ? "rgba(232,201,106,0.12)" : "transparent", color: whiteNode ? "#e8dcc8" : "#57472b" }}>{whiteNode ? whiteNode.move.notation : ""}</button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ReviewBranchPanel({ record, currentNodeId, onJump }) {
  const activePathIds = new Set(getNodePath(record, currentNodeId));
  const viewportWidth = 320;
  const viewportHeight = 220;
  const gapX = 48;
  const gapY = 20;
  const padding = 28;
  const layout = buildBranchMapLayout(record);
  const pixelPositions = Object.fromEntries(Object.entries(layout.positions).map(([id, point]) => [
    id,
    {
      x: padding + point.depth * gapX,
      y: padding + point.row * gapY,
    },
  ]));
  const contentWidth = Math.max(viewportWidth, padding * 2 + Math.max(0, layout.width - 1) * gapX + 40);
  const contentHeight = Math.max(viewportHeight, padding * 2 + Math.max(0, layout.height - 1) * gapY + 40);
  const clampOffset = (candidate) => ({
    x: Math.min(padding, Math.max(viewportWidth - contentWidth - padding, candidate.x)),
    y: Math.min(padding, Math.max(viewportHeight - contentHeight - padding, candidate.y)),
  });
  const [offset, setOffset] = useState(() => clampOffset({ x: 22, y: 22 }));
  const dragRef = useRef(null);

  useEffect(() => {
    const target = pixelPositions[currentNodeId] || pixelPositions[record.rootId] || { x: padding, y: padding };
    setOffset(clampOffset({
      x: viewportWidth / 2 - target.x,
      y: viewportHeight / 2 - target.y,
    }));
  }, [record, currentNodeId]);

  return (
    <div style={{ display: "grid", gap: 10 }}>
      <div style={{ fontFamily: "'DM Sans'", fontSize: 11, color: "#8c7344", lineHeight: 1.7 }}>
        Drag to pan the branch map. The main line stays horizontal, and you can click any node to jump straight to that position.
      </div>
      <div
        onPointerDown={(event) => {
          dragRef.current = {
            pointerId: event.pointerId,
            x: event.clientX,
            y: event.clientY,
          };
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          if (!dragRef.current || dragRef.current.pointerId !== event.pointerId) {
            return;
          }
          const deltaX = event.clientX - dragRef.current.x;
          const deltaY = event.clientY - dragRef.current.y;
          dragRef.current = {
            pointerId: event.pointerId,
            x: event.clientX,
            y: event.clientY,
          };
          setOffset((prev) => clampOffset({ x: prev.x + deltaX, y: prev.y + deltaY }));
        }}
        onPointerUp={(event) => {
          if (dragRef.current?.pointerId === event.pointerId) {
            dragRef.current = null;
            event.currentTarget.releasePointerCapture(event.pointerId);
          }
        }}
        onPointerCancel={() => {
          dragRef.current = null;
        }}
        onWheel={(event) => {
          event.preventDefault();
          setOffset((prev) => clampOffset({
            x: prev.x - event.deltaX,
            y: prev.y - event.deltaY,
          }));
        }}
        style={{
          width: "100%",
          height: viewportHeight,
          overflow: "hidden",
          borderRadius: 16,
          border: "1px solid #20170f",
          background: "radial-gradient(circle at top, rgba(34,42,52,0.55), #0e141b 55%)",
          position: "relative",
          cursor: dragRef.current ? "grabbing" : "grab",
          touchAction: "none",
        }}
      >
        <div
          style={{
            position: "absolute",
            inset: 0,
            backgroundImage: "radial-gradient(circle, rgba(232,201,106,0.09) 1px, transparent 1px)",
            backgroundSize: "22px 22px",
            opacity: 0.45,
          }}
        />
        <div style={{ position: "absolute", width: contentWidth, height: contentHeight, transform: `translate(${offset.x}px, ${offset.y}px)` }}>
          <svg width={contentWidth} height={contentHeight} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
            {layout.edges.map((edge) => {
              const from = pixelPositions[edge.from];
              const to = pixelPositions[edge.to];
              const onActivePath = activePathIds.has(edge.from) && activePathIds.has(edge.to);
              return (
                <path
                  key={`${edge.from}-${edge.to}`}
                  d={`M ${from.x} ${from.y} H ${to.x} V ${to.y}`}
                  stroke={onActivePath ? (edge.main ? "#d1ae64" : "#8cb5d6") : edge.main ? "#4c3920" : "#233445"}
                  strokeWidth={onActivePath ? 2.4 : 1.3}
                  strokeDasharray={edge.main ? undefined : "3 5"}
                  opacity={onActivePath ? 0.95 : 0.75}
                  fill="none"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              );
            })}
          </svg>
          {Object.keys(layout.positions).map((nodeId) => {
            const node = record.nodes[nodeId];
            const point = pixelPositions[nodeId];
            const isActive = nodeId === currentNodeId;
            const isOnActivePath = activePathIds.has(nodeId);
            const size = isActive ? 18 : isOnActivePath ? 12 : 9;
            const color = nodeId === record.rootId ? GOLD : node.move.player === "B" ? "#3f3f46" : "#ddd2bc";
            return (
              <button
                key={nodeId}
                className="ghost-btn"
                onClick={() => onJump(nodeId)}
                onPointerDown={(event) => {
                  event.stopPropagation();
                }}
                title={nodeId === record.rootId ? "Start" : `${node.move.player}@${node.move.notation}`}
                style={{
                  position: "absolute",
                  left: point.x - Math.max(size, 20) / 2,
                  top: point.y - Math.max(size, 20) / 2,
                  width: Math.max(size, 20),
                  height: Math.max(size, 20),
                  padding: 0,
                  borderRadius: 999,
                  border: "none",
                  background: "transparent",
                  boxShadow: isActive ? "0 0 0 5px rgba(232,201,106,0.18)" : isOnActivePath ? "0 0 0 3px rgba(232,201,106,0.08)" : "none",
                  cursor: "pointer",
                  display: "grid",
                  placeItems: "center",
                }}
              >
                <span
                  style={{
                    display: "block",
                    width: size,
                    height: size,
                    borderRadius: 999,
                    border: isActive ? "2px solid #f1d58d" : isOnActivePath ? "1px solid #b48b3f" : "1px solid #5f4b2c",
                    background: color,
                  }}
                />
              </button>
            );
          })}
        </div>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center", flexWrap: "wrap", fontFamily: "'DM Sans'", fontSize: 11, color: "#a98f5e" }}>
        <div>Nodes: {Object.keys(layout.positions).length} | Rows: {layout.height} | Depth: {layout.width}</div>
        <div>{currentNodeId === record.rootId ? "Start" : `${record.nodes[currentNodeId].move.player}@${record.nodes[currentNodeId].move.notation}`}</div>
      </div>
    </div>
  );
}

export function LocalGame({ config, onMenu, onSaveRecord }) {
  const [state, setState] = useState(() => createMatchState(config));
  const [history, setHistory] = useState([]);
  const [moves, setMoves] = useState([]);
  const [annotationResetToken, setAnnotationResetToken] = useState(0);

  useEffect(() => {
    if (config.baseSeconds === null || state.result) return undefined;
    const id = setInterval(() => setState((prev) => tickClock(prev, config)), 1000);
    return () => clearInterval(id);
  }, [config, state.result]);

  const place = (row, col) => {
    const next = applyMove(state, config, row, col);
    if (!next) return;
    setHistory((prev) => [...prev, cloneState(state)]);
    setMoves((prev) => [...prev, { row, col, player: state.turn, ply: prev.length + 1, notation: moveToNotation(row, col) }]);
    setState(next);
  };

  const takeback = () => {
    if (!history.length) return;
    setState(history[history.length - 1]);
    setHistory((prev) => prev.slice(0, -1));
    setMoves((prev) => prev.slice(0, -1));
  };

  return <Shell config={config} state={state} active={state.result ? null : state.turn} canPlace={!state.result} onPlace={place} onBack={onMenu} backLabel="<- Hall" rightLabel="Local" status={<Status state={state} message={`${pName(state.turn)}'s turn`} />} controls={<><button className="tb-btn" onClick={takeback} disabled={!history.length} style={actionBtn("ghost", !history.length)}>Takeback</button><button className="tb-btn" onClick={() => setAnnotationResetToken((token) => token + 1)} style={actionBtn("ghost", false)}>Clear Marks</button><button className="tb-btn" onClick={() => onSaveRecord({ config, moves, state })} disabled={!moves.length} style={actionBtn("ghost", !moves.length)}>Save Record</button><button className="ng-btn" onClick={onMenu} style={actionBtn("solid")}>Leave Practice</button></>} annotationScopeKey={`local-${config.boardSize}`} annotationResetToken={annotationResetToken} />;
}

export function OnlineGame({ session, shareLink, inviteCopied, onCopyInvite, onMove, onBackToHall, onLeave, onRematch, onReview, onRoomAction, onSendChat }) {
  const config = session.config;
  const state = session.gameState || createMatchState(config);
  const canPlace = session.phase === "active" && canRoleMove(session.role, state, session.game);
  const requested = session.role ? session.rematch?.[session.role] : false;
  const rematchState = requestStateForRole(session.requests?.rematch, session.role);
  const [resultsOpen, setResultsOpen] = useState(session.phase === "finished" && !!state.result);
  const [annotationResetToken, setAnnotationResetToken] = useState(0);
  const resultKey = `${session.gameId || session.game?.id || "game"}:${session.phase}:${state.result?.msg || ""}`;

  useEffect(() => {
    if (session.phase === "finished" && state.result) {
      setResultsOpen(true);
    }
  }, [resultKey]);

  useEffect(() => {
    setAnnotationResetToken(0);
  }, [session.gameId, session.roomId]);

  let message = session.notice || "";
  let sub = session.lastError || "";
  const roomLine = session.roomId ? `Room ${session.roomId}${session.gameIndex ? ` - Game ${session.gameIndex}` : ""}` : "Creating room...";

  if (!state.result) {
    if (session.phase === "waiting") sub = session.lastError || (session.mode === "host" ? `${roomLine}. Share this code or invite link with your opponent.` : `${roomLine}. Waiting for the host to finish setup.`);
    if (session.phase === "connecting") sub = session.lastError || "Opening the room over HTTP.";
    if (session.phase === "active") {
      message = `${pName(state.turn)}'s turn`;
      sub = session.lastError || `${roomLine}. ${session.mode === "spectate" ? "Watching live." : canPlace ? "Your move." : "Opponent's move."}`;
    }
  } else if (requested) {
    sub = session.lastError || `${roomLine}. Rematch requested. Waiting for the other player.`;
  } else if (session.phase === "finished") {
    sub = session.lastError || `${roomLine}. Rematch keeps the same room settings and players.`;
  }

  return (
    <>
      <Shell
        config={config}
        state={state}
        active={session.phase === "active" && !state.result ? state.turn : null}
        canPlace={canPlace}
        onPlace={onMove}
        onBack={onBackToHall}
        backLabel="<- Hall"
        rightLabel={session.roomId ? `${roleLabel(session.role, session.mode, session.game)} | ${session.roomId}${session.gameIndex ? ` | G${session.gameIndex}` : ""}` : roleLabel(session.role, session.mode, session.game)}
        status={<Status state={state} message={message} sub={sub} />}
        banner={<>{session.mode === "host" && session.roomId ? <SharePanel link={shareLink} copied={inviteCopied} onCopy={onCopyInvite} /> : null}<PlayerRosterPanel roomSummary={session.roomSummary} game={session.game} /></>}
        annotationScopeKey={session.gameId || session.game?.id || session.roomId || "room"}
        annotationResetToken={annotationResetToken}
        controls={
          <>
            {session.phase === "finished" && state.result ? <button className="tb-btn" onClick={() => setResultsOpen((open) => !open)} style={actionBtn("ghost", false)}>{resultsOpen ? "Hide Results" : "Show Results"}</button> : null}
            <button className="tb-btn" onClick={() => setAnnotationResetToken((token) => token + 1)} style={actionBtn("ghost", false)}>Clear Marks</button>
            <button className="tb-btn" onClick={onBackToHall} style={actionBtn("ghost", false)}>Back To Hall</button>
            <button className="ng-btn" onClick={onLeave} style={actionBtn("solid")}>Leave Room</button>
          </>
        }
        footerPanels={
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 14 }}>
            <RoomActionPanel session={session} onRoomAction={onRoomAction} />
            <ChatPanel messages={session.chatMessages || []} onSend={onSendChat} />
          </div>
        }
      />
      <EndgameModal
        open={session.phase === "finished" && !!state.result && resultsOpen}
        title="Game Finished"
        sub={session.lastError || `${roomLine}. The record was saved automatically, and you can review it before deciding whether to rematch.`}
        details={<EndgameRatingPanel session={session} />}
        onClose={() => setResultsOpen(false)}
        actions={[
          { label: "Review", kind: "solid", onClick: onReview, disabled: false },
          session.role ? { label: rematchState === "incoming" ? "Accept Rematch" : requested ? "Waiting..." : "Rematch", kind: "ghost", onClick: onRematch, disabled: rematchState === "outgoing" || requested } : null,
          { label: "Back To Hall", kind: "ghost", onClick: onBackToHall, disabled: false },
          { label: "Leave Room", kind: "ghost", onClick: onLeave, disabled: false },
        ].filter(Boolean)}
      />
    </>
  );
}

export function ReviewGame({ record, currentNodeId, onBack, onChangeRecord, onSaveRecord }) {
  const [activeNodeId, setActiveNodeId] = useState(() => currentNodeId || findDeepestMainlineNode(record));
  const [feedback, setFeedback] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState("");
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveTitle, setSaveTitle] = useState(record.meta?.title || "");
  const [annotationResetToken, setAnnotationResetToken] = useState(0);

  useEffect(() => {
    if (!feedback) return undefined;
    const id = setTimeout(() => setFeedback(""), 2200);
    return () => clearTimeout(id);
  }, [feedback]);

  useEffect(() => {
    setActiveNodeId(currentNodeId || findDeepestMainlineNode(record));
    setSaveTitle(record.meta?.title || "");
    setAnnotationResetToken(0);
  }, [record, currentNodeId]);

  useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.target && ["INPUT", "TEXTAREA"].includes(event.target.tagName)) {
        return;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        const path = getNodePath(record, activeNodeId);
        if (path.length > 1) {
          setActiveNodeId(path[path.length - 2]);
        }
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        const children = getChildNodes(record, activeNodeId);
        if (children.length) {
          setActiveNodeId(children[0].id);
        }
      }
      if (event.key === "Home") {
        event.preventDefault();
        setActiveNodeId(record.rootId);
      }
      if (event.key === "End") {
        event.preventDefault();
        setActiveNodeId(jumpToMainlineEnd(record, activeNodeId));
      }
      if (event.key === "ArrowUp" || event.key === "PageUp") {
        const previousBranch = cycleBranchNode(record, activeNodeId, -1);
        if (previousBranch) {
          event.preventDefault();
          setActiveNodeId(previousBranch);
        }
      }
      if (event.key === "ArrowDown" || event.key === "PageDown") {
        const nextBranch = cycleBranchNode(record, activeNodeId, 1);
        if (nextBranch) {
          event.preventDefault();
          setActiveNodeId(nextBranch);
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [record, activeNodeId]);

  const replay = replayRecord(record, activeNodeId);
  const path = getNodePath(record, activeNodeId);
  const parentId = path.length > 1 ? path[path.length - 2] : record.rootId;
  const canBranch = !replay.state.result;
  const timeline = getTimeline(record, activeNodeId);
  const previousBranchNodeId = cycleBranchNode(record, activeNodeId, -1);
  const nextBranchNodeId = cycleBranchNode(record, activeNodeId, 1);

  const persistRecord = async (nextRecord, message, nextNodeId = activeNodeId) => {
    const saved = await onSaveRecord(nextRecord);
    if (saved) {
      onChangeRecord(saved, nextNodeId);
    }
    if (message) {
      setFeedback(message);
    }
    return saved || nextRecord;
  };

  const handleAddVariation = (row, col) => {
    try {
      const next = addVariation(record, activeNodeId, row, col);
      onChangeRecord(next.record, next.nodeId);
      void persistRecord(next.record, `Added branch move ${moveToNotation(row, col)}.`, next.nodeId);
    } catch (error) {
      // Keep the review screen lightweight: illegal branch placements simply do nothing.
    }
  };

  const handleCopyExport = async () => {
    const text = exportRecordText(record);
    try {
      const copied = await copyTextToClipboard(text);
      if (!copied) throw new Error("Copy blocked");
      setFeedback("Record text copied to the clipboard.");
    } catch {
      setFeedback("Could not copy the record text to the clipboard.");
    }
  };

  const handleImport = async () => {
    try {
      const nextRecord = importRecordText(importText);
      const nextNodeId = findDeepestMainlineNode(nextRecord);
      onChangeRecord(nextRecord, nextNodeId);
      await persistRecord(nextRecord, "Imported record text into the archive.", nextNodeId);
      setImportOpen(false);
      setImportText("");
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : "Could not import that record text.");
    }
  };

  const handleSaveArchive = async () => {
    const nextRecord = {
      ...record,
      meta: {
        ...(record.meta || {}),
        title: String(saveTitle || "").trim() || record.meta?.title || "Untitled Record",
      },
    };
    const saved = await persistRecord(nextRecord, "Record archive saved.");
    onChangeRecord(saved, activeNodeId);
    setSaveOpen(false);
  };

  const handlePromoteBranch = async () => {
    const promoted = promoteNodePathToMain(record, activeNodeId);
    onChangeRecord(promoted, activeNodeId);
    await persistRecord(promoted, "Current branch promoted to the main line.");
  };

  return (
    <div style={{ ...shellStyle, paddingTop: 18 }}>
      <style>{BASE_CSS}</style>
      <ReviewToast message={feedback} />
      <div style={{ width: "100%", maxWidth: 1200, display: "grid", gap: 18 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <button className="menu-btn" onClick={onBack} style={{ background: "transparent", border: "1px solid #2a2018", color: "#5a4a28", fontFamily: "'DM Sans'", fontSize: 9, letterSpacing: 2, textTransform: "uppercase", padding: "6px 13px", borderRadius: 4, cursor: "pointer" }}>{"<- Back"}</button>
          <div style={{ flex: "1 1 240px", fontSize: 26, color: GOLD }}>{record.meta?.title || "Review"}</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button className="tb-btn" onClick={handleCopyExport} style={actionBtn("ghost", false)}>Export</button>
            <button className="tb-btn" onClick={() => setImportOpen(true)} style={actionBtn("ghost", false)}>Import</button>
            <button className="tb-btn" onClick={() => {
              setSaveTitle(record.meta?.title || "");
              setSaveOpen(true);
            }} style={actionBtn("ghost", false)}>Save Archive</button>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(280px, 360px)", gap: 18, alignItems: "start" }}>
          <div style={{ borderRadius: 18, border: "1px solid #1c1810", background: "#111820", padding: 18 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
              <div style={{ fontFamily: "'DM Sans'", fontSize: 11, color: "#b99b64", lineHeight: 1.7 }}>
                <div>{record.config.boardSize} x {record.config.boardSize} | {formatClockSetting(record.config)}</div>
                <div>{record.meta?.roomId ? `Room ${record.meta.roomId}` : "Local record"}{record.meta?.gameIndex ? ` | Game ${record.meta.gameIndex}` : ""}</div>
              </div>
              <div style={{ fontFamily: "'DM Sans'", fontSize: 11, color: "#8c7344" }}>
                {canBranch ? "Click an empty intersection to branch from the current position." : "This line has already ended. Move backward to branch earlier."}
              </div>
            </div>
            <Board config={record.config} state={replay.state} canPlace={canBranch} onPlace={handleAddVariation} annotationScopeKey={record.id || record.meta?.gameId || record.meta?.title || "review"} annotationResetToken={annotationResetToken} />
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center", marginTop: 14 }}>
              <button className="tb-btn" onClick={() => setActiveNodeId(record.rootId)} style={actionBtn("ghost", false)}>Start</button>
              <button className="tb-btn" onClick={() => {
                if (path.length > 1) setActiveNodeId(path[path.length - 2]);
              }} style={actionBtn("ghost", path.length <= 1)}>Prev</button>
              <button className="tb-btn" onClick={() => {
                const children = getChildNodes(record, activeNodeId);
                if (children.length) setActiveNodeId(children[0].id);
              }} style={actionBtn("ghost", !getChildNodes(record, activeNodeId).length)}>Next</button>
              <button className="tb-btn" onClick={() => previousBranchNodeId && setActiveNodeId(previousBranchNodeId)} disabled={!previousBranchNodeId} style={actionBtn("ghost", !previousBranchNodeId)}>Prev Branch</button>
              <button className="tb-btn" onClick={() => nextBranchNodeId && setActiveNodeId(nextBranchNodeId)} disabled={!nextBranchNodeId} style={actionBtn("ghost", !nextBranchNodeId)}>Next Branch</button>
              <button className="tb-btn" onClick={() => setActiveNodeId(jumpToMainlineEnd(record, activeNodeId))} style={actionBtn("ghost", false)}>End</button>
              <button className="tb-btn" onClick={() => setAnnotationResetToken((token) => token + 1)} style={actionBtn("ghost", false)}>Clear Marks</button>
              <button className="tb-btn" onClick={handlePromoteBranch} disabled={path.length <= 1} style={actionBtn("ghost", path.length <= 1)}>Set As Main</button>
            </div>
          </div>

          <div style={{ display: "grid", gap: 16 }}>
            <div style={{ borderRadius: 18, border: "1px solid #1c1810", background: "#111820", padding: "16px 18px" }}>
              <div style={{ fontSize: 22, color: GOLD, marginBottom: 10 }}>Move Trail</div>
              <ReviewMoveList record={record} currentNodeId={activeNodeId} onJump={setActiveNodeId} />
            </div>
            <div style={{ borderRadius: 18, border: "1px solid #1c1810", background: "#111820", padding: "16px 18px" }}>
              <div style={{ fontSize: 22, color: GOLD, marginBottom: 10 }}>Branches</div>
              <ReviewBranchPanel record={record} currentNodeId={activeNodeId} onJump={setActiveNodeId} />
            </div>
            <div style={{ borderRadius: 18, border: "1px solid #1c1810", background: "#111820", padding: "16px 18px" }}>
              <div style={{ fontSize: 22, color: GOLD, marginBottom: 10 }}>Current Position</div>
              <div style={{ fontFamily: "'DM Sans'", fontSize: 11, color: "#d2bd92", lineHeight: 1.8 }}>
                <div>Node: {activeNodeId === record.rootId ? "Start" : activeNodeId}</div>
                <div>Parent: {parentId === record.rootId ? "Start" : parentId}</div>
                <div>Side to move: {replay.state.result ? "Finished" : pName(replay.state.turn)}</div>
                <div>Total moves on line: {replay.moves.length}</div>
                <div>Visible path nodes: {timeline.length}</div>
                <div>Shortcuts: Left/Right move, Up/Down branch, Home/End jump.</div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <ReviewModal open={importOpen} title="Import Record" sub="Paste Anti-Gomoku PGN text here. The imported tree will replace the current review record." onClose={() => setImportOpen(false)}>
        <div style={{ display: "grid", gap: 12 }}>
          <textarea value={importText} onChange={(event) => setImportText(event.target.value)} placeholder={'[Format "AntiGomokuPGN/1"]'} style={{ minHeight: 260, resize: "vertical", width: "100%", padding: "12px 14px", borderRadius: 12, border: "1px solid #2e2818", background: "#0c1117", color: "#dcc798", fontFamily: "'DM Sans'", fontSize: 12, lineHeight: 1.7 }} />
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button className="ng-btn" onClick={() => { void handleImport(); }} disabled={!importText.trim()} style={actionBtn("solid", !importText.trim())}>Import</button>
            <button className="tb-btn" onClick={() => setImportOpen(false)} style={actionBtn("ghost", false)}>Cancel</button>
          </div>
        </div>
      </ReviewModal>
      <ReviewModal open={saveOpen} title="Save Archive" sub="Give this record a clear name before saving it back into the local archive." onClose={() => setSaveOpen(false)} width={520}>
        <div style={{ display: "grid", gap: 12 }}>
          <input value={saveTitle} onChange={(event) => setSaveTitle(event.target.value)} placeholder="Record title" style={{ width: "100%", padding: "12px 14px", borderRadius: 12, border: "1px solid #2e2818", background: "#0c1117", color: "#dcc798", fontFamily: "'DM Sans'", fontSize: 12 }} />
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button className="ng-btn" onClick={() => { void handleSaveArchive(); }} style={actionBtn("solid", false)}>Save</button>
            <button className="tb-btn" onClick={() => setSaveOpen(false)} style={actionBtn("ghost", false)}>Cancel</button>
          </div>
        </div>
      </ReviewModal>
    </div>
  );
}
