from __future__ import annotations

import contextlib
import io
import random
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import numpy as np
import torch

import play_cli
from tools import ml_match_suite
from ukumog_engine import Color, Position, SearchEngine
from ukumog_engine.ml.data import (
    DATASET_KIND_QUIET_VALUE_V1,
    DATASET_KIND_ROOT_POLICY_V1,
    NPZRootPolicyDataset,
    NPZQuietValueDataset,
    append_root_policy_examples,
    append_quiet_value_examples,
    load_dataset_kind,
    save_root_policy_examples,
    save_quiet_value_examples,
)
from ukumog_engine.ml.features import FEATURE_CHANNELS, encode_position
from ukumog_engine.ml.generate_data import _effective_search_budget, collect_selfplay_examples
from ukumog_engine.ml.generate_root_policy_data import collect_root_policy_examples
from ukumog_engine.ml.inference import TorchPolicyValueEvaluator
from ukumog_engine.ml.inspect_data import inspect_dataset
from ukumog_engine.ml.mask_features import (
    FIVE_MASK_COUNT,
    FOUR_MASK_COUNT,
    encode_mask_states,
)
from ukumog_engine.ml.model import (
    MODEL_KIND_MASK_VALUE_V1,
    MODEL_KIND_ROOT_POLICY_V1,
    LegacyModelConfig,
    ModelConfig,
    RootPolicyModelConfig,
    UkumogMaskValueNet,
    UkumogPolicyValueNet,
    UkumogRootPolicyNet,
)
from ukumog_engine.ml.symmetry import (
    canonical_position_hash,
    canonical_position_key,
    canonicalize_position,
    inverse_symmetry,
    transform_index,
    transform_position,
)
from ukumog_engine.ml.train import _split_dataset_indices, train_model
from ukumog_engine.ml.train_root_policy import train_root_policy_model
from ukumog_engine.tactics import analyze_tactics


class FakeEvaluator:
    def __init__(self, preferred_move: int) -> None:
        self.preferred_move = preferred_move
        self.supports_policy = True
        self.quiet_value_only = False

    def reset(self) -> None:
        return None

    def evaluate(self, position: Position, snapshot=None, opponent_snapshot=None) -> int:
        if position.occupied_bits & (1 << self.preferred_move):
            return -400_000
        return 0

    def move_priors(self, position: Position, moves: list[int], snapshot=None, opponent_snapshot=None) -> dict[int, int]:
        return {move: (200_000 if move == self.preferred_move else 0) for move in moves}


def _synthetic_quiet_arrays(sample_count: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    four_states = np.zeros((sample_count, FOUR_MASK_COUNT), dtype=np.uint8)
    five_states = np.zeros((sample_count, FIVE_MASK_COUNT), dtype=np.uint8)
    value_targets = np.linspace(-0.5, 0.5, sample_count, dtype=np.float32)
    for index in range(sample_count):
        four_states[index, index % FOUR_MASK_COUNT] = np.uint8((index % 3) + 1)
        five_states[index, index % FIVE_MASK_COUNT] = np.uint8((index % 5) + 1)
    return four_states, five_states, value_targets


def _synthetic_root_policy_arrays(sample_count: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    features = np.zeros((sample_count, FEATURE_CHANNELS, 11, 11), dtype=np.float32)
    legal_masks = np.zeros((sample_count, 121), dtype=np.bool_)
    policy_targets = np.zeros((sample_count,), dtype=np.int64)
    for index in range(sample_count):
        move = (60 + index) % 121
        features[index, 0, index % 11, (index * 2) % 11] = 1.0
        features[index, 2] = 1.0
        legal_masks[index, move] = True
        legal_masks[index, (move + 1) % 121] = True
        policy_targets[index] = move
    return features, legal_masks, policy_targets


class MLFeatureTests(unittest.TestCase):
    def test_encode_position_emits_expected_shape(self) -> None:
        rows = [
            "...........",
            "...........",
            "...........",
            "...........",
            ".....W.....",
            "....B......",
            "...........",
            "...........",
            "...........",
            "...........",
            "...........",
        ]
        position = Position.from_rows(rows, side_to_move=Color.BLACK)
        features = encode_position(position)
        self.assertEqual(features.shape, (FEATURE_CHANNELS, 11, 11))
        self.assertEqual(features.dtype, np.float32)
        self.assertEqual(float(features[0].sum()), 1.0)
        self.assertEqual(float(features[1].sum()), 1.0)

    def test_encode_mask_states_normalizes_side_to_move(self) -> None:
        black_position = Position.from_rows(
            [
                "...........",
                "...........",
                "...........",
                "...........",
                ".....W.....",
                "....B......",
                "...........",
                "...........",
                "...........",
                "...........",
                "...........",
            ],
            side_to_move=Color.BLACK,
        )
        white_position = Position(
            black_bits=black_position.white_bits,
            white_bits=black_position.black_bits,
            side_to_move=Color.WHITE,
        )

        black_four, black_five = encode_mask_states(black_position)
        white_four, white_five = encode_mask_states(white_position)

        self.assertTrue(np.array_equal(black_four, white_four))
        self.assertTrue(np.array_equal(black_five, white_five))

    def test_search_can_use_learned_evaluator_signal(self) -> None:
        rows = [
            "...........",
            "...........",
            "...........",
            "...........",
            "...........",
            ".....B.....",
            "...........",
            "...........",
            "...........",
            "...........",
            "...........",
        ]
        position = Position.from_rows(rows, side_to_move=Color.WHITE)
        safe_moves = analyze_tactics(position).safe_moves
        preferred_move = safe_moves[-1]
        engine = SearchEngine(learned_evaluator=FakeEvaluator(preferred_move), learned_eval_weight=1.0)
        result = engine.search(position, max_depth=1)
        self.assertEqual(result.best_move, preferred_move)
        self.assertGreater(result.stats.model_calls_total, 0)
        self.assertGreater(result.stats.model_calls_root, 0)
        self.assertIn("model_calls_total", result.to_dict()["stats"])
        self.assertIn("tactics_time_seconds", result.to_dict()["stats"])
        self.assertIn("ml calls=", result.format_summary())

    def test_search_root_analysis_is_deterministic(self) -> None:
        engine = SearchEngine()
        first = engine.search(Position.initial(), max_depth=1, analyze_root=True)
        second = engine.search(Position.initial(), max_depth=1, analyze_root=True)

        first_scores = [(entry.move, entry.score) for entry in first.root_move_scores]
        second_scores = [(entry.move, entry.score) for entry in second.root_move_scores]

        self.assertTrue(first_scores)
        self.assertEqual(first_scores, second_scores)
        self.assertEqual(first.root_move_scores[0].move, first.best_move)
        self.assertEqual(first.to_dict()["root_move_scores"][0]["move"], first.root_move_scores[0].move)


class MLDatasetTests(unittest.TestCase):
    def test_effective_search_budget_can_use_opening_override(self) -> None:
        self.assertEqual(
            _effective_search_budget(
                ply=2,
                base_depth=6,
                base_time_ms=1500,
                opening_plies=5,
                opening_depth=2,
                opening_time_ms=200,
            ),
            (2, 200),
        )
        self.assertEqual(
            _effective_search_budget(
                ply=6,
                base_depth=6,
                base_time_ms=1500,
                opening_plies=5,
                opening_depth=2,
                opening_time_ms=200,
            ),
            (6, 1500),
        )

    def test_quiet_value_dataset_round_trip(self) -> None:
        four_states, five_states, value_targets = _synthetic_quiet_arrays(2)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "tiny_quiet.npz"
            save_quiet_value_examples(
                path,
                four_states,
                five_states,
                value_targets,
                extra_arrays={
                    "game_ids": np.array([0, 1], dtype=np.int32),
                    "canonical_hashes": np.array([11, 22], dtype=np.uint64),
                },
            )
            dataset = NPZQuietValueDataset(path)
            dataset_kind = load_dataset_kind(path)

        self.assertEqual(len(dataset), 2)
        sample = dataset[0]
        self.assertEqual(sample["four_states"].shape[0], FOUR_MASK_COUNT)
        self.assertEqual(sample["five_states"].shape[0], FIVE_MASK_COUNT)
        self.assertIn("canonical_hashes", dataset.metadata)
        self.assertEqual(dataset_kind, DATASET_KIND_QUIET_VALUE_V1)

    def test_root_policy_dataset_round_trip(self) -> None:
        features, legal_masks, policy_targets = _synthetic_root_policy_arrays(2)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "tiny_root_policy.npz"
            save_root_policy_examples(
                path,
                features,
                legal_masks,
                policy_targets,
                best_scores=np.array([120, 90], dtype=np.int32),
                score_gaps=np.array([60, 55], dtype=np.int32),
                search_depths=np.array([6, 6], dtype=np.int16),
                extra_arrays={
                    "game_ids": np.array([0, 1], dtype=np.int32),
                    "canonical_hashes": np.array([33, 44], dtype=np.uint64),
                },
            )
            dataset = NPZRootPolicyDataset(path)
            dataset_kind = load_dataset_kind(path)

        self.assertEqual(len(dataset), 2)
        sample = dataset[0]
        self.assertEqual(sample["features"].shape, (FEATURE_CHANNELS, 11, 11))
        self.assertEqual(sample["legal_mask"].shape[0], 121)
        self.assertIn("canonical_hashes", dataset.metadata)
        self.assertEqual(dataset_kind, DATASET_KIND_ROOT_POLICY_V1)

    def test_append_quiet_value_examples_extends_existing_dataset(self) -> None:
        four_states, five_states, value_targets = _synthetic_quiet_arrays(1)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "appendable_quiet.npz"
            save_quiet_value_examples(
                path,
                four_states,
                five_states,
                value_targets,
                extra_arrays={
                    "game_ids": np.array([0], dtype=np.int32),
                    "canonical_hashes": np.array([np.uint64(11)], dtype=np.uint64),
                },
            )
            append_quiet_value_examples(
                path,
                four_states,
                five_states,
                value_targets,
                extra_arrays={
                    "game_ids": np.array([1], dtype=np.int32),
                    "canonical_hashes": np.array([np.uint64(22)], dtype=np.uint64),
                },
            )
            dataset = NPZQuietValueDataset(path)

        self.assertEqual(len(dataset), 2)
        self.assertEqual(dataset.metadata["game_ids"].tolist(), [0, 1])
        self.assertEqual(dataset.metadata["canonical_hashes"].tolist(), [11, 22])

    def test_append_root_policy_examples_extends_existing_dataset(self) -> None:
        features, legal_masks, policy_targets = _synthetic_root_policy_arrays(1)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "appendable_root_policy.npz"
            save_root_policy_examples(
                path,
                features,
                legal_masks,
                policy_targets,
                best_scores=np.array([120], dtype=np.int32),
                score_gaps=np.array([60], dtype=np.int32),
                search_depths=np.array([6], dtype=np.int16),
                extra_arrays={
                    "game_ids": np.array([0], dtype=np.int32),
                    "canonical_hashes": np.array([np.uint64(11)], dtype=np.uint64),
                },
            )
            append_root_policy_examples(
                path,
                features,
                legal_masks,
                np.array([(policy_targets[0] + 1) % 121], dtype=np.int64),
                best_scores=np.array([80], dtype=np.int32),
                score_gaps=np.array([55], dtype=np.int32),
                search_depths=np.array([5], dtype=np.int16),
                extra_arrays={
                    "game_ids": np.array([1], dtype=np.int32),
                    "canonical_hashes": np.array([np.uint64(22)], dtype=np.uint64),
                },
            )
            dataset = NPZRootPolicyDataset(path)

        self.assertEqual(len(dataset), 2)
        self.assertEqual(dataset.metadata["game_ids"].tolist(), [0, 1])
        self.assertEqual(dataset.metadata["canonical_hashes"].tolist(), [11, 22])

    def test_collect_selfplay_examples_generates_quiet_non_mate_samples(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "quiet_generate.npz"
            total = collect_selfplay_examples(
                games=2,
                seed=7,
                play_depth=1,
                label_depth=1,
                output_path=path,
                play_time_ms=0,
                label_time_ms=0,
                sample_every=1,
                sample_start_ply=2,
                max_positions=6,
                dedup="symmetry",
                append_output=False,
            )
            summary = inspect_dataset(path)
            dataset = NPZQuietValueDataset(path)

        self.assertGreaterEqual(total, 0)
        self.assertEqual(summary["dataset_kind"], DATASET_KIND_QUIET_VALUE_V1)
        self.assertEqual(summary["quiet_ratio"], 1.0)
        self.assertEqual(summary["mate_like_ratio"], 0.0)
        if len(dataset):
            self.assertTrue((np.abs(dataset.metadata["scores"]) < 999_000).all())

    def test_collect_selfplay_examples_can_append_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "incremental_quiet.npz"
            first_total = collect_selfplay_examples(
                games=1,
                seed=3,
                play_depth=1,
                label_depth=1,
                output_path=path,
                play_time_ms=0,
                label_time_ms=0,
                sample_every=1,
                sample_start_ply=2,
                max_positions=4,
                dedup="symmetry",
                append_output=True,
            )
            second_total = collect_selfplay_examples(
                games=1,
                seed=13,
                play_depth=1,
                label_depth=1,
                output_path=path,
                play_time_ms=0,
                label_time_ms=0,
                sample_every=1,
                sample_start_ply=2,
                max_positions=4,
                dedup="symmetry",
                append_output=True,
            )
            dataset = NPZQuietValueDataset(path)

        self.assertGreaterEqual(first_total, 0)
        self.assertGreaterEqual(second_total, 0)
        self.assertIn("canonical_hashes", dataset.metadata)
        self.assertEqual(len(set(dataset.metadata["canonical_hashes"].tolist())), len(dataset.metadata["canonical_hashes"]))

    def test_collect_root_policy_examples_can_append_output_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "incremental_root_policy.npz"
            first_total = collect_root_policy_examples(
                games=1,
                seed=3,
                play_depth=1,
                label_depth=1,
                output_path=path,
                play_time_ms=0,
                label_time_ms=0,
                sample_every=1,
                sample_start_ply=2,
                max_positions=4,
                min_candidate_moves=2,
                min_score_gap=0,
                max_score_gap=1_000_000,
                append_output=True,
            )
            second_total = collect_root_policy_examples(
                games=1,
                seed=3,
                play_depth=1,
                label_depth=1,
                output_path=path,
                play_time_ms=0,
                label_time_ms=0,
                sample_every=1,
                sample_start_ply=2,
                max_positions=4,
                min_candidate_moves=2,
                min_score_gap=0,
                max_score_gap=1_000_000,
                append_output=True,
            )
            dataset = NPZRootPolicyDataset(path)

        self.assertGreaterEqual(first_total, 0)
        self.assertGreaterEqual(second_total, 0)
        self.assertEqual(len(dataset), first_total + second_total)
        hashes = dataset.metadata["canonical_hashes"].tolist()
        self.assertEqual(len(set(hashes)), len(hashes))

    def test_collect_selfplay_examples_respects_samples_per_game(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "one_per_game.npz"
            total = collect_selfplay_examples(
                games=1,
                seed=17,
                play_depth=1,
                label_depth=1,
                output_path=path,
                play_time_ms=0,
                label_time_ms=0,
                sample_every=1,
                sample_start_ply=0,
                max_positions=8,
                dedup="symmetry",
                append_output=False,
                samples_per_game=1,
            )

        self.assertLessEqual(total, 1)

    def test_collect_selfplay_examples_can_stop_on_target_new_samples(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "target_stop.npz"
            total = collect_selfplay_examples(
                games=20,
                seed=23,
                play_depth=1,
                label_depth=1,
                output_path=path,
                play_time_ms=0,
                label_time_ms=0,
                sample_every=1,
                sample_start_ply=0,
                dedup="symmetry",
                append_output=False,
                target_new_samples=2,
                samples_per_game=2,
            )

        self.assertLessEqual(total, 2)


class MLInferenceTests(unittest.TestCase):
    def test_torch_evaluator_loads_mask_value_checkpoint_and_disables_policy(self) -> None:
        model = UkumogMaskValueNet(ModelConfig(accumulator_width=16, hidden_width=8))

        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_path = Path(tmpdir) / "mask_model.pt"
            torch.save(
                {
                    "model_kind": MODEL_KIND_MASK_VALUE_V1,
                    "dataset_kind": DATASET_KIND_QUIET_VALUE_V1,
                    "model_state": model.state_dict(),
                    "model_config": model.config.to_dict(),
                },
                checkpoint_path,
            )
            evaluator = TorchPolicyValueEvaluator.from_checkpoint(checkpoint_path, device="cpu")
            position = Position.initial()
            score = evaluator.evaluate(position)
            priors = evaluator.move_priors(position, [60])

        self.assertIsInstance(score, int)
        self.assertEqual(priors, {})
        self.assertFalse(evaluator.supports_policy)
        self.assertTrue(evaluator.quiet_value_only)

    def test_torch_evaluator_loads_root_policy_checkpoint_and_defaults_to_root_policy(self) -> None:
        model = UkumogRootPolicyNet(RootPolicyModelConfig(trunk_channels=16, residual_blocks=1, policy_channels=8))

        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_path = Path(tmpdir) / "root_policy.pt"
            torch.save(
                {
                    "model_kind": MODEL_KIND_ROOT_POLICY_V1,
                    "dataset_kind": DATASET_KIND_ROOT_POLICY_V1,
                    "model_state": model.state_dict(),
                    "model_config": model.config.to_dict(),
                },
                checkpoint_path,
            )
            evaluator = TorchPolicyValueEvaluator.from_checkpoint(checkpoint_path, device="cpu")
            priors = evaluator.move_priors(Position.initial(), [60, 61])
            score = evaluator.evaluate(Position.initial())

        self.assertIsInstance(score, int)
        self.assertTrue(evaluator.supports_policy)
        self.assertFalse(evaluator.quiet_value_only)
        self.assertEqual(evaluator.default_ml_mode, "root-policy")
        self.assertIn(60, priors)
        self.assertIn(61, priors)

    def test_torch_evaluator_loads_legacy_dense_checkpoint_config(self) -> None:
        model = UkumogPolicyValueNet(
            LegacyModelConfig(
                trunk_channels=16,
                residual_blocks=1,
                policy_channels=32,
                value_channels=32,
                value_hidden=32,
                trunk_dropout=0.0,
                head_dropout=0.0,
                head_mode="dense",
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_path = Path(tmpdir) / "legacy_model.pt"
            legacy_state: dict[str, torch.Tensor] = {}
            for key, value in model.state_dict().items():
                if ".block.4.weight" in key and value.ndim == 4:
                    legacy_state[key.replace(".block.4.weight", ".block.3.weight")] = value
                elif ".block.5.weight" in key and value.ndim == 1:
                    legacy_state[key.replace(".block.5.weight", ".block.4.weight")] = value
                elif ".block.5.bias" in key and value.ndim == 1:
                    legacy_state[key.replace(".block.5.bias", ".block.4.bias")] = value
                else:
                    legacy_state[key] = value
            torch.save(
                {
                    "model_state": legacy_state,
                    "model_config": {
                        "input_channels": FEATURE_CHANNELS,
                        "trunk_channels": 16,
                        "residual_blocks": 1,
                        "value_hidden": 32,
                        "norm_groups": 8,
                    },
                },
                checkpoint_path,
            )
            evaluator = TorchPolicyValueEvaluator.from_checkpoint(checkpoint_path, device="cpu")
            score = evaluator.evaluate(Position.initial())
            priors = evaluator.move_priors(Position.initial(), [60])

        self.assertIsInstance(score, int)
        self.assertIn(60, priors)
        self.assertTrue(evaluator.supports_policy)
        self.assertEqual(evaluator.default_ml_mode, "root-policy")

    def test_symmetry_helpers_round_trip_indices(self) -> None:
        move = 17
        for symmetry in range(8):
            transformed = transform_index(move, symmetry)
            restored = transform_index(transformed, inverse_symmetry(symmetry))
            self.assertEqual(restored, move)

    def test_canonical_position_key_is_symmetry_invariant(self) -> None:
        position = Position.from_rows(
            [
                "...........",
                "...........",
                "...........",
                "...........",
                ".....W.....",
                "....B......",
                "...........",
                "...........",
                "...........",
                "...........",
                "...........",
            ],
            side_to_move=Color.BLACK,
        )
        baseline_key = canonical_position_key(position)
        for symmetry in range(8):
            transformed = transform_position(position, symmetry)
            self.assertEqual(canonical_position_key(transformed), baseline_key)

        canonical_position, applied_symmetry = canonicalize_position(position)
        self.assertEqual(canonical_position_key(canonical_position), baseline_key)
        self.assertIsInstance(applied_symmetry, int)
        self.assertEqual(canonical_position_hash(position), canonical_position_hash(canonical_position))


class MLTrainingTests(unittest.TestCase):
    def test_split_dataset_indices_uses_canonical_hashes_without_leakage(self) -> None:
        four_states, five_states, value_targets = _synthetic_quiet_arrays(4)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "split_groups.npz"
            save_quiet_value_examples(
                path,
                four_states,
                five_states,
                value_targets,
                extra_arrays={
                    "game_ids": np.array([0, 0, 1, 1], dtype=np.int32),
                    "canonical_hashes": np.array([10, 10, 20, 20], dtype=np.uint64),
                },
            )
            dataset = NPZQuietValueDataset(path)
            train_indices, val_indices, resolved_group = _split_dataset_indices(
                dataset,
                np.random.default_rng(7),
                0.5,
                "canonical",
            )

        self.assertEqual(resolved_group, "canonical")
        train_groups = set(dataset.metadata["canonical_hashes"][train_indices].tolist())
        val_groups = set(dataset.metadata["canonical_hashes"][val_indices].tolist())
        self.assertTrue(train_groups.isdisjoint(val_groups))

    def test_train_model_saves_mask_value_checkpoint(self) -> None:
        four_states, five_states, value_targets = _synthetic_quiet_arrays(8)

        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = Path(tmpdir) / "train_quiet.npz"
            output_path = Path(tmpdir) / "mask_value.pt"
            save_quiet_value_examples(
                data_path,
                four_states,
                five_states,
                value_targets,
                extra_arrays={
                    "canonical_hashes": np.arange(8, dtype=np.uint64),
                },
            )
            checkpoint = train_model(
                data_path=data_path,
                output_path=output_path,
                epochs=1,
                batch_size=4,
                learning_rate=1e-3,
                model_config=ModelConfig(accumulator_width=16, hidden_width=8),
            )
            saved = torch.load(checkpoint, map_location="cpu", weights_only=False)

        self.assertEqual(checkpoint, output_path)
        self.assertEqual(saved["model_kind"], MODEL_KIND_MASK_VALUE_V1)
        self.assertEqual(saved["dataset_kind"], DATASET_KIND_QUIET_VALUE_V1)
        self.assertIn("best_val_loss", saved)

    def test_train_root_policy_model_saves_policy_checkpoint(self) -> None:
        features, legal_masks, policy_targets = _synthetic_root_policy_arrays(8)

        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = Path(tmpdir) / "train_root_policy.npz"
            output_path = Path(tmpdir) / "root_policy.pt"
            save_root_policy_examples(
                data_path,
                features,
                legal_masks,
                policy_targets,
                best_scores=np.arange(8, dtype=np.int32),
                score_gaps=np.full(8, 60, dtype=np.int32),
                search_depths=np.full(8, 6, dtype=np.int16),
                extra_arrays={"canonical_hashes": np.arange(8, dtype=np.uint64)},
            )
            checkpoint = train_root_policy_model(
                data_path=data_path,
                output_path=output_path,
                epochs=1,
                batch_size=4,
                learning_rate=1e-3,
                device="cpu",
                model_config=RootPolicyModelConfig(trunk_channels=16, residual_blocks=1, policy_channels=8),
            )
            saved = torch.load(checkpoint, map_location="cpu", weights_only=False)

        self.assertEqual(checkpoint, output_path)
        self.assertEqual(saved["model_kind"], MODEL_KIND_ROOT_POLICY_V1)
        self.assertEqual(saved["dataset_kind"], DATASET_KIND_ROOT_POLICY_V1)
        self.assertIn("best_val_loss", saved)


class DatasetInspectorTests(unittest.TestCase):
    def test_inspect_dataset_reports_quiet_value_summary(self) -> None:
        four_states, five_states, value_targets = _synthetic_quiet_arrays(3)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "inspect_quiet.npz"
            save_quiet_value_examples(
                path,
                four_states,
                five_states,
                value_targets,
                scores=np.array([100, -200, 300], dtype=np.int32),
                search_depths=np.array([6, 6, 5], dtype=np.int16),
                extra_arrays={"canonical_hashes": np.array([1, 2, 3], dtype=np.uint64)},
            )
            summary = inspect_dataset(path)

        self.assertEqual(summary["dataset_kind"], DATASET_KIND_QUIET_VALUE_V1)
        self.assertEqual(summary["sample_count"], 3)
        self.assertEqual(summary["quiet_ratio"], 1.0)
        self.assertEqual(summary["canonical_duplicate_count"], 0)
        self.assertEqual(summary["search_depth_counts"], {5: 1, 6: 2})

    def test_inspect_dataset_reports_root_policy_summary(self) -> None:
        features, legal_masks, policy_targets = _synthetic_root_policy_arrays(3)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "inspect_root_policy.npz"
            save_root_policy_examples(
                path,
                features,
                legal_masks,
                policy_targets,
                best_scores=np.array([100, -200, 300], dtype=np.int32),
                score_gaps=np.array([60, 75, 90], dtype=np.int32),
                search_depths=np.array([6, 6, 5], dtype=np.int16),
                extra_arrays={"canonical_hashes": np.array([1, 2, 3], dtype=np.uint64)},
            )
            summary = inspect_dataset(path)

        self.assertEqual(summary["dataset_kind"], DATASET_KIND_ROOT_POLICY_V1)
        self.assertEqual(summary["sample_count"], 3)
        self.assertEqual(summary["canonical_duplicate_count"], 0)
        self.assertEqual(summary["search_depth_counts"], {5: 1, 6: 2})


class CLITests(unittest.TestCase):
    def test_parse_args_supports_engine_vs_engine(self) -> None:
        args = play_cli.parse_args(
            [
                "--mode",
                "engine-vs-engine",
                "--games",
                "6",
                "--shuffle-colors",
                "--ml-mode",
                "quiet-value",
                "--black-depth",
                "2",
                "--white-depth",
                "3",
                "--black-time",
                "1.5",
                "--white-time",
                "2.5",
                "--max-moves",
                "20",
                "--temperature",
                "0.8",
                "--black-temperature",
                "0.4",
                "--sample-top-k",
                "5",
                "--seed",
                "7",
                "--seed-step",
                "3",
                "--symmetry-ensemble",
                "--white-symmetry-ensemble",
                "--white-ml-mode",
                "full",
                "--search-summary",
                "--time-trace",
                "--stats-jsonl",
                "logs/search.jsonl",
                "--device",
                "cpu",
            ]
        )
        self.assertEqual(args.mode, "engine-vs-engine")
        self.assertEqual(args.games, 6)
        self.assertTrue(args.shuffle_colors)
        self.assertEqual(args.ml_mode, "quiet-value")
        self.assertEqual(args.learned_weight, 0.10)
        self.assertEqual(args.device, "cpu")
        self.assertEqual(args.black_depth, 2)
        self.assertEqual(args.white_depth, 3)
        self.assertEqual(args.black_time, 1.5)
        self.assertEqual(args.white_time, 2.5)
        self.assertEqual(args.max_moves, 20)
        self.assertEqual(args.temperature, 0.8)
        self.assertEqual(args.black_temperature, 0.4)
        self.assertEqual(args.sample_top_k, 5)
        self.assertEqual(args.seed, 7)
        self.assertEqual(args.seed_step, 3)
        self.assertTrue(args.symmetry_ensemble)
        self.assertTrue(args.white_symmetry_ensemble)
        self.assertEqual(args.white_ml_mode, "full")
        self.assertTrue(args.search_summary)
        self.assertTrue(args.time_trace)
        self.assertEqual(args.stats_jsonl, Path("logs/search.jsonl"))

    def test_build_engine_controller_auto_resolves_mode_and_device(self) -> None:
        model = UkumogRootPolicyNet(RootPolicyModelConfig(trunk_channels=16, residual_blocks=1, policy_channels=8))

        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_path = Path(tmpdir) / "root_policy.pt"
            torch.save(
                {
                    "model_kind": MODEL_KIND_ROOT_POLICY_V1,
                    "dataset_kind": DATASET_KIND_ROOT_POLICY_V1,
                    "model_state": model.state_dict(),
                    "model_config": model.config.to_dict(),
                },
                checkpoint_path,
            )
            controller = play_cli._build_engine_controller(
                color=Color.BLACK,
                model_path=checkpoint_path,
                ml_mode="auto",
                device="cpu",
                depth=1,
                time_seconds=0.0,
                learned_weight=0.10,
                temperature=0.0,
                symmetry_ensemble=False,
            )

        self.assertEqual(controller.ml_mode, "root-policy")
        self.assertEqual(controller.device, "cpu")
        self.assertEqual(controller.engine.learned_policy_max_ply, 0)
        self.assertEqual(controller.engine.learned_value_max_ply, -1)
        self.assertEqual(controller.learned_weight, 0.0)
        self.assertEqual(controller.engine.learned_evaluator.device.type, "cpu")

    def test_append_stats_record_writes_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "stats" / "search.jsonl"
            play_cli._append_stats_record(output_path, {"event": "search", "depth": 3})
            contents = output_path.read_text(encoding="utf-8").strip()

        self.assertEqual(contents, '{"depth": 3, "event": "search"}')

    def test_choose_engine_move_supports_temperature_root_sampling(self) -> None:
        controller = play_cli._build_engine_controller(
            color=Color.BLACK,
            model_path=None,
            ml_mode="quiet-value",
            device="cpu",
            depth=1,
            time_seconds=0.0,
            learned_weight=0.0,
            temperature=0.8,
            symmetry_ensemble=False,
        )

        move, search_result, sampled = play_cli._choose_engine_move(
            position=Position.initial(),
            controller=controller,
            plies_played=0,
            temperature_plies=8,
            sample_top_k=4,
            rng=random.Random(11),
        )

        self.assertIsNotNone(move)
        self.assertIsNotNone(search_result.best_move)
        self.assertIsInstance(sampled, bool)

    def test_time_trace_helpers_accumulate_and_format(self) -> None:
        controller = play_cli._build_engine_controller(
            color=Color.BLACK,
            model_path=None,
            ml_mode="quiet-value",
            device="cpu",
            depth=1,
            time_seconds=0.0,
            learned_weight=0.0,
            temperature=0.0,
            symmetry_ensemble=False,
        )
        _, search_result, _ = play_cli._choose_engine_move(
            position=Position.initial(),
            controller=controller,
            plies_played=0,
            temperature_plies=0,
            sample_top_k=1,
            rng=random.Random(1),
        )

        play_cli._record_search_totals(controller, search_result)
        trace = play_cli._format_time_trace(controller, search_result)

        self.assertEqual(controller.searches_run, 1)
        self.assertIn("search=", trace)
        self.assertIn("cum_search=", trace)
        self.assertIn("breakdown", trace)

    def test_run_engine_batch_supports_summary_mode(self) -> None:
        args = play_cli.parse_args(
            [
                "--mode",
                "engine-vs-engine",
                "--games",
                "2",
                "--shuffle-colors",
                "--depth",
                "1",
                "--time",
                "0",
                "--max-moves",
                "1",
            ]
        )
        engine_a = play_cli._engine_spec_for_color(args, Color.BLACK, "Engine A")
        engine_b = play_cli._engine_spec_for_color(args, Color.WHITE, "Engine B")
        result = play_cli._run_engine_batch(args, engine_a, engine_b)
        self.assertEqual(result, 0)

    def test_main_human_vs_engine_runs_engine_turn_without_budget_type_errors(self) -> None:
        stdout = io.StringIO()
        argv = [
            "play_cli.py",
            "--mode",
            "human-vs-engine",
            "--human",
            "white",
            "--depth",
            "1",
            "--time",
            "0",
        ]

        with (
            mock.patch("sys.argv", argv),
            mock.patch("builtins.input", side_effect=["q"]),
            contextlib.redirect_stdout(stdout),
        ):
            result = play_cli.main()

        output = stdout.getvalue()
        self.assertEqual(result, 0)
        self.assertIn("Black PureSearch thinking...", output)
        self.assertIn("Black PureSearch chooses", output)


class MatchSuiteTests(unittest.TestCase):
    def test_match_suite_is_reproducible_for_paired_colors(self) -> None:
        candidate = play_cli.EngineSpec(
            name="Candidate",
            model_path=None,
            ml_mode="auto",
            device="cpu",
            depth=1,
            time_seconds=0.0,
            learned_weight=0.0,
            temperature=0.0,
            symmetry_ensemble=False,
        )
        baseline = play_cli.EngineSpec(
            name="Baseline",
            model_path=None,
            ml_mode="auto",
            device="cpu",
            depth=1,
            time_seconds=0.0,
            learned_weight=0.0,
            temperature=0.0,
            symmetry_ensemble=False,
        )
        suite = [ml_match_suite.SuitePosition(name="initial", position=Position.initial())]

        first = ml_match_suite.run_match_suite(
            candidate,
            baseline,
            suite_positions=suite,
            time_controls=(0.0,),
            max_moves=1,
        )
        second = ml_match_suite.run_match_suite(
            candidate,
            baseline,
            suite_positions=suite,
            time_controls=(0.0,),
            max_moves=1,
        )

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
