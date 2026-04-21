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
DATASET_KIND_KEY = "dataset_kind"
DATASET_KIND_QUIET_VALUE_V1 = "quiet_value_v1"
DATASET_KIND_LEGACY_POLICY_VALUE = "legacy_policy_value_v0"


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


def _dataset_kind_array(dataset_kind: str) -> np.ndarray:
    return np.array(dataset_kind)


def _dataset_kind_from_loaded(data: np.lib.npyio.NpzFile) -> str:
    if DATASET_KIND_KEY in data.files:
        return str(np.asarray(data[DATASET_KIND_KEY]).item())
    if "features" in data.files:
        return DATASET_KIND_LEGACY_POLICY_VALUE
    if "four_states" in data.files and "five_states" in data.files:
        return DATASET_KIND_QUIET_VALUE_V1
    raise ValueError("unable to infer dataset kind from archive contents")


def load_dataset_kind(path: str | Path) -> str:
    with np.load(Path(path)) as data:
        return _dataset_kind_from_loaded(data)


def _default_metadata_array(name: str, size: int) -> np.ndarray:
    if name == "scores":
        return np.zeros(size, dtype=np.int32)
    if name == "search_depths":
        return np.full(size, -1, dtype=np.int16)
    if name == "game_ids":
        return np.arange(size, dtype=np.int32)
    if name == "plies":
        return np.full(size, -1, dtype=np.int16)
    if name == "canonical_group_ids":
        return np.arange(size, dtype=np.int32)
    if name == "canonical_hashes":
        return (np.arange(size, dtype=np.uint64) + np.uint64(1 << 63)).astype(np.uint64, copy=False)
    raise ValueError(f"no default metadata defined for append key {name!r}")


def _merge_dataset_arrays(
    output: Path,
    dataset_kind: str,
    core_arrays: dict[str, np.ndarray],
    *,
    extra_arrays: dict[str, np.ndarray] | None = None,
) -> None:
    arrays = {DATASET_KIND_KEY: _dataset_kind_array(dataset_kind), **core_arrays}
    if extra_arrays is not None:
        arrays.update(extra_arrays)
    np.savez_compressed(output, **arrays)


def _append_dataset_arrays(
    output: Path,
    dataset_kind: str,
    core_arrays: dict[str, np.ndarray],
    *,
    extra_arrays: dict[str, np.ndarray] | None = None,
) -> None:
    if not output.exists():
        _merge_dataset_arrays(output, dataset_kind, core_arrays, extra_arrays=extra_arrays)
        return

    appended = {**core_arrays}
    if extra_arrays is not None:
        appended.update(extra_arrays)

    with np.load(output) as existing:
        existing_kind = _dataset_kind_from_loaded(existing)
        if existing_kind != dataset_kind:
            raise ValueError(f"cannot append {dataset_kind} data to {existing_kind} dataset")

        sample_keys = [key for key in core_arrays if np.asarray(core_arrays[key]).ndim >= 1]
        if not sample_keys:
            raise ValueError("append requires at least one sample-shaped core array")
        sample_count = int(np.asarray(core_arrays[sample_keys[0]]).shape[0])
        existing_count = int(np.asarray(existing[sample_keys[0]]).shape[0])

        merged: dict[str, np.ndarray] = {DATASET_KIND_KEY: _dataset_kind_array(dataset_kind)}
        all_keys = (set(existing.files) | set(appended.keys())) - {DATASET_KIND_KEY}
        for key in sorted(all_keys):
            if key not in existing.files:
                existing_value = _default_metadata_array(key, existing_count)
            else:
                existing_value = np.asarray(existing[key])
            if key not in appended:
                appended_value = _default_metadata_array(key, sample_count)
            else:
                appended_value = np.asarray(appended[key])
            if existing_value.shape[1:] != appended_value.shape[1:]:
                raise ValueError(
                    f"cannot append dataset key {key!r} with incompatible shapes "
                    f"{existing_value.shape} and {appended_value.shape}"
                )
            merged[key] = np.concatenate((existing_value, appended_value), axis=0)

    np.savez_compressed(output, **merged)


def save_quiet_value_examples(
    path: str | Path,
    four_states: np.ndarray,
    five_states: np.ndarray,
    value_targets: np.ndarray,
    scores: np.ndarray | None = None,
    search_depths: np.ndarray | None = None,
    extra_arrays: dict[str, np.ndarray] | None = None,
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    core_arrays: dict[str, np.ndarray] = {
        "four_states": four_states.astype(np.uint8, copy=False),
        "five_states": five_states.astype(np.uint8, copy=False),
        "value_targets": value_targets.astype(np.float32, copy=False),
    }
    metadata: dict[str, np.ndarray] = {}
    if scores is not None:
        metadata["scores"] = scores.astype(np.int32, copy=False)
    if search_depths is not None:
        metadata["search_depths"] = search_depths.astype(np.int16, copy=False)
    if extra_arrays is not None:
        metadata.update(extra_arrays)
    _merge_dataset_arrays(output, DATASET_KIND_QUIET_VALUE_V1, core_arrays, extra_arrays=metadata)


def append_quiet_value_examples(
    path: str | Path,
    four_states: np.ndarray,
    five_states: np.ndarray,
    value_targets: np.ndarray,
    scores: np.ndarray | None = None,
    search_depths: np.ndarray | None = None,
    extra_arrays: dict[str, np.ndarray] | None = None,
) -> None:
    output = Path(path)
    core_arrays: dict[str, np.ndarray] = {
        "four_states": four_states.astype(np.uint8, copy=False),
        "five_states": five_states.astype(np.uint8, copy=False),
        "value_targets": value_targets.astype(np.float32, copy=False),
    }
    metadata: dict[str, np.ndarray] = {}
    if scores is not None:
        metadata["scores"] = scores.astype(np.int32, copy=False)
    if search_depths is not None:
        metadata["search_depths"] = search_depths.astype(np.int16, copy=False)
    if extra_arrays is not None:
        metadata.update(extra_arrays)
    _append_dataset_arrays(output, DATASET_KIND_QUIET_VALUE_V1, core_arrays, extra_arrays=metadata)


def save_examples(
    path: str | Path,
    features: np.ndarray,
    legal_masks: np.ndarray,
    policy_targets: np.ndarray,
    value_targets: np.ndarray,
    scores: np.ndarray | None = None,
    search_depths: np.ndarray | None = None,
    extra_arrays: dict[str, np.ndarray] | None = None,
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    core_arrays: dict[str, np.ndarray] = {
        "features": features.astype(np.float32, copy=False),
        "legal_masks": legal_masks.astype(np.bool_, copy=False),
        "policy_targets": policy_targets.astype(np.int64, copy=False),
        "value_targets": value_targets.astype(np.float32, copy=False),
    }
    metadata: dict[str, np.ndarray] = {}
    if scores is not None:
        metadata["scores"] = scores.astype(np.int32, copy=False)
    if search_depths is not None:
        metadata["search_depths"] = search_depths.astype(np.int16, copy=False)
    if extra_arrays is not None:
        metadata.update(extra_arrays)
    _merge_dataset_arrays(output, DATASET_KIND_LEGACY_POLICY_VALUE, core_arrays, extra_arrays=metadata)


def append_examples(
    path: str | Path,
    features: np.ndarray,
    legal_masks: np.ndarray,
    policy_targets: np.ndarray,
    value_targets: np.ndarray,
    scores: np.ndarray | None = None,
    search_depths: np.ndarray | None = None,
    extra_arrays: dict[str, np.ndarray] | None = None,
) -> None:
    output = Path(path)
    if not output.exists():
        save_examples(
            output,
            features,
            legal_masks,
            policy_targets,
            value_targets,
            scores=scores,
            search_depths=search_depths,
            extra_arrays=extra_arrays,
        )
        return

    with np.load(output) as existing:
        existing_kind = _dataset_kind_from_loaded(existing)
    if existing_kind != DATASET_KIND_LEGACY_POLICY_VALUE:
        raise ValueError(f"cannot append legacy policy-value data to {existing_kind} dataset")

    core_arrays: dict[str, np.ndarray] = {
        "features": features.astype(np.float32, copy=False),
        "legal_masks": legal_masks.astype(np.bool_, copy=False),
        "policy_targets": policy_targets.astype(np.int64, copy=False),
        "value_targets": value_targets.astype(np.float32, copy=False),
    }
    metadata: dict[str, np.ndarray] = {}
    if scores is not None:
        metadata["scores"] = scores.astype(np.int32, copy=False)
    if search_depths is not None:
        metadata["search_depths"] = search_depths.astype(np.int16, copy=False)
    if extra_arrays is not None:
        metadata.update(extra_arrays)
    _append_dataset_arrays(output, DATASET_KIND_LEGACY_POLICY_VALUE, core_arrays, extra_arrays=metadata)


class NPZQuietValueDataset(Dataset[dict[str, torch.Tensor]]):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        data = np.load(self.path)
        if _dataset_kind_from_loaded(data) != DATASET_KIND_QUIET_VALUE_V1:
            raise ValueError("dataset is not a quiet_value_v1 archive")

        self.four_states = data["four_states"].astype(np.uint8)
        self.five_states = data["five_states"].astype(np.uint8)
        self.value_targets = data["value_targets"].astype(np.float32)
        self.metadata: dict[str, np.ndarray] = {}

        if self.four_states.ndim != 2 or self.five_states.ndim != 2:
            raise ValueError("quiet-value states must be rank-2 arrays")
        if self.four_states.shape[0] == 0:
            raise ValueError("dataset is empty")
        if self.five_states.shape[0] != self.four_states.shape[0]:
            raise ValueError("four_states and five_states have different sample counts")
        if self.value_targets.shape != (self.four_states.shape[0],):
            raise ValueError("value_targets array has the wrong shape")

        standard_keys = {DATASET_KIND_KEY, "four_states", "five_states", "value_targets"}
        for key in data.files:
            if key in standard_keys:
                continue
            values = np.asarray(data[key])
            if values.shape and values.shape[0] != self.four_states.shape[0]:
                raise ValueError(f"metadata array {key!r} has the wrong leading dimension")
            self.metadata[key] = values

    def __len__(self) -> int:
        return int(self.four_states.shape[0])

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        return {
            "four_states": torch.from_numpy(self.four_states[index]),
            "five_states": torch.from_numpy(self.five_states[index]),
            "value_target": torch.tensor(self.value_targets[index], dtype=torch.float32),
        }


class NPZPositionDataset(Dataset[dict[str, torch.Tensor]]):
    def __init__(self, path: str | Path, symmetry_augment: bool = False) -> None:
        self.path = Path(path)
        data = np.load(self.path)
        if _dataset_kind_from_loaded(data) != DATASET_KIND_LEGACY_POLICY_VALUE:
            raise ValueError("dataset is not a legacy policy-value archive")

        self.features = data["features"].astype(np.float32)
        self.legal_masks = data["legal_masks"].astype(np.bool_)
        self.policy_targets = data["policy_targets"].astype(np.int64)
        self.value_targets = data["value_targets"].astype(np.float32)
        self.symmetry_augment = symmetry_augment
        self.metadata: dict[str, np.ndarray] = {}

        if self.features.ndim != 4:
            raise ValueError("features array must have shape [N, C, H, W]")
        if self.features.shape[0] == 0:
            raise ValueError("dataset is empty")
        if self.legal_masks.shape != (self.features.shape[0], BOARD_CELLS):
            raise ValueError("legal_masks array has the wrong shape")

        standard_keys = {DATASET_KIND_KEY, "features", "legal_masks", "policy_targets", "value_targets"}
        for key in data.files:
            if key in standard_keys:
                continue
            values = np.asarray(data[key])
            if values.shape and values.shape[0] != self.features.shape[0]:
                raise ValueError(f"metadata array {key!r} has the wrong leading dimension")
            self.metadata[key] = values

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
