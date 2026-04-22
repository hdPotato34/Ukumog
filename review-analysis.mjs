import { findDeepestMainlineNode, getNodePath } from "./game-record.mjs";

export function buildMainlineNodeIds(record) {
  return getNodePath(record, findDeepestMainlineNode(record)).slice(1);
}

export function nextMainlineNodeToAnalyze(record, analysisByNodeId = {}, analysisStatusByNodeId = {}, excludeNodeId = "") {
  return buildMainlineNodeIds(record).find((nodeId) => (
    nodeId !== excludeNodeId
    && !analysisByNodeId[nodeId]
    && (!analysisStatusByNodeId[nodeId] || analysisStatusByNodeId[nodeId] === "idle")
  )) || null;
}

export function formatAnalysisScore(analysis) {
  if (!analysis) return "";
  if (analysis.mate) return `#${analysis.mate}`;
  const score = Number(analysis.score);
  if (!Number.isFinite(score)) return "";
  return `${score >= 0 ? "+" : ""}${(score / 100).toFixed(1)}`;
}

export function analysisBarPercent(analysis) {
  if (!analysis) return 50;
  if (analysis.mate) return analysis.mate > 0 ? 100 : 0;
  const score = Number(analysis.score);
  if (!Number.isFinite(score)) return 50;
  const normalized = Math.max(-1, Math.min(1, score / 600));
  return ((normalized + 1) / 2) * 100;
}
