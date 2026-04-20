from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
from torch.utils.data import Dataset

from ..board import BOARD_CELLS
from ..search import MATE_SCORE
from .symmetry import transform_flat_mask, transform_index, transform_planes

VALUE_SCORE_CLIP = 20_000.0
VALUE_SCORE_SCALE = 4_000.0


def score_to_value_target(score: int) -> float:
    if score >= MATE_SCORE - 1_000:
        return 1.0
    if score <= -MATE_SCORE + 1_000:
        return -1.0
    clipped = max(-VALUE_SCORE_CLIP, min(VALUE_SCORE_CLIP, float(score)))
    return float(np.tanh(clipped / VALUE_SCORE_SCALE))


def value_to_search_score(value: float, scale: int = 6_000) -> int:
    clipped = max(-1.0, min(1.0, float(value)))
    return int(round(clipped * scale))


def save_examples(
    path: str | Path,
    features: np.ndarray,
    legal_masks: np.ndarray,
    policy_targets: np.ndarray,
    value_targets: np.ndarray,
    scores: np.ndarray | None = None,
    search_depths: np.ndarray | None = None,
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    arrays: dict[str, np.ndarray] = {
        "features": features.astype(np.float32, copy=False),
        "legal_masks": legal_masks.astype(np.bool_, copy=False),
        "policy_targets": policy_targets.astype(np.int64, copy=False),
        "value_targets": value_targets.astype(np.float32, copy=False),
    }
    if scores is not None:
        arrays["scores"] = scores.astype(np.int32, copy=False)
    if search_depths is not None:
        arrays["search_depths"] = search_depths.astype(np.int16, copy=False)

    np.savez_compressed(output, **arrays)


class NPZPositionDataset(Dataset[dict[str, torch.Tensor]]):
    def __init__(self, path: str | Path, symmetry_augment: bool = False) -> None:
        data = np.load(Path(path))
        self.features = data["features"].astype(np.float32)
        self.legal_masks = data["legal_masks"].astype(np.bool_)
        self.policy_targets = data["policy_targets"].astype(np.int64)
        self.value_targets = data["value_targets"].astype(np.float32)
        self.symmetry_augment = symmetry_augment

        if self.features.ndim != 4:
            raise ValueError("features array must have shape [N, C, H, W]")
        if self.features.shape[0] == 0:
            raise ValueError("dataset is empty")
        if self.legal_masks.shape != (self.features.shape[0], BOARD_CELLS):
            raise ValueError("legal_masks array has the wrong shape")

    def __len__(self) -> int:
        return int(self.features.shape[0])

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        features = self.features[index]
        legal_mask = self.legal_masks[index]
        policy_target = int(self.policy_targets[index])
        if self.symmetry_augment:
            symmetry = int(np.random.randint(0, 8))
            features = transform_planes(features, symmetry)
            legal_mask = transform_flat_mask(legal_mask, symmetry).astype(np.bool_, copy=False)
            policy_target = transform_index(policy_target, symmetry)

        return {
            "features": torch.from_numpy(features),
            "legal_mask": torch.from_numpy(legal_mask),
            "policy_target": torch.tensor(policy_target, dtype=torch.long),
            "value_target": torch.tensor(self.value_targets[index], dtype=torch.float32),
        }
