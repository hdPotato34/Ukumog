function normalizeIntegerArray(values) {
  if (!Array.isArray(values)) {
    return [];
  }

  return values
    .map((value) => Number(value))
    .filter((value) => Number.isInteger(value) && value > 0)
    .sort((left, right) => left - right);
}

function normalizeRange(value) {
  const min = Number(value?.min);
  const max = Number(value?.max);
  return {
    min: Number.isFinite(min) ? min : null,
    max: Number.isFinite(max) ? max : null,
  };
}

export function normalizeEngineCapabilities(value = {}) {
  const source = value?.capabilities && typeof value.capabilities === "object"
    ? value.capabilities
    : value;

  return {
    supportedBoardSizes: normalizeIntegerArray(source?.supportedBoardSizes),
    timeBudgetMs: normalizeRange(source?.timeBudgetMs),
    maxDepth: normalizeRange(source?.maxDepth),
  };
}

export function supportsEngineBoardSize(capabilities, boardSize) {
  return normalizeEngineCapabilities(capabilities).supportedBoardSizes.includes(Number(boardSize));
}

export function formatSupportedBoardSizes(capabilities) {
  const supportedBoardSizes = normalizeEngineCapabilities(capabilities).supportedBoardSizes;
  if (!supportedBoardSizes.length) {
    return "no board sizes";
  }
  return supportedBoardSizes.map((size) => `${size}x${size}`).join(", ");
}
