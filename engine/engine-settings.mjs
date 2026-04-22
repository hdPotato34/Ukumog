const STORAGE_KEY = "hd.engine.settings.v1";
const TIME_BUDGET_STEP_MS = 5;

export const ENGINE_TIME_BUDGET_MIN_MS = 25;
export const ENGINE_TIME_BUDGET_MAX_MS = 5000;
export const ENGINE_DEPTH_MIN = 1;
export const ENGINE_DEPTH_MAX = 12;

export const DEFAULT_PLAY_ENGINE_SETTINGS = {
  timedTimeBudgetMs: 60,
  untimedTimeBudgetMs: 45,
  maxDepth: 4,
};

export const DEFAULT_REVIEW_FOCUS_ENGINE_SETTINGS = {
  timeBudgetMs: 220,
  maxDepth: 5,
};

export const DEFAULT_REVIEW_BACKGROUND_ENGINE_SETTINGS = {
  timeBudgetMs: 140,
  maxDepth: 4,
};

export const DEFAULT_ENGINE_SETTINGS = {
  play: DEFAULT_PLAY_ENGINE_SETTINGS,
  reviewFocus: DEFAULT_REVIEW_FOCUS_ENGINE_SETTINGS,
  reviewBackground: DEFAULT_REVIEW_BACKGROUND_ENGINE_SETTINGS,
};

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function roundToStep(value, step) {
  return Math.round(value / step) * step;
}

function parseFiniteNumber(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

export function clampTimeBudgetMs(value, fallback = DEFAULT_REVIEW_FOCUS_ENGINE_SETTINGS.timeBudgetMs) {
  const numeric = parseFiniteNumber(value);
  const baseline = numeric === null ? fallback : numeric;
  return clamp(
    roundToStep(baseline, TIME_BUDGET_STEP_MS),
    ENGINE_TIME_BUDGET_MIN_MS,
    ENGINE_TIME_BUDGET_MAX_MS,
  );
}

export function clampMaxDepth(value, fallback = DEFAULT_REVIEW_FOCUS_ENGINE_SETTINGS.maxDepth) {
  const numeric = parseFiniteNumber(value);
  const baseline = numeric === null ? fallback : numeric;
  return clamp(Math.round(baseline), ENGINE_DEPTH_MIN, ENGINE_DEPTH_MAX);
}

export function sanitizePlayEngineSettings(value = {}) {
  return {
    timedTimeBudgetMs: clampTimeBudgetMs(value?.timedTimeBudgetMs, DEFAULT_PLAY_ENGINE_SETTINGS.timedTimeBudgetMs),
    untimedTimeBudgetMs: clampTimeBudgetMs(value?.untimedTimeBudgetMs, DEFAULT_PLAY_ENGINE_SETTINGS.untimedTimeBudgetMs),
    maxDepth: clampMaxDepth(value?.maxDepth, DEFAULT_PLAY_ENGINE_SETTINGS.maxDepth),
  };
}

export function sanitizeReviewEngineSettings(value = {}, defaults = DEFAULT_REVIEW_FOCUS_ENGINE_SETTINGS) {
  return {
    timeBudgetMs: clampTimeBudgetMs(value?.timeBudgetMs, defaults.timeBudgetMs),
    maxDepth: clampMaxDepth(value?.maxDepth, defaults.maxDepth),
  };
}

export function sanitizeEngineSettings(value = {}) {
  return {
    play: sanitizePlayEngineSettings(value?.play),
    reviewFocus: sanitizeReviewEngineSettings(value?.reviewFocus, DEFAULT_REVIEW_FOCUS_ENGINE_SETTINGS),
    reviewBackground: sanitizeReviewEngineSettings(value?.reviewBackground, DEFAULT_REVIEW_BACKGROUND_ENGINE_SETTINGS),
  };
}

export function resolveGameplayRequestSettings(config = {}, playSettings = null) {
  const cleanSettings = sanitizePlayEngineSettings(playSettings || DEFAULT_PLAY_ENGINE_SETTINGS);
  return {
    timeBudgetMs: config?.baseSeconds === null
      ? cleanSettings.untimedTimeBudgetMs
      : cleanSettings.timedTimeBudgetMs,
    maxDepth: cleanSettings.maxDepth,
  };
}

export function hasLocalStorage() {
  return typeof window !== "undefined" && !!window.localStorage;
}

export function loadStoredEngineSettings() {
  if (!hasLocalStorage()) {
    return sanitizeEngineSettings();
  }

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return sanitizeEngineSettings();
    }
    return sanitizeEngineSettings(JSON.parse(raw));
  } catch {
    return sanitizeEngineSettings();
  }
}

export function saveStoredEngineSettings(settings) {
  const cleanSettings = sanitizeEngineSettings(settings);
  if (!hasLocalStorage()) {
    return cleanSettings;
  }

  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(cleanSettings));
  } catch {
    // Ignore storage write failures and keep the sanitized in-memory settings.
  }
  return cleanSettings;
}
