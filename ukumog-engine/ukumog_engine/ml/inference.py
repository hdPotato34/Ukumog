from __future__ import annotations

from pathlib import Path

import numpy as np
import torch

from ..masks import DEFAULT_MASKS, MaskTables
from ..position import Color, Position
from ..tactics import TacticalSnapshot
from .data import value_to_search_score
from .features import encode_position
from .model import ModelConfig, UkumogPolicyValueNet
from .symmetry import inverse_symmetry, transform_flat_mask, transform_planes


def _position_key(position: Position) -> tuple[int, int, int]:
    side_flag = 0 if position.side_to_move is Color.BLACK else 1
    return position.black_bits, position.white_bits, side_flag


class TorchPolicyValueEvaluator:
    def __init__(
        self,
        model: UkumogPolicyValueNet,
        device: str | torch.device | None = None,
        tables: MaskTables = DEFAULT_MASKS,
        value_scale: int = 6_000,
        policy_bonus_scale: int = 18_000,
        symmetry_ensemble: bool = False,
    ) -> None:
        resolved_device = torch.device(device if device is not None else ("cuda" if torch.cuda.is_available() else "cpu"))
        self.model = model.to(resolved_device)
        self.model.eval()
        self.device = resolved_device
        self.tables = tables
        self.value_scale = value_scale
        self.policy_bonus_scale = policy_bonus_scale
        self.symmetry_ensemble = symmetry_ensemble
        self.cache: dict[tuple[int, int, int], tuple[np.ndarray, float]] = {}

    @classmethod
    def from_checkpoint(
        cls,
        path: str | Path,
        device: str | torch.device | None = None,
        tables: MaskTables = DEFAULT_MASKS,
        value_scale: int = 6_000,
        policy_bonus_scale: int = 18_000,
        symmetry_ensemble: bool = False,
    ) -> "TorchPolicyValueEvaluator":
        checkpoint = torch.load(Path(path), map_location="cpu", weights_only=False)
        config = ModelConfig(**checkpoint["model_config"])
        model = UkumogPolicyValueNet(config)
        model.load_state_dict(checkpoint["model_state"])
        return cls(
            model=model,
            device=device,
            tables=tables,
            value_scale=value_scale,
            policy_bonus_scale=policy_bonus_scale,
            symmetry_ensemble=symmetry_ensemble,
        )

    def reset(self) -> None:
        self.cache = {}

    def evaluate(
        self,
        position: Position,
        snapshot: TacticalSnapshot | None = None,
        opponent_snapshot: TacticalSnapshot | None = None,
    ) -> int:
        _, value = self._predict(position, snapshot, opponent_snapshot)
        return value_to_search_score(value, self.value_scale)

    def move_priors(
        self,
        position: Position,
        moves: list[int] | tuple[int, ...],
        snapshot: TacticalSnapshot | None = None,
        opponent_snapshot: TacticalSnapshot | None = None,
    ) -> dict[int, int]:
        if not moves:
            return {}

        logits, _ = self._predict(position, snapshot, opponent_snapshot)
        move_indices = np.array(list(moves), dtype=np.int64)
        selected = logits[move_indices]
        selected = selected - float(selected.max())
        exp_scores = np.exp(selected)
        total = float(exp_scores.sum())
        if total <= 0.0:
            return {move: 0 for move in moves}

        bonuses: dict[int, int] = {}
        for move, probability in zip(move_indices.tolist(), (exp_scores / total).tolist(), strict=False):
            bonuses[move] = int(round(probability * self.policy_bonus_scale))
        return bonuses

    def _predict(
        self,
        position: Position,
        snapshot: TacticalSnapshot | None = None,
        opponent_snapshot: TacticalSnapshot | None = None,
    ) -> tuple[np.ndarray, float]:
        key = _position_key(position)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        features = encode_position(position, self.tables, snapshot, opponent_snapshot)
        if not self.symmetry_ensemble:
            batch = torch.from_numpy(features).unsqueeze(0).to(self.device)
            with torch.no_grad():
                policy_logits, value = self.model(batch)
            result = (
                policy_logits.squeeze(0).detach().cpu().numpy().astype(np.float32, copy=False),
                float(value.item()),
            )
            self.cache[key] = result
            return result

        policy_accum = np.zeros((121,), dtype=np.float32)
        value_accum = 0.0
        for symmetry in range(8):
            sym_features = transform_planes(features, symmetry)
            batch = torch.from_numpy(sym_features).unsqueeze(0).to(self.device)
            with torch.no_grad():
                policy_logits, value = self.model(batch)
            sym_policy = policy_logits.squeeze(0).detach().cpu().numpy().astype(np.float32, copy=False)
            restored_policy = transform_flat_mask(sym_policy, inverse_symmetry(symmetry)).astype(np.float32, copy=False)
            policy_accum += restored_policy
            value_accum += float(value.item())

        result = (policy_accum / 8.0, value_accum / 8.0)
        self.cache[key] = result
        return result
