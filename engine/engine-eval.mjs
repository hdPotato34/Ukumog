import { opp } from "../game-core.mjs";
import defaultEnginePack from "./engine-pack.default.json" with { type: "json" };
import { countNearbyStones, createPerspectiveState, listLegalMoves } from "./rules-adapter.mjs";
import { listImmediateWinningMoves } from "./engine-tactics.mjs";

export const DEFAULT_ENGINE_PACK = defaultEnginePack;

function mergeSearchConfig(search = {}) {
  return {
    ...DEFAULT_ENGINE_PACK.search,
    ...(search || {}),
  };
}

function mergeWeights(weights = {}) {
  return {
    ...DEFAULT_ENGINE_PACK.evaluation.weights,
    ...(weights || {}),
  };
}

export function normalizeEnginePack(enginePack = {}) {
  return {
    ...DEFAULT_ENGINE_PACK,
    ...(enginePack || {}),
    search: mergeSearchConfig(enginePack.search),
    evaluation: {
      ...DEFAULT_ENGINE_PACK.evaluation,
      ...(enginePack.evaluation || {}),
      weights: mergeWeights(enginePack.evaluation?.weights),
    },
    featureFlags: {
      ...DEFAULT_ENGINE_PACK.featureFlags,
      ...(enginePack.featureFlags || {}),
    },
  };
}

export function isMateScore(score, enginePack = DEFAULT_ENGINE_PACK) {
  return Math.abs(score) >= (normalizeEnginePack(enginePack).evaluation.mateScore - 512);
}

export function scoreToMatePly(score, enginePack = DEFAULT_ENGINE_PACK) {
  const pack = normalizeEnginePack(enginePack);
  if (!isMateScore(score, pack)) {
    return null;
  }
  const distance = Math.max(1, pack.evaluation.mateScore - Math.abs(score));
  return score > 0 ? distance : -distance;
}

export function terminalScoreForWinner(winner, perspective, enginePack = DEFAULT_ENGINE_PACK, ply = 0) {
  const pack = normalizeEnginePack(enginePack);
  if (!winner || !perspective) {
    return 0;
  }
  const signedScore = winner === perspective ? pack.evaluation.mateScore : -pack.evaluation.mateScore;
  return signedScore - Math.sign(signedScore) * ply;
}

function scanBoardFeatures(state, perspective) {
  const boardSize = state.board.length;
  const middle = (boardSize - 1) / 2;
  const enemy = opp(perspective);
  let friendlyAdjacency = 0;
  let opponentAdjacency = 0;
  let centerControl = 0;
  let opponentCenterControl = 0;
  let mobility = 0;
  let opponentMobility = 0;

  for (let row = 0; row < boardSize; row += 1) {
    for (let col = 0; col < boardSize; col += 1) {
      const cell = state.board[row][col];
      if (!cell) {
        const local = countNearbyStones(state, row, col, 1);
        mobility += local.friendly;
        mobility -= local.opponent;
        opponentMobility += local.opponent;
        opponentMobility -= local.friendly;
        continue;
      }

      const centerValue = boardSize - (Math.abs(row - middle) + Math.abs(col - middle));
      const localState = { ...state, turn: cell };
      const local = countNearbyStones(localState, row, col, 1);

      if (cell === perspective) {
        friendlyAdjacency += local.friendly;
        centerControl += centerValue;
      } else if (cell === enemy) {
        opponentAdjacency += local.friendly;
        opponentCenterControl += centerValue;
      }
    }
  }

  return {
    friendlyAdjacency,
    opponentAdjacency,
    centerControl,
    opponentCenterControl,
    mobility,
    opponentMobility,
  };
}

export function evaluateState(state, config, enginePack = DEFAULT_ENGINE_PACK, {
  perspective = state.turn,
} = {}) {
  const pack = normalizeEnginePack(enginePack);
  const weights = pack.evaluation.weights;

  if (state.result) {
    return terminalScoreForWinner(state.result.winner, perspective, pack, 0);
  }

  const currentState = state.turn === perspective ? state : createPerspectiveState(state, perspective);
  const opponentState = createPerspectiveState(currentState, opp(perspective));
  const boardFeatures = scanBoardFeatures(currentState, perspective);

  const immediateWins = listImmediateWinningMoves(currentState, config).length;
  const opponentImmediateWins = listImmediateWinningMoves(opponentState, config).length;
  const safeMoves = listLegalMoves(currentState, config).length;
  const opponentSafeMoves = listLegalMoves(opponentState, config).length;

  return (
    immediateWins * weights.immediateWin
    + opponentImmediateWins * weights.opponentImmediateWin
    + safeMoves * weights.safeMove
    + opponentSafeMoves * weights.opponentSafeMove
    + boardFeatures.friendlyAdjacency * weights.friendlyAdjacency
    + boardFeatures.opponentAdjacency * weights.opponentAdjacency
    + boardFeatures.centerControl * weights.centerControl
    + boardFeatures.opponentCenterControl * weights.opponentCenterControl
    + boardFeatures.mobility * weights.mobility
    + boardFeatures.opponentMobility * weights.opponentMobility
  );
}
