from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from ..search import MATE_SCORE
from .data import (
    DATASET_KIND_LEGACY_POLICY_VALUE,
    DATASET_KIND_QUIET_VALUE_V1,
    load_dataset_kind,
)


def inspect_dataset(path: str | Path) -> dict[str, object]:
    resolved_path = Path(path)
    dataset_kind = load_dataset_kind(resolved_path)
    with np.load(resolved_path) as data:
        if dataset_kind == DATASET_KIND_QUIET_VALUE_V1:
            sample_count = int(np.asarray(data["four_states"]).shape[0])
            quiet_ratio = 1.0
            tactical_ratio = 0.0
        else:
            sample_count = int(np.asarray(data["features"]).shape[0])
            features = np.asarray(data["features"])
            winning = features[:, 4].sum(axis=(1, 2)) > 0
            forced = features[:, 6].sum(axis=(1, 2)) > 0
            safe_threat = features[:, 7].sum(axis=(1, 2)) > 0
            double_threat = features[:, 8].sum(axis=(1, 2)) > 0
            opp_winning = features[:, 9].sum(axis=(1, 2)) > 0
            opp_safe = features[:, 10].sum(axis=(1, 2)) > 0
            opp_double = features[:, 11].sum(axis=(1, 2)) > 0
            tactical = winning | forced | safe_threat | double_threat | opp_winning | opp_safe | opp_double
            tactical_ratio = float(tactical.mean()) if sample_count else 0.0
            quiet_ratio = 1.0 - tactical_ratio

        mate_like_ratio = 0.0
        if "scores" in data.files and sample_count:
            scores = np.asarray(data["scores"])
            mate_like_ratio = float((np.abs(scores) >= (MATE_SCORE - 1_000)).mean())

        search_depth_counts: dict[int, int] = {}
        if "search_depths" in data.files:
            unique, counts = np.unique(np.asarray(data["search_depths"]), return_counts=True)
            search_depth_counts = {
                int(depth): int(count)
                for depth, count in zip(unique.tolist(), counts.tolist(), strict=False)
            }

        canonical_duplicate_count = 0
        if "canonical_hashes" in data.files:
            hashes = np.asarray(data["canonical_hashes"])
            canonical_duplicate_count = int(len(hashes) - len(set(int(value) for value in hashes.tolist())))

    return {
        "dataset_kind": dataset_kind,
        "sample_count": sample_count,
        "quiet_ratio": quiet_ratio,
        "tactical_ratio": tactical_ratio,
        "mate_like_ratio": mate_like_ratio,
        "search_depth_counts": search_depth_counts,
        "canonical_duplicate_count": canonical_duplicate_count,
    }


def _format_report(summary: dict[str, object]) -> str:
    return "\n".join(
        [
            f"dataset_kind={summary['dataset_kind']}",
            f"samples={summary['sample_count']}",
            f"quiet_ratio={summary['quiet_ratio']:.3f}",
            f"tactical_ratio={summary['tactical_ratio']:.3f}",
            f"mate_like_ratio={summary['mate_like_ratio']:.3f}",
            f"search_depth_counts={summary['search_depth_counts']}",
            f"canonical_duplicate_count={summary['canonical_duplicate_count']}",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a Ukumog ML dataset.")
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args()
    print(_format_report(inspect_dataset(args.data)))


if __name__ == "__main__":
    main()
