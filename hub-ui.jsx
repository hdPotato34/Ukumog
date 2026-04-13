import { useState } from "react";
import {
  CLOCK_PRESET_OPTIONS,
  COLOR_MODE_OPTIONS,
  CUSTOM_BASE_TIME_OPTIONS,
  GOLD,
  SIZE_OPTIONS,
  formatClockSetting,
  formatColorSetting,
  sanitizeConfig,
} from "./game-core.mjs";
import { normalizeRoomId } from "./online-room.mjs";

const BASE_CSS = `@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;600;700&family=DM+Sans:wght@300;400;500&display=swap');*{box-sizing:border-box;scrollbar-width:thin;scrollbar-color:#7e6840 #111821}html,body{margin:0}button,input{transition:all .15s ease}button,input,textarea{font:inherit}::selection{background:rgba(214,183,114,.24);color:#f5e7c3}::-webkit-scrollbar{width:12px;height:12px}::-webkit-scrollbar-track{background:linear-gradient(180deg,#0f151c,#111922);border-radius:999px}::-webkit-scrollbar-thumb{background:linear-gradient(180deg,#8b7245,#5e4a2b);border:2px solid #111821;border-radius:999px}::-webkit-scrollbar-thumb:hover{background:linear-gradient(180deg,#a48652,#6f5834)}.hub-btn:hover:not(:disabled){filter:brightness(1.08);transform:translateY(-1px)}.ghost-btn:hover:not(:disabled){border-color:#6a5030!important;color:#d8be86!important;background:rgba(214,190,136,.04)}.top-input:focus{outline:none;border-color:#8d713e!important;box-shadow:0 0 0 2px rgba(232,201,106,.08)}`;

const pageStyle = {
  minHeight: "100vh",
  backgroundColor: "#0b1015",
  backgroundImage: "radial-gradient(circle at top left, rgba(182,146,82,0.11), transparent 24%), radial-gradient(circle at top right, rgba(83,109,134,0.12), transparent 22%), linear-gradient(180deg, #0d1218 0%, #0b1015 100%)",
  color: "#e8dcc8",
  fontFamily: "'Cormorant Garamond', Georgia, serif",
  padding: "18px clamp(18px, 3vw, 34px) 28px",
};

function panelStyle() {
  return {
    background: "#111820",
    border: "1px solid #20180f",
    borderRadius: 20,
    padding: "20px 22px",
    boxShadow: "0 22px 80px rgba(0,0,0,0.34)",
  };
}

function titleStyle() {
  return {
    fontSize: 28,
    color: GOLD,
    lineHeight: 1,
  };
}

function labelStyle() {
  return {
    marginBottom: 9,
    fontFamily: "'DM Sans'",
    fontSize: 11,
    letterSpacing: 2.4,
    textTransform: "uppercase",
    color: "#7c6841",
  };
}

function inputStyle() {
  return {
    width: "100%",
    padding: "11px 12px",
    borderRadius: 10,
    border: "1px solid #2e2818",
    background: "#0c1117",
    color: "#dcc798",
    fontFamily: "'DM Sans'",
    fontSize: 13,
  };
}

function solidButton(disabled = false) {
  return {
    padding: "11px 16px",
    borderRadius: 10,
    border: "none",
    background: disabled ? "#40331c" : GOLD,
    color: disabled ? "#8a7447" : "#1a1208",
    fontFamily: "'DM Sans'",
    fontSize: 12,
    letterSpacing: 1.7,
    textTransform: "uppercase",
    cursor: disabled ? "not-allowed" : "pointer",
  };
}

function ghostButton(disabled = false) {
  return {
    padding: "11px 16px",
    borderRadius: 10,
    border: `1px solid ${disabled ? "#221b11" : "#2f2618"}`,
    background: "transparent",
    color: disabled ? "#57472b" : "#d6bd89",
    fontFamily: "'DM Sans'",
    fontSize: 12,
    letterSpacing: 1.7,
    textTransform: "uppercase",
    cursor: disabled ? "not-allowed" : "pointer",
  };
}

function pill(active = false) {
  return {
    padding: "9px 14px",
    borderRadius: 999,
    border: `1px solid ${active ? GOLD : "#302717"}`,
    background: active ? GOLD : "transparent",
    color: active ? "#1a1208" : "#9b8152",
    fontFamily: "'DM Sans'",
    fontSize: 12,
    letterSpacing: 1.6,
    textTransform: "uppercase",
    cursor: "pointer",
  };
}

function infoText(text, color = "#6f5d3b") {
  return <div style={{ fontFamily: "'DM Sans'", fontSize: 12, lineHeight: 1.75, color }}>{text}</div>;
}

function scrollAreaStyle(maxHeight = 480) {
  return {
    maxHeight,
    overflowY: "auto",
    paddingRight: 10,
    display: "flex",
    flexDirection: "column",
    gap: 12,
    scrollbarGutter: "stable",
    overscrollBehavior: "contain",
  };
}

function statTone(kind = "gold") {
  if (kind === "sage") {
    return {
      color: "#d9cfab",
      border: "#314137",
      background: "linear-gradient(180deg, rgba(25,35,31,0.96), rgba(14,20,19,0.98))",
    };
  }
  if (kind === "slate") {
    return {
      color: "#d7d2c4",
      border: "#283646",
      background: "linear-gradient(180deg, rgba(22,29,38,0.96), rgba(12,17,23,0.98))",
    };
  }
  if (kind === "ember") {
    return {
      color: "#e0ccb0",
      border: "#47362a",
      background: "linear-gradient(180deg, rgba(39,28,22,0.96), rgba(16,18,22,0.98))",
    };
  }
  return {
    color: GOLD,
    border: "#2f2618",
    background: "linear-gradient(180deg, rgba(31,24,15,0.97), rgba(12,18,24,0.99))",
  };
}

function statCardStyle({ color = GOLD, background = "linear-gradient(180deg, rgba(31,24,15,0.97), rgba(12,18,24,0.99))", border = "#2f2618" } = {}) {
  return {
    padding: "15px 15px",
    borderRadius: 16,
    border: `1px solid ${border}`,
    background,
    minHeight: 102,
    display: "flex",
    flexDirection: "column",
    justifyContent: "space-between",
    gap: 10,
    boxShadow: "0 16px 34px rgba(0,0,0,0.18)",
    color,
  };
}

function formatOutcome(outcome) {
  if (outcome === "win") return "Win";
  if (outcome === "loss") return "Loss";
  if (outcome === "draw") return "Draw";
  return "Unknown";
}

function formatRoomConfig(config) {
  const cleanConfig = sanitizeConfig(config);
  return `${cleanConfig.boardSize}x${cleanConfig.boardSize} | ${formatClockSetting(cleanConfig)} | ${formatColorSetting(cleanConfig)}`;
}

function formatRatingValue(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.round(parsed) : null;
}

function formatRatingTag(entity, { historical = false } = {}) {
  const rating = historical
    ? formatRatingValue(entity?.ratingBefore ?? entity?.rating)
    : formatRatingValue(entity?.rating);
  return rating === null ? "" : `R${rating}`;
}

function formatIdentityText(entity, { historical = false, includeLogin = true } = {}) {
  if (!entity) return "Unknown";
  const rating = formatRatingTag(entity, { historical });
  return [
    entity.displayName || "Unknown",
    includeLogin && entity.loginId ? `@${entity.loginId}` : "",
    rating,
  ].filter(Boolean).join(" | ");
}

function formatPresenceLabel(presence) {
  if (presence?.status === "in_game") return "In Game";
  if (presence?.status === "spectating") return "Spectating";
  if (presence?.status === "online") return "Online";
  return "Offline";
}

function presenceBadgeStyle(status = "offline") {
  if (status === "in_game") {
    return ratingBadgeStyle("#9fe2a5", "rgba(100,176,106,0.16)");
  }
  if (status === "spectating") {
    return ratingBadgeStyle("#9fc2ff", "rgba(90,120,180,0.16)");
  }
  if (status === "online") {
    return ratingBadgeStyle("#f0d69a", "rgba(232,201,106,0.1)");
  }
  return ratingBadgeStyle("#a89570", "rgba(120,110,90,0.12)");
}

function displayRatingDelta(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || !parsed) return "0";
  const rounded = Math.round(parsed);
  return `${rounded > 0 ? "+" : ""}${rounded}`;
}

function formatPercent(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "0%";
  return `${parsed % 1 === 0 ? parsed.toFixed(0) : parsed.toFixed(1)}%`;
}

function formatSignedStat(value, digits = 0) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || !parsed) {
    return digits > 0 ? `0.${"0".repeat(digits)}` : "0";
  }
  return `${parsed > 0 ? "+" : ""}${parsed.toFixed(digits)}`;
}

function formatCurrentStreak(streak) {
  if (!streak?.outcome || !streak?.length) {
    return "No streak";
  }
  return `${streak.length} ${formatOutcome(streak.outcome)}`;
}

function formatRecordLine(summary) {
  return `${summary?.wins || 0}-${summary?.losses || 0}-${summary?.draws || 0}`;
}

function formatBaseTimeOption(seconds) {
  if (seconds >= 3600) {
    const hours = seconds / 3600;
    return `${hours % 1 === 0 ? hours : hours.toFixed(1)}h`;
  }
  if (seconds >= 60) {
    return `${Math.round(seconds / 60)}m`;
  }
  return `${seconds}s`;
}

function getClockPresetId(config) {
  const cleanConfig = sanitizeConfig(config);
  const preset = CLOCK_PRESET_OPTIONS.find((option) => (
    !option.custom
    && option.baseSeconds === cleanConfig.baseSeconds
    && option.incrementSeconds === cleanConfig.incrementSeconds
  ));
  return preset?.id || "custom";
}

function ratingBadgeStyle(color = "#e0c47a", background = "rgba(232,201,106,0.12)") {
  return {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "5px 9px",
    borderRadius: 999,
    border: `1px solid ${background === "transparent" ? "#3b2d1a" : "rgba(232,201,106,0.16)"}`,
    background,
    color,
    fontFamily: "'DM Sans'",
    fontSize: 11,
    letterSpacing: 1.2,
    textTransform: "uppercase",
  };
}

function outcomeBadgeStyle(outcome) {
  if (outcome === "win") {
    return { background: "rgba(100,176,106,0.16)", border: "#335a34", color: "#a9e2af" };
  }
  if (outcome === "loss") {
    return { background: "rgba(196,104,104,0.14)", border: "#5f2d2d", color: "#f0a8a8" };
  }
  return { background: "rgba(120,130,150,0.14)", border: "#2f3542", color: "#ccd4e2" };
}

function NoticeToast({ notice, onDismiss }) {
  if (!notice) return null;
  return (
      <div style={{ position: "fixed", left: 20, bottom: 20, zIndex: 80, maxWidth: 380, padding: "13px 15px", borderRadius: 14, border: "1px solid #3c2818", background: "rgba(21,16,11,0.96)", color: "#e4c88f", fontFamily: "'DM Sans'", fontSize: 13, lineHeight: 1.65, boxShadow: "0 18px 50px rgba(0,0,0,0.4)" }}>
      <div style={{ display: "flex", alignItems: "start", gap: 12 }}>
        <div style={{ flex: 1 }}>{notice}</div>
        <button className="ghost-btn" onClick={onDismiss} style={{ ...ghostButton(false), padding: "6px 9px", fontSize: 11 }}>Close</button>
      </div>
    </div>
  );
}

function SearchBar({ query, results, loading, onChange, onSelect }) {
  return (
    <div style={{ position: "relative", width: "min(320px, 100%)" }}>
      <input className="top-input" value={query} onChange={(event) => onChange(event.target.value)} placeholder="Search user ID" style={{ ...inputStyle(), height: 40, paddingLeft: 12, paddingRight: 12 }} />
      {(loading || query.trim() || results.length) ? (
        <div style={{ position: "absolute", top: 46, left: 0, right: 0, ...panelStyle(), padding: 10, display: "flex", flexDirection: "column", gap: 6, zIndex: 40 }}>
          {loading ? infoText("Searching players...") : null}
          {!loading && query.trim() && !results.length ? infoText("No matching user profiles found.") : null}
          {!loading ? results.map((user) => (
            <button key={user.id} className="ghost-btn" onClick={() => onSelect(user)} style={{ ...ghostButton(false), textAlign: "left" }}>
              <div style={{ fontSize: 20 }}>{user.displayName}</div>
              <div style={{ fontFamily: "'DM Sans'", fontSize: 12, color: "#7c6841", display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                <span>@{user.loginId}</span>
                {formatRatingValue(user.rating) !== null ? <span style={ratingBadgeStyle("#dfc27a", "rgba(232,201,106,0.08)")}>R{formatRatingValue(user.rating)}</span> : null}
              </div>
            </button>
          )) : null}
        </div>
      ) : null}
    </div>
  );
}

function SessionMenu({ open, viewer, authMode, authForm, onAuthModeChange, onFieldChange, onLogin, onRegister, onResetSession, onOpenProfile }) {
  return (
    <div style={{ position: "relative" }}>
      {open ? (
        <div style={{ position: "absolute", top: 52, right: 0, width: 320, ...panelStyle(), zIndex: 60, display: "flex", flexDirection: "column", gap: 12 }}>
            <div>
              <div style={{ ...titleStyle(), fontSize: 24 }}>Identity</div>
            {viewer ? <div style={{ fontFamily: "'DM Sans'", fontSize: 12, color: "#ae935d", marginTop: 4 }}>{viewer.authenticated ? formatIdentityText(viewer) : `${viewer.displayName} | guest`}</div> : null}
            </div>

          {viewer?.authenticated ? (
            <>
              {infoText("Registered accounts can be searched and challenged directly from the hall.")}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button className="ghost-btn" onClick={onOpenProfile} style={ghostButton(false)}>My Profile</button>
                <button className="ghost-btn" onClick={onResetSession} style={ghostButton(false)}>Sign Out To Guest</button>
              </div>
            </>
          ) : (
            <>
              <div style={{ display: "flex", gap: 8 }}>
                <button className="ghost-btn" onClick={() => onAuthModeChange("login")} style={pill(authMode === "login")}>Login</button>
                <button className="ghost-btn" onClick={() => onAuthModeChange("register")} style={pill(authMode === "register")}>Register</button>
              </div>
              {authMode === "register" ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <input className="top-input" value={authForm.loginId} onChange={(event) => onFieldChange("loginId", event.target.value)} placeholder="User ID" style={inputStyle()} />
                  <input className="top-input" value={authForm.displayName} onChange={(event) => onFieldChange("displayName", event.target.value)} placeholder="Display name" style={inputStyle()} />
                  <input className="top-input" type="password" value={authForm.password} onChange={(event) => onFieldChange("password", event.target.value)} placeholder="Password" style={inputStyle()} />
                  <button className="hub-btn" onClick={onRegister} style={solidButton(false)}>Create Account</button>
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <input className="top-input" value={authForm.loginId} onChange={(event) => onFieldChange("loginId", event.target.value)} placeholder="User ID" style={inputStyle()} />
                  <input className="top-input" type="password" value={authForm.password} onChange={(event) => onFieldChange("password", event.target.value)} placeholder="Password" style={inputStyle()} />
                  <button className="hub-btn" onClick={onLogin} style={solidButton(false)}>Login</button>
                </div>
              )}
              <div style={{ borderTop: "1px solid #21190f", paddingTop: 12 }}>
                {infoText("Anonymous guests are still supported. Resetting creates a fresh guest identity.")}
                <button className="ghost-btn" onClick={onResetSession} style={{ ...ghostButton(false), marginTop: 10 }}>Fresh Guest Session</button>
              </div>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}

function TopBar(props) {
  const {
    viewer,
    activeTab,
    onTabChange,
    notice,
    onDismissNotice,
    searchQuery,
    searchResults,
    searchLoading,
    onSearchChange,
    onSelectSearchResult,
    showSearch,
    sessionMenuOpen,
    onToggleSessionMenu,
    authMode,
    authForm,
    onAuthModeChange,
    onAuthFieldChange,
    onLogin,
    onRegister,
    onResetSession,
    onOpenSelfProfile,
  } = props;

  return (
    <>
      <NoticeToast notice={notice} onDismiss={onDismissNotice} />
      <header style={{ ...panelStyle(), marginBottom: 18, padding: "16px 18px", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 34, fontWeight: 700, letterSpacing: 6, color: GOLD, textTransform: "uppercase", lineHeight: 1 }}>Anti-Gomoku</div>
          <div style={{ fontFamily: "'DM Sans'", fontSize: 11, letterSpacing: 3.5, color: "#4f422e", marginTop: 4, textTransform: "uppercase" }}>Hall . Profiles . Direct Challenges</div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginLeft: "auto" }}>
          <button className="ghost-btn" onClick={() => onTabChange("hall")} style={pill(activeTab === "hall")}>Hall</button>
          <button className="ghost-btn" onClick={() => onTabChange("profile")} style={pill(activeTab === "profile")}>Profile</button>
          {showSearch ? <SearchBar query={searchQuery} results={searchResults} loading={searchLoading} onChange={onSearchChange} onSelect={onSelectSearchResult} /> : null}
          <button className="ghost-btn" onClick={onToggleSessionMenu} style={ghostButton(false)}>
            {viewer ? (viewer.authenticated ? formatIdentityText(viewer) : `${viewer.displayName} | guest`) : "Session"}
          </button>
          <SessionMenu open={sessionMenuOpen} viewer={viewer} authMode={authMode} authForm={authForm} onAuthModeChange={onAuthModeChange} onFieldChange={onAuthFieldChange} onLogin={onLogin} onRegister={onRegister} onResetSession={onResetSession} onOpenProfile={onOpenSelfProfile} />
        </div>
      </header>
    </>
  );
}

function Section({ title, sub, children }) {
  return (
    <section style={{ ...panelStyle(), display: "flex", flexDirection: "column", gap: 14 }}>
      <div>
        <div style={titleStyle()}>{title}</div>
        {sub ? <div style={{ fontFamily: "'DM Sans'", fontSize: 12, color: "#8b7348", marginTop: 5, lineHeight: 1.6 }}>{sub}</div> : null}
      </div>
      {children}
    </section>
  );
}

function RoomCard({ room, actionLabel, onAction }) {
  return (
    <div style={{ padding: "14px 15px", borderRadius: 14, border: "1px solid #211a11", background: "#0f151c", display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
        <div>
          <div style={{ fontSize: 22, color: GOLD, letterSpacing: 2, textTransform: "uppercase" }}>Room {room.id}</div>
          <div style={{ fontFamily: "'DM Sans'", fontSize: 12, color: "#8b7348" }}>{formatRoomConfig(room.config)}</div>
        </div>
        <div style={{ fontFamily: "'DM Sans'", fontSize: 11, color: room.phase === "waiting" ? "#c8a86a" : room.phase === "active" ? "#a9c89c" : "#b9a5c8", textTransform: "uppercase", letterSpacing: 1.8 }}>{room.phase}</div>
      </div>
      <div style={{ fontFamily: "'DM Sans'", fontSize: 12, color: "#d2bd92", lineHeight: 1.75 }}>
        <div><span style={{ color: "#7c6841" }}>Host:</span> {room.host ? formatIdentityText(room.host) : "Unknown"}</div>
        <div><span style={{ color: "#7c6841" }}>Guest:</span> {room.guest ? formatIdentityText(room.guest) : room.invitedUser ? formatIdentityText(room.invitedUser) : "Open seat"}</div>
        <div><span style={{ color: "#7c6841" }}>Spectators:</span> {room.spectatorCount || 0}</div>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
        <div style={{ fontFamily: "'DM Sans'", fontSize: 12, color: "#786544" }}>
          {room.visibility === "invite" ? "Direct invite room" : "Public room"}
          {room.listedPublicly ? " | visible in watch list" : room.publicVisible ? " | hidden until game starts" : " | hidden from public list"}
        </div>
        {actionLabel ? <button className="hub-btn" onClick={() => onAction(room)} style={solidButton(false)}>{actionLabel}</button> : null}
      </div>
    </div>
  );
}

function ModalShell({ open, title, sub, onClose, width = 640, children }) {
  if (!open) return null;
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(8,10,14,0.78)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24, zIndex: 70 }}>
      <div style={{ width: `min(100%, ${width}px)`, maxHeight: "min(88vh, 760px)", overflowY: "auto", ...panelStyle(), padding: "18px 20px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "start", marginBottom: 16 }}>
          <div>
            <div style={titleStyle()}>{title}</div>
            {sub ? <div style={{ fontFamily: "'DM Sans'", fontSize: 12, color: "#8b7348", marginTop: 5, lineHeight: 1.6 }}>{sub}</div> : null}
          </div>
          <button className="ghost-btn" onClick={onClose} style={{ ...ghostButton(false), padding: "8px 12px" }}>Close</button>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>{children}</div>
      </div>
    </div>
  );
}

function HallActionCard({ title, count, description, actionLabel, onOpen }) {
  return (
    <button className="ghost-btn" onClick={onOpen} style={{ ...panelStyle(), padding: "20px 18px", minHeight: 214, display: "flex", flexDirection: "column", alignItems: "flex-start", justifyContent: "space-between", textAlign: "left", cursor: "pointer" }}>
      <div>
        <div style={{ fontFamily: "'DM Sans'", fontSize: 11, letterSpacing: 2.3, textTransform: "uppercase", color: "#8b7348", marginBottom: 10 }}>{count !== null && count !== undefined ? `Count ${count}` : "Action"}</div>
        <div style={{ ...titleStyle(), fontSize: 28 }}>{title}</div>
        <div style={{ fontFamily: "'DM Sans'", fontSize: 13, lineHeight: 1.85, color: "#c2ab80", marginTop: 12 }}>{description}</div>
      </div>
      <div style={{ fontFamily: "'DM Sans'", fontSize: 12, letterSpacing: 1.8, textTransform: "uppercase", color: GOLD }}>{actionLabel}</div>
    </button>
  );
}

function CurrentRoomStrip({ room, onOpenRoom }) {
  if (!room) return null;
  return (
    <Section title="Current Room" sub="You only need one quick way back into the room you are already in.">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div style={{ fontFamily: "'DM Sans'", fontSize: 13, lineHeight: 1.8, color: "#d4c08f" }}>
          <div style={{ color: GOLD, fontSize: 19, letterSpacing: 2, textTransform: "uppercase" }}>Room {room.id}</div>
          <div>{formatRoomConfig(room.config)}</div>
        </div>
        <button className="hub-btn" onClick={() => onOpenRoom(room)} style={solidButton(false)}>Open Room</button>
      </div>
    </Section>
  );
}

function MatchConfigFields({ config, onConfigChange }) {
  const cleanConfig = sanitizeConfig(config);
  const presetId = getClockPresetId(cleanConfig);
  const baseIndex = Math.max(0, CUSTOM_BASE_TIME_OPTIONS.indexOf(cleanConfig.baseSeconds ?? 180));

  return (
    <>
      <div>
        <div style={labelStyle()}>Board Size</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {SIZE_OPTIONS.map((size) => <button key={size} className="ghost-btn" onClick={() => onConfigChange({ ...cleanConfig, boardSize: size })} style={pill(cleanConfig.boardSize === size)}>{size} x {size}</button>)}
        </div>
      </div>
      <div>
        <div style={labelStyle()}>Starting Color</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {COLOR_MODE_OPTIONS.map((option) => <button key={option.value} className="ghost-btn" onClick={() => onConfigChange({ ...cleanConfig, colorMode: option.value })} style={pill(cleanConfig.colorMode === option.value)}>{option.label}</button>)}
        </div>
      </div>
      <div>
        <div style={labelStyle()}>Clock</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {CLOCK_PRESET_OPTIONS.map((option) => (
            <button
              key={option.id}
              className="ghost-btn"
              onClick={() => onConfigChange(option.custom ? {
                ...cleanConfig,
                baseSeconds: cleanConfig.baseSeconds ?? 180,
                incrementSeconds: cleanConfig.baseSeconds === null ? 2 : cleanConfig.incrementSeconds,
              } : {
                ...cleanConfig,
                baseSeconds: option.baseSeconds,
                incrementSeconds: option.incrementSeconds,
              })}
              style={pill(presetId === option.id)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>
      {presetId === "custom" ? (
        <div style={{ display: "grid", gap: 12, padding: "14px 15px", borderRadius: 14, border: "1px solid #211a11", background: "#0f151c" }}>
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center", marginBottom: 8 }}>
              <div style={labelStyle()}>Base Time</div>
              <div style={{ fontFamily: "'DM Sans'", fontSize: 12, color: "#d4c08f" }}>{cleanConfig.baseSeconds === null ? "Unlimited" : formatBaseTimeOption(cleanConfig.baseSeconds)}</div>
            </div>
            <input type="range" min={0} max={CUSTOM_BASE_TIME_OPTIONS.length - 1} step={1} value={baseIndex} onChange={(event) => onConfigChange({ ...cleanConfig, baseSeconds: CUSTOM_BASE_TIME_OPTIONS[Number(event.target.value)] })} style={{ width: "100%" }} />
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, fontFamily: "'DM Sans'", fontSize: 10, color: "#7c6841", marginTop: 6 }}>
              <span>30s</span>
              <span>1m</span>
              <span>5m</span>
              <span>10m</span>
              <span>30m</span>
              <span>2h</span>
            </div>
          </div>
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center", marginBottom: 8 }}>
              <div style={labelStyle()}>Increment</div>
              <div style={{ fontFamily: "'DM Sans'", fontSize: 12, color: "#d4c08f" }}>+{cleanConfig.incrementSeconds}s</div>
            </div>
            <input type="range" min={0} max={60} step={1} value={cleanConfig.incrementSeconds} onChange={(event) => onConfigChange({ ...cleanConfig, incrementSeconds: Number(event.target.value) })} style={{ width: "100%" }} />
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, fontFamily: "'DM Sans'", fontSize: 10, color: "#7c6841", marginTop: 6 }}>
              <span>0s</span>
              <span>15s</span>
              <span>30s</span>
              <span>45s</span>
              <span>60s</span>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

function VisibilityField({ value, onChange, helpText }) {
  return (
    <div>
      <div style={labelStyle()}>Public Visibility</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        <button className="ghost-btn" onClick={() => onChange(true)} style={pill(!!value)}>Visible</button>
        <button className="ghost-btn" onClick={() => onChange(false)} style={pill(!value)}>Hidden</button>
      </div>
      {infoText(helpText || "Visible rooms can appear in the public watch list once they are eligible for public viewing.")}
    </div>
  );
}

function CreateRoomModal({ open, onClose, createConfig, createPublicVisible, onConfigChange, onCreatePublicVisibleChange, onCreatePublic, onStartLocal }) {
  return (
    <ModalShell open={open} onClose={onClose} title="Create Room" sub="Configure the board once, then start an online room or a local practice board.">
      <MatchConfigFields config={createConfig} onConfigChange={(nextConfig) => onConfigChange(sanitizeConfig(nextConfig))} />
      <VisibilityField value={createPublicVisible} onChange={onCreatePublicVisibleChange} helpText="Visible rooms show up in the public room browser while waiting, and started games can be watched." />
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="hub-btn" onClick={onCreatePublic} style={solidButton(false)}>Create Online Room</button>
        <button className="ghost-btn" onClick={onStartLocal} style={ghostButton(false)}>Local Practice</button>
      </div>
    </ModalShell>
  );
}

function JoinCodeModal({ open, onClose, roomCode, onRoomCodeChange, onJoinByCode }) {
  const normalizedCode = normalizeRoomId(roomCode);
  return (
    <ModalShell open={open} onClose={onClose} title="Join With Code" sub="Enter the room code shared by another player.">
      <div>
        <div style={labelStyle()}>Room Code</div>
        <div style={{ display: "flex", gap: 8 }}>
          <input className="top-input" value={roomCode} onChange={(event) => onRoomCodeChange(event.target.value.toUpperCase())} placeholder="ABC123" style={{ ...inputStyle(), letterSpacing: 3, textTransform: "uppercase" }} />
          <button className="hub-btn" onClick={onJoinByCode} disabled={!normalizedCode} style={solidButton(!normalizedCode)}>Join</button>
        </div>
      </div>
      {infoText("Invite links can still open rooms directly. If the room has already started, entering the code will open it in spectator mode.")}
    </ModalShell>
  );
}

function RoomBrowserModal({ open, onClose, title, sub, rooms, emptyText, actionLabel, onAction }) {
  return (
    <ModalShell open={open} onClose={onClose} title={title} sub={sub}>
      {!rooms.length ? infoText(emptyText) : rooms.map((room) => (
        <RoomCard key={room.id} room={room} actionLabel={actionLabel(room)} onAction={(selectedRoom) => {
          onAction(selectedRoom);
          onClose();
        }} />
      ))}
    </ModalShell>
  );
}

function SummaryGrid({ items }) {
  const visibleItems = (items || []).filter((item) => item && (item.value !== undefined && item.value !== null && item.value !== ""));
  if (!visibleItems.length) {
    return null;
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 10 }}>
      {visibleItems.map((item) => (
        <div key={item.label} style={statCardStyle(item.tone)}>
          <div style={{ fontFamily: "'DM Sans'", fontSize: 11, letterSpacing: 1.8, textTransform: "uppercase", color: "#9b8256" }}>{item.label}</div>
          <div>
            <div style={{ fontSize: 27, color: item.tone?.color || GOLD, lineHeight: 1.05 }}>{item.value}</div>
            {item.sub ? <div style={{ fontFamily: "'DM Sans'", fontSize: 12, color: "#bfa77a", marginTop: 7, lineHeight: 1.55 }}>{item.sub}</div> : null}
          </div>
        </div>
      ))}
    </div>
  );
}

function MatchHistoryEntryCard({ entry, onOpenHistoryRecord, onOpenOpponentProfile, hideOpponentButton = false }) {
  const outcomeTone = outcomeBadgeStyle(entry.outcome);

  return (
    <div style={{ padding: "16px 16px", borderRadius: 16, border: "1px solid #2a2014", background: "linear-gradient(180deg, #121a22, #0d141b)", boxShadow: "0 14px 40px rgba(0,0,0,0.24)", display: "flex", justifyContent: "space-between", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
      <div style={{ fontFamily: "'DM Sans'", fontSize: 12, color: "#d2bd92", lineHeight: 1.8, flex: "1 1 320px" }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 8 }}>
          <span style={{ ...ratingBadgeStyle(outcomeTone.color, outcomeTone.background), border: `1px solid ${outcomeTone.border}` }}>{formatOutcome(entry.outcome)}</span>
          <span style={{ color: GOLD, fontSize: 17 }}>Room {entry.roomId}{entry.gameIndex ? ` | Game ${entry.gameIndex}` : ""}</span>
        </div>
        <div style={{ fontSize: 21, color: "#f0d9a4", marginBottom: 7, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <span>vs</span>
          {entry.opponent?.loginId && !hideOpponentButton ? (
            <button className="ghost-btn" onClick={() => onOpenOpponentProfile(entry.opponent.loginId)} style={{ ...ghostButton(false), padding: "5px 11px", fontSize: 13, letterSpacing: 0.3, textTransform: "none" }}>
              {formatIdentityText(entry.opponent, { historical: true })}
            </button>
          ) : (
            <span>{formatIdentityText(entry.opponent, { historical: true })}</span>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
          {formatRatingValue(entry.player?.ratingBefore ?? entry.player?.rating) !== null ? <span style={ratingBadgeStyle("#f0d69a", "rgba(232,201,106,0.08)")}>You {formatRatingTag(entry.player, { historical: true })}</span> : null}
          {entry.rating ? <span style={ratingBadgeStyle((entry.rating.delta || 0) >= 0 ? "#9fe2a5" : "#f0a8a8", (entry.rating.delta || 0) >= 0 ? "rgba(100,176,106,0.16)" : "rgba(196,104,104,0.14)")}>{displayRatingDelta(entry.rating.delta)}</span> : null}
          {entry.rating?.after ? <span style={ratingBadgeStyle("#d8c18f", "rgba(96,78,44,0.18)")}>Now R{formatRatingValue(entry.rating.after)}</span> : null}
        </div>
        <div>{formatRoomConfig(entry.config)} | {entry.finishedAt ? new Date(entry.finishedAt).toLocaleString() : "Unknown time"}</div>
      </div>
      <button className="hub-btn" onClick={() => onOpenHistoryRecord(entry)} style={solidButton(false)}>Review</button>
    </div>
  );
}

function RecordArchiveEntryCard({ record, onOpenArchivedRecord, onDeleteArchivedRecord }) {
  return (
    <div style={{ padding: "14px 15px", borderRadius: 14, border: "1px solid #211a11", background: "#0f151c", display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
      <div style={{ fontFamily: "'DM Sans'", fontSize: 12, color: "#d2bd92", lineHeight: 1.8 }}>
        <div style={{ color: GOLD, fontSize: 17 }}>{record.meta?.title || "Untitled Record"}</div>
        <div>{record.meta?.sourceKind === "online" ? "Online Match" : "Local Practice"}{record.meta?.roomId ? ` | Room ${record.meta.roomId}` : ""}{record.meta?.gameIndex ? ` | Game ${record.meta.gameIndex}` : ""}</div>
        <div>{formatRoomConfig(record.config)} | Updated {record.meta?.updatedAt ? new Date(record.meta.updatedAt).toLocaleString() : "Unknown time"}</div>
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="hub-btn" onClick={() => onOpenArchivedRecord(record)} style={solidButton(false)}>Open</button>
        <button className="ghost-btn" onClick={() => onDeleteArchivedRecord(record.id)} style={ghostButton(false)}>Delete</button>
      </div>
    </div>
  );
}

function ProfileOverviewPanel({ isSelf, viewer, profileUser, statsSummary, challengeConfig, challengePublicVisible, onConfigChange, onChallengePublicVisibleChange, onChallenge, onOpenPresenceRoom }) {
  if (!profileUser) {
    return (
      <Section title="Profile" sub="Open a user from the hall search to view details and issue a challenge.">
        {infoText("The profile page now stays focused on one person at a time instead of mixing hall actions into the same screen.")}
      </Section>
    );
  }

  const presence = profileUser.presence || { status: "offline", roomId: "", canSpectate: false };
  const canOpenPresenceRoom = !!presence.roomId && (presence.status === "in_game" || presence.status === "spectating");
  const summaryItems = [
    { label: "Record", value: formatRecordLine(statsSummary), sub: `${statsSummary?.totalGames || 0} online games`, tone: statTone("gold") },
    { label: "Win Rate", value: formatPercent(statsSummary?.winRate || 0), sub: `${statsSummary?.wins || 0} wins`, tone: statTone("sage") },
    { label: "Rated", value: `${statsSummary?.ratedGames || 0}`, sub: `${statsSummary?.unratedGames || 0} unrated`, tone: statTone("slate") },
    { label: "Streak", value: formatCurrentStreak(statsSummary?.currentStreak), sub: statsSummary?.bestWinStreak ? `Best win streak ${statsSummary.bestWinStreak}` : "No win streak yet", tone: statTone("ember") },
  ];

  return (
    <Section title={isSelf ? "My Profile" : "Player Profile"} sub={isSelf ? "Your account summary, current standing, and the quickest routes into history and review." : "Review the player, compare records, and open an invite-only room from one place."}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16 }}>
        <div style={{ padding: "16px 17px", borderRadius: 16, background: "linear-gradient(160deg, #171108 0%, #0f151c 62%, #101922 100%)", border: "1px solid #2c2213", minHeight: 212 }}>
          <div style={{ fontSize: 34, color: GOLD }}>{profileUser.displayName}</div>
          <div style={{ fontFamily: "'DM Sans'", fontSize: 13, color: "#b08f56", marginTop: 5 }}>{profileUser.loginId ? `@${profileUser.loginId}` : "Guest"}</div>
          {formatRatingValue(profileUser.rating) !== null ? (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 12 }}>
              <span style={{ ...ratingBadgeStyle("#1a1208", GOLD), color: "#1a1208", background: GOLD, border: "none" }}>Rating {formatRatingValue(profileUser.rating)}</span>
              <span style={ratingBadgeStyle("#d8c18f", "rgba(232,201,106,0.08)")}>Temp x{Number(profileUser.ratingTemperature || 1).toFixed(2)}</span>
              <span style={ratingBadgeStyle("#c5b189", "rgba(96,78,44,0.18)")}>{profileUser.ratedGames || 0} Rated Games</span>
            </div>
          ) : null}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 12 }}>
            <span style={presenceBadgeStyle(presence.status)}>{formatPresenceLabel(presence)}</span>
            {canOpenPresenceRoom ? (
              <button className="ghost-btn" onClick={() => onOpenPresenceRoom(presence.roomId)} style={{ ...ghostButton(false), padding: "7px 11px", fontSize: 11 }}>
                {isSelf ? "Open Room" : "Spectate Room"}
              </button>
            ) : null}
          </div>
          <div style={{ fontFamily: "'DM Sans'", fontSize: 13, color: "#bfa77a", lineHeight: 1.75, marginTop: 16 }}>
            {isSelf
              ? "Your profile keeps the core match signals visible: rating, form, archive access, and recent rated movement."
              : "This profile shows the player's live presence, public online record, and your direct results against them when available."}
          </div>
        </div>

        <div style={{ display: "grid", gap: 10, alignContent: "start" }}>
          <SummaryGrid items={summaryItems} />
        </div>
      </div>

      {!isSelf ? (
        <div style={{ display: "grid", gap: 14, gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }}>
          <div style={{ padding: "14px 15px", borderRadius: 14, background: "#0f151c", border: "1px solid #211a11" }}>
            <MatchConfigFields config={challengeConfig} onConfigChange={(nextConfig) => onConfigChange(sanitizeConfig(nextConfig))} />
          </div>
          <div style={{ padding: "14px 15px", borderRadius: 14, background: "#0f151c", border: "1px solid #211a11", display: "flex", flexDirection: "column", gap: 14, justifyContent: "space-between" }}>
            <VisibilityField value={challengePublicVisible} onChange={onChallengePublicVisibleChange} helpText="The direct invite stays private while waiting. If visibility is on, the started game can be watched from the public room browser." />
            <button className="hub-btn" onClick={onChallenge} disabled={!viewer} style={solidButton(!viewer)}>Challenge @{profileUser.loginId}</button>
            {infoText("This creates an invite-only room reserved for the viewed account.")}
          </div>
        </div>
      ) : (
        <div style={{ padding: "14px 16px", borderRadius: 14, background: "#0f151c", border: "1px solid #211a11" }}>
          {infoText("Match history and archive sections below are capped into scrollable panes so the page stays usable even after many games.")}
        </div>
      )}
    </Section>
  );
}

function RatingTrendPanel({ profileUser, history, summary }) {
  const orderedHistory = [...(history || [])]
    .sort((left, right) => String(left.finishedAt || "").localeCompare(String(right.finishedAt || "")));

  const series = [];
  if (orderedHistory.length) {
    const initialRating = formatRatingValue(orderedHistory[0]?.player?.ratingBefore ?? orderedHistory[0]?.player?.rating);
    if (initialRating !== null) {
      series.push({ label: "Start", rating: initialRating, outcome: null });
    }
    orderedHistory.forEach((entry, index) => {
      const ratingAfter = formatRatingValue(entry?.rating?.after ?? entry?.player?.ratingAfter ?? entry?.player?.rating);
      if (ratingAfter !== null) {
        series.push({
          label: `${index + 1}`,
          rating: ratingAfter,
          outcome: entry.outcome,
          date: entry.finishedAt,
        });
      }
    });
  } else if (formatRatingValue(profileUser?.rating) !== null) {
    series.push({ label: "Now", rating: formatRatingValue(profileUser?.rating), outcome: null });
  }

  const ratings = series.map((point) => point.rating);
  const minRating = ratings.length ? Math.min(...ratings) : 1000;
  const maxRating = ratings.length ? Math.max(...ratings) : 1000;
  const paddedMin = minRating - 20;
  const paddedMax = maxRating + 20;
  const width = 720;
  const height = 220;
  const padX = 24;
  const padY = 24;
  const stepX = series.length > 1 ? (width - padX * 2) / (series.length - 1) : 0;
  const projectY = (rating) => {
    if (paddedMax === paddedMin) return height / 2;
    const ratio = (rating - paddedMin) / (paddedMax - paddedMin);
    return height - padY - ratio * (height - padY * 2);
  };
  const points = series.map((point, index) => ({
    ...point,
    x: padX + index * stepX,
    y: projectY(point.rating),
  }));
  const pathD = points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
  const fillD = points.length
    ? `${pathD} L ${points[points.length - 1].x} ${height - padY} L ${points[0].x} ${height - padY} Z`
    : "";
  const peak = ratings.length ? Math.max(...ratings) : null;
  const floor = ratings.length ? Math.min(...ratings) : null;
  const trendItems = [
    { label: "Record", value: formatRecordLine(summary), sub: `${summary?.totalGames || 0} online games`, tone: statTone("gold") },
    { label: "Win Rate", value: formatPercent(summary?.winRate || 0), sub: `${summary?.wins || 0} wins, ${summary?.draws || 0} draws`, tone: statTone("sage") },
    { label: "Avg Delta", value: formatSignedStat(summary?.averageRatedDelta || 0, 1), sub: `${summary?.ratedGames || 0} rated matches`, tone: statTone("slate") },
    { label: "Best Gain", value: displayRatingDelta(summary?.bestRatedGain || 0), sub: `Worst ${displayRatingDelta(summary?.worstRatedDrop || 0)}`, tone: statTone("ember") },
    { label: "Rated Net", value: displayRatingDelta(summary?.totalRatedDelta || 0), sub: `${summary?.unratedGames || 0} unrated games`, tone: statTone("gold") },
    { label: "Current Streak", value: formatCurrentStreak(summary?.currentStreak), sub: summary?.bestWinStreak ? `Best win streak ${summary.bestWinStreak}` : "Still building", tone: statTone("slate") },
  ];

  return (
    <Section title="Rating Curve" sub="Your rated path stays visible here with results context, record totals, and rating swings alongside the curve.">
      <SummaryGrid items={trendItems} />
      {!points.length ? infoText("Play a rated online match to start building a visible rating curve.") : (
        <>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ ...ratingBadgeStyle("#1a1208", GOLD), color: "#1a1208", background: GOLD, border: "none" }}>Current {formatRatingValue(profileUser?.rating) ?? points[points.length - 1].rating}</span>
            {peak !== null ? <span style={ratingBadgeStyle("#d8c18f", "rgba(232,201,106,0.08)")}>Peak {peak}</span> : null}
            {floor !== null ? <span style={ratingBadgeStyle("#c5b189", "rgba(96,78,44,0.18)")}>Low {floor}</span> : null}
            <span style={ratingBadgeStyle("#a8c2de", "rgba(120,150,190,0.14)")}>{Math.max(0, points.length - 1)} Rated Matches</span>
          </div>
          <div style={{ borderRadius: 16, overflow: "hidden", border: "1px solid #21190f", background: "linear-gradient(180deg, #10171f, #0c1218)" }}>
            <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto", display: "block" }}>
              <defs>
                <linearGradient id="rating-line" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="#8cb5d6" />
                  <stop offset="100%" stopColor="#e8c96a" />
                </linearGradient>
                <linearGradient id="rating-fill" x1="0%" y1="0%" x2="0%" y2="100%">
                  <stop offset="0%" stopColor="rgba(232,201,106,0.28)" />
                  <stop offset="100%" stopColor="rgba(232,201,106,0)" />
                </linearGradient>
              </defs>
              {[0, 0.5, 1].map((ratio) => {
                const y = padY + ratio * (height - padY * 2);
                const rating = Math.round(paddedMax - ratio * (paddedMax - paddedMin));
                return (
                  <g key={`grid-${ratio}`}>
                    <line x1={padX} y1={y} x2={width - padX} y2={y} stroke="rgba(209,174,100,0.12)" strokeWidth="1" />
                    <text x={width - padX + 4} y={y + 4} fill="#8f7546" fontFamily="'DM Sans'" fontSize="10">{rating}</text>
                  </g>
                );
              })}
              {fillD ? <path d={fillD} fill="rgba(232,201,106,0.12)" /> : null}
              {pathD ? <path d={pathD} fill="none" stroke="url(#rating-line)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /> : null}
              {points.map((point, index) => {
                const color = point.outcome === "win" ? "#9fe2a5" : point.outcome === "loss" ? "#f0a8a8" : GOLD;
                return (
                  <g key={`point-${index}`}>
                    <circle cx={point.x} cy={point.y} r={index === points.length - 1 ? 5.5 : 4} fill={color} stroke="#0d1117" strokeWidth="2" />
                    <text x={point.x} y={height - 8} textAnchor="middle" fill="#8f7546" fontFamily="'DM Sans'" fontSize="10">{point.label}</text>
                  </g>
                );
              })}
            </svg>
          </div>
        </>
      )}
    </Section>
  );
}

function RecentMatchesPanel({ history, onOpenHistoryRecord, onOpenOpponentProfile }) {
  return (
    <Section title="Online Match History" sub="Finished online games stay in a scrollable review list so the profile page remains easy to navigate as the list grows.">
      {!history.length ? infoText("No recent online match history is available for this profile yet.") : (
        <div style={scrollAreaStyle(620)}>
          {history.map((entry) => (
            <MatchHistoryEntryCard key={`${entry.gameId}:${entry.finishedAt}`} entry={entry} onOpenHistoryRecord={onOpenHistoryRecord} onOpenOpponentProfile={onOpenOpponentProfile} />
          ))}
        </div>
      )}
    </Section>
  );
}

function HeadToHeadPanel({ profileUser, viewer, headToHead, onOpenHistoryRecord }) {
  if (!profileUser) {
    return null;
  }

  if (!viewer?.userId) {
    return (
      <Section title="Head-to-Head" sub="Create a registered account to keep persistent records against specific opponents.">
        {infoText("Direct head-to-head history only appears for signed-in accounts because guest sessions do not keep a long-term match record.")}
      </Section>
    );
  }

  const summary = headToHead?.summary || null;
  const recent = headToHead?.recent || [];
  const items = [
    { label: "Record", value: formatRecordLine(summary), sub: `${summary?.totalGames || 0} games together`, tone: statTone("gold") },
    { label: "Win Rate", value: formatPercent(summary?.winRate || 0), sub: `${summary?.wins || 0} wins`, tone: statTone("sage") },
    { label: "Rated Net", value: displayRatingDelta(summary?.totalRatedDelta || 0), sub: `${summary?.ratedGames || 0} rated clashes`, tone: statTone("slate") },
    { label: "Last Result", value: recent[0] ? formatOutcome(recent[0].outcome) : "None yet", sub: summary?.lastPlayedAt ? new Date(summary.lastPlayedAt).toLocaleString() : "No finished games", tone: statTone("ember") },
  ];

  return (
    <Section title={`Against @${profileUser.loginId || profileUser.displayName}`} sub="Your direct history against this player is summarized here, with recent meetings ready for replay.">
      <SummaryGrid items={items} />
      {!recent.length ? infoText("You have not finished an online match against this player yet.") : (
        <div style={scrollAreaStyle(460)}>
          {recent.map((entry) => (
            <MatchHistoryEntryCard key={`${entry.gameId}:${entry.finishedAt}`} entry={entry} onOpenHistoryRecord={onOpenHistoryRecord} onOpenOpponentProfile={() => {}} hideOpponentButton />
          ))}
        </div>
      )}
    </Section>
  );
}

function RecordArchivePanel({ records, onOpenArchivedRecord, onDeleteArchivedRecord }) {
  return (
    <Section title="Record Archive" sub="Local practice lines and auto-saved online records live in a separate scrollable pane for faster browsing.">
      {!records.length ? infoText("Your record archive is empty right now.") : (
        <div style={scrollAreaStyle(620)}>
          {records.map((record) => (
            <RecordArchiveEntryCard key={record.id} record={record} onOpenArchivedRecord={onOpenArchivedRecord} onDeleteArchivedRecord={onDeleteArchivedRecord} />
          ))}
        </div>
      )}
    </Section>
  );
}

export function HallPage(props) {
  const {
    viewer,
    notice,
    onDismissNotice,
    activeTab,
    onTabChange,
    rooms,
    roomCode,
    onRoomCodeChange,
    onJoinByCode,
    createConfig,
    createPublicVisible,
    onConfigChange,
    onCreatePublicVisibleChange,
    onCreatePublic,
    onOpenRoom,
    onStartLocal,
    searchQuery,
    searchResults,
    searchLoading,
    onSearchChange,
    onSelectSearchResult,
    sessionMenuOpen,
    onToggleSessionMenu,
    authMode,
    authForm,
    onAuthModeChange,
    onAuthFieldChange,
    onLogin,
    onRegister,
    onResetSession,
    onOpenSelfProfile,
  } = props;

  const [activePanel, setActivePanel] = useState(null);
  const currentRoom = rooms.myRooms[0] || rooms.activeRooms[0] || rooms.spectatingRooms[0] || null;

  return (
    <div style={pageStyle}>
      <style>{BASE_CSS}</style>
      <TopBar
        viewer={viewer}
        activeTab={activeTab}
        onTabChange={onTabChange}
        notice={notice}
        onDismissNotice={onDismissNotice}
        searchQuery={searchQuery}
        searchResults={searchResults}
        searchLoading={searchLoading}
        onSearchChange={onSearchChange}
        onSelectSearchResult={onSelectSearchResult}
        showSearch
        sessionMenuOpen={sessionMenuOpen}
        onToggleSessionMenu={onToggleSessionMenu}
        authMode={authMode}
        authForm={authForm}
        onAuthModeChange={onAuthModeChange}
        onAuthFieldChange={onAuthFieldChange}
        onLogin={onLogin}
        onRegister={onRegister}
        onResetSession={onResetSession}
        onOpenSelfProfile={onOpenSelfProfile}
      />

      <div style={{ display: "grid", gap: 18 }}>
        <CurrentRoomStrip room={currentRoom} onOpenRoom={onOpenRoom} />

        <Section title="Hall" sub="Keep the home screen light: search at the top, then enter the exact room action you want from one of these four panels.">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 16 }}>
            <HallActionCard title="Create Room" count={null} description="Open a new public room or spin up a local board with the same match settings." actionLabel="Configure" onOpen={() => setActivePanel("create")} />
            <HallActionCard title="Join With Code" count={null} description="Paste a room code when someone shares one manually instead of sending the full link." actionLabel="Enter Code" onOpen={() => setActivePanel("code")} />
            <HallActionCard title="Join Public Room" count={rooms.publicRooms.length} description="Browse all visible public rooms. Pending rooms can be joined, and started games can be watched." actionLabel="Browse Public Rooms" onOpen={() => setActivePanel("public")} />
            <HallActionCard title="Pending Invites" count={rooms.invites.length} description="Open the direct challenges that are currently reserved for this identity." actionLabel="Review Invites" onOpen={() => setActivePanel("invites")} />
          </div>
        </Section>
      </div>

      <CreateRoomModal open={activePanel === "create"} onClose={() => setActivePanel(null)} createConfig={sanitizeConfig(createConfig)} createPublicVisible={createPublicVisible} onConfigChange={onConfigChange} onCreatePublicVisibleChange={onCreatePublicVisibleChange} onCreatePublic={onCreatePublic} onStartLocal={onStartLocal} />
      <JoinCodeModal open={activePanel === "code"} onClose={() => setActivePanel(null)} roomCode={roomCode} onRoomCodeChange={onRoomCodeChange} onJoinByCode={onJoinByCode} />
      <RoomBrowserModal open={activePanel === "public"} onClose={() => setActivePanel(null)} title="Public Rooms" sub="Visible waiting rooms and active games both appear here. Join an open seat, or spectate a game already in progress." rooms={rooms.publicRooms} emptyText="The public hall is quiet right now." actionLabel={(room) => room.canJoin ? "Join" : room.canSpectate ? "Spectate" : null} onAction={onOpenRoom} />
      <RoomBrowserModal open={activePanel === "invites"} onClose={() => setActivePanel(null)} title="Pending Invites" sub="These rooms were created specifically for this account or guest session." rooms={rooms.invites} emptyText="No direct challenges are waiting for you right now." actionLabel={() => "Join"} onAction={onOpenRoom} />
    </div>
  );
}

export function ProfilePage(props) {
  const {
    viewer,
    notice,
    onDismissNotice,
    activeTab,
    onTabChange,
    profileUser,
    challengeConfig,
    challengePublicVisible,
    onChallengeConfigChange,
    onChallengePublicVisibleChange,
    onChallenge,
    onOpenPresenceRoom,
    matchHistory,
    matchHistorySummary,
    profileStats,
    headToHead,
    archiveRecords,
    onOpenHistoryRecord,
    onOpenArchivedRecord,
    onDeleteArchivedRecord,
    onOpenOpponentProfile,
    sessionMenuOpen,
    onToggleSessionMenu,
    authMode,
    authForm,
    onAuthModeChange,
    onAuthFieldChange,
    onLogin,
    onRegister,
    onResetSession,
    onOpenSelfProfile,
  } = props;

  const isSelf = !!(
    viewer
    && profileUser
    && (
      (viewer.loginId && profileUser.loginId && profileUser.loginId === viewer.loginId)
      || (!viewer.loginId && !profileUser.loginId && profileUser.displayName === viewer.displayName)
    )
  );
  const statsSummary = isSelf ? matchHistorySummary : profileStats;

  return (
    <div style={pageStyle}>
      <style>{BASE_CSS}</style>
      <TopBar
        viewer={viewer}
        activeTab={activeTab}
        onTabChange={onTabChange}
        notice={notice}
        onDismissNotice={onDismissNotice}
        searchQuery=""
        searchResults={[]}
        searchLoading={false}
        onSearchChange={() => {}}
        onSelectSearchResult={() => {}}
        showSearch={false}
        sessionMenuOpen={sessionMenuOpen}
        onToggleSessionMenu={onToggleSessionMenu}
        authMode={authMode}
        authForm={authForm}
        onAuthModeChange={onAuthModeChange}
        onAuthFieldChange={onAuthFieldChange}
        onLogin={onLogin}
        onRegister={onRegister}
        onResetSession={onResetSession}
        onOpenSelfProfile={onOpenSelfProfile}
      />

      <div style={{ display: "grid", gap: 18 }}>
        <ProfileOverviewPanel isSelf={isSelf} viewer={viewer} profileUser={profileUser} statsSummary={statsSummary} challengeConfig={sanitizeConfig(challengeConfig)} challengePublicVisible={challengePublicVisible} onConfigChange={onChallengeConfigChange} onChallengePublicVisibleChange={onChallengePublicVisibleChange} onChallenge={onChallenge} onOpenPresenceRoom={onOpenPresenceRoom} />
        {isSelf ? <RatingTrendPanel profileUser={profileUser} history={matchHistory || []} summary={matchHistorySummary} /> : null}
        {isSelf ? (
          <div style={{ display: "grid", gap: 18, gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", alignItems: "start" }}>
            <RecentMatchesPanel history={matchHistory || []} onOpenHistoryRecord={onOpenHistoryRecord} onOpenOpponentProfile={onOpenOpponentProfile} />
            <RecordArchivePanel records={archiveRecords || []} onOpenArchivedRecord={onOpenArchivedRecord} onDeleteArchivedRecord={onDeleteArchivedRecord} />
          </div>
        ) : null}
        {!isSelf ? <HeadToHeadPanel profileUser={profileUser} viewer={viewer} headToHead={headToHead} onOpenHistoryRecord={onOpenHistoryRecord} /> : null}
      </div>
    </div>
  );
}

export function LoadingPage({ message }) {
  return (
    <div style={{ ...pageStyle, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <style>{BASE_CSS}</style>
      <div style={{ ...panelStyle(), width: "100%", maxWidth: 460, textAlign: "center" }}>
        <div style={{ fontSize: 28, color: GOLD, marginBottom: 10 }}>Anti-Gomoku</div>
        <div style={{ fontFamily: "'DM Sans'", fontSize: 12, color: "#b99b64" }}>{message}</div>
      </div>
    </div>
  );
}
