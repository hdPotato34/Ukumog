from __future__ import annotations

from pathlib import Path

import numpy as np
import torch

from ..incremental import IncrementalState
from ..masks import DEFAULT_MASKS, MaskTables
from ..position import Color, Position
from ..tactics import TacticalSnapshot
from .data import value_to_search_score
from .features import encode_position
from .mask_features import encode_mask_states
from .model import (
    MODEL_KIND_LEGACY_POLICY_VALUE,
    MODEL_KIND_MASK_VALUE_V1,
    LegacyModelConfig,
    ModelConfig,
    UkumogMaskValueNet,
    UkumogPolicyValueNet,
)
from .symmetry import inverse_symmetry, transform_flat_mask, transform_planes


def _position_key(position: Position) -> tuple[int, int, int]:
    side_flag = 0 if position.side_to_move is Color.BLACK else 1
    return position.black_bits, position.white_bits, side_flag


def _upgrade_legacy_state_dict(model_state: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
    upgraded: dict[str, torch.Tensor] = {}
    for key, value in model_state.items():
        if ".block.3.weight" in key and value.ndim == 4:
            upgraded[key.replace(".block.3.weight", ".block.4.weight")] = value
            continue
        if ".block.4.weight" in key and value.ndim == 1:
            upgraded[key.replace(".block.4.weight", ".block.5.weight")] = value
            continue
        if ".block.4.bias" in key and value.ndim == 1:
            upgraded[key.replace(".block.4.bias", ".block.5.bias")] = value
            continue
        upgraded[key] = value
    return upgraded


def _resolve_legacy_checkpoint_config(
    raw_config: dict[str, object],
    model_state: dict[str, torch.Tensor],
) -> LegacyModelConfig:
    resolved = dict(raw_config)

    if "head_mode" not in resolved:
        policy_final = model_state.get("policy_head.5.weight")
        if policy_final is not None and policy_final.ndim == 2:
            resolved["head_mode"] = "dense"
        else:
            policy_compact = model_state.get("policy_head.4.weight")
            if policy_compact is not None and policy_compact.ndim == 4:
                resolved["head_mode"] = "pooled"
            else:
                resolved["head_mode"] = "dense"

    if "policy_channels" not in resolved and "policy_head.0.weight" in model_state:
        resolved["policy_channels"] = int(model_state["policy_head.0.weight"].shape[0])
    if "value_channels" not in resolved and "value_head.0.weight" in model_state:
        resolved["value_channels"] = int(model_state["value_head.0.weight"].shape[0])
    if "trunk_dropout" not in resolved:
        resolved["trunk_dropout"] = 0.0
    if "head_dropout" not in resolved:
        resolved["head_dropout"] = 0.0

    return LegacyModelConfig(**resolved)


class TorchPolicyValueEvaluator:
    def __init__(
        self,
        model: torch.nn.Module,
        *,
        model_kind: str,
        device: str | torch.device | None = None,
        tables: MaskTables = DEFAULT_MASKS,
        value_scale: int = 6_000,
        policy_bonus_scale: int = 18_000,
        symmetry_ensemble: bool = False,
    ) -> None:
        resolved_device = torch.device(device if device is not None else ("cuda" if torch.cuda.is_available() else "cpu"))
        self.model = model.to(resolved_device)
        self.model.eval()
        self.model_kind = model_kind
        self.device = resolved_device
        self.tables = tables
        self.value_scale = value_scale
        self.policy_bonus_scale = policy_bonus_scale
        self.symmetry_ensemble = symmetry_ensemble
        self.supports_policy = model_kind != MODEL_KIND_MASK_VALUE_V1
        self.quiet_value_only = model_kind == MODEL_KIND_MASK_VALUE_V1
        self.cache: dict[tuple[int, int, int], tuple[np.ndarray | None, float]] = {}

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
        model_kind = str(checkpoint.get("model_kind", MODEL_KIND_LEGACY_POLICY_VALUE))

        if model_kind == MODEL_KIND_MASK_VALUE_V1:
            config = ModelConfig(**checkpoint["model_config"])
            model = UkumogMaskValueNet(config)
            model.load_state_dict(checkpoint["model_state"])
            return cls(
                model=model,
                model_kind=model_kind,
                device=device,
                tables=tables,
                value_scale=value_scale,
                policy_bonus_scale=policy_bonus_scale,
                symmetry_ensemble=False,
            )

        upgraded_state = _upgrade_legacy_state_dict(checkpoint["model_state"])
        config = _resolve_legacy_checkpoint_config(checkpoint["model_config"], upgraded_state)
        model = UkumogPolicyValueNet(config)
        model.load_state_dict(upgraded_state)
        return cls(
            model=model,
            model_kind=MODEL_KIND_LEGACY_POLICY_VALUE,
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
        incremental_state: IncrementalState | None = None,
    ) -> int:
        _, value = self._predict(position, snapshot, opponent_snapshot, incremental_state)
        return value_to_search_score(value, self.value_scale)

    def move_priors(
        self,
        position: Position,
        moves: list[int] | tuple[int, ...],
        snapshot: TacticalSnapshot | None = None,
        opponent_snapshot: TacticalSnapshot | None = None,
    ) -> dict[int, int]:
        if not moves or not self.supports_policy:
            return {}

        logits, _ = self._predict(position, snapshot, opponent_snapshot, None)
        if logits is None:
            return {}
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
        incremental_state: IncrementalState | None = None,
    ) -> tuple[np.ndarray | None, float]:
        key = _position_key(position)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        if self.model_kind == MODEL_KIND_MASK_VALUE_V1:
            resolved_state = incremental_state if incremental_state is not None else IncrementalState.from_position(position)
            four_states, five_states = encode_mask_states(position, resolved_state)
            four_tensor = torch.from_numpy(four_states).unsqueeze(0).to(self.device)
            five_tensor = torch.from_numpy(five_states).unsqueeze(0).to(self.device)
            with torch.no_grad():
                value = self.model(four_tensor, five_tensor)
            result = (None, float(value.item()))
            self.cache[key] = result
            return result

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
