from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch
import play_cli

from ukumog_engine import Color, Position, SearchEngine
from ukumog_engine.ml.data import NPZPositionDataset, save_examples
from ukumog_engine.ml.features import FEATURE_CHANNELS, encode_position
from ukumog_engine.ml.inference import TorchPolicyValueEvaluator
from ukumog_engine.ml.model import ModelConfig, UkumogPolicyValueNet
from ukumog_engine.ml.symmetry import inverse_symmetry, transform_index
from ukumog_engine.tactics import analyze_tactics


class FakeEvaluator:
    def __init__(self, preferred_move: int) -> None:
        self.preferred_move = preferred_move

    def reset(self) -> None:
        return None

    def evaluate(self, position: Position, snapshot=None, opponent_snapshot=None) -> int:
        if position.occupied_bits & (1 << self.preferred_move):
            return -400_000
        return 0

    def move_priors(self, position: Position, moves: list[int], snapshot=None, opponent_snapshot=None) -> dict[int, int]:
        return {move: (200_000 if move == self.preferred_move else 0) for move in moves}


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


class MLDatasetTests(unittest.TestCase):
    def test_npz_dataset_round_trip(self) -> None:
        position = Position.initial()
        features = np.stack([encode_position(position)])
        legal_masks = np.zeros((1, 121), dtype=np.bool_)
        legal_masks[0] = True
        policy_targets = np.array([60], dtype=np.int64)
        value_targets = np.array([0.0], dtype=np.float32)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "tiny.npz"
            save_examples(path, features, legal_masks, policy_targets, value_targets)
            dataset = NPZPositionDataset(path)
            sample = dataset[0]

        self.assertEqual(sample["features"].shape, torch.Size([FEATURE_CHANNELS, 11, 11]))
        self.assertTrue(bool(sample["legal_mask"].all()))
        self.assertEqual(int(sample["policy_target"].item()), 60)

    def test_symmetry_augmented_dataset_keeps_target_legal(self) -> None:
        position = Position.initial()
        features = np.stack([encode_position(position)])
        legal_masks = np.zeros((1, 121), dtype=np.bool_)
        legal_masks[0, 17] = True
        policy_targets = np.array([17], dtype=np.int64)
        value_targets = np.array([0.0], dtype=np.float32)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "tiny.npz"
            save_examples(path, features, legal_masks, policy_targets, value_targets)
            dataset = NPZPositionDataset(path, symmetry_augment=True)
            sample = dataset[0]

        transformed_target = int(sample["policy_target"].item())
        self.assertTrue(bool(sample["legal_mask"][transformed_target].item()))


class MLInferenceTests(unittest.TestCase):
    def test_torch_evaluator_loads_checkpoint_and_scores(self) -> None:
        model = UkumogPolicyValueNet(ModelConfig(trunk_channels=16, residual_blocks=1, value_hidden=32))

        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_path = Path(tmpdir) / "model.pt"
            torch.save(
                {
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
        self.assertIn(60, priors)

    def test_symmetry_helpers_round_trip_indices(self) -> None:
        move = 17
        for symmetry in range(8):
            transformed = transform_index(move, symmetry)
            restored = transform_index(transformed, inverse_symmetry(symmetry))
            self.assertEqual(restored, move)


class CLITests(unittest.TestCase):
    def test_parse_args_supports_engine_vs_engine(self) -> None:
        args = play_cli.parse_args(
            [
                "--mode",
                "engine-vs-engine",
                "--ml-mode",
                "root-policy",
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
                "--symmetry-ensemble",
                "--white-symmetry-ensemble",
                "--white-ml-mode",
                "full",
                "--search-summary",
                "--time-trace",
                "--stats-jsonl",
                "logs/search.jsonl",
            ]
        )
        self.assertEqual(args.mode, "engine-vs-engine")
        self.assertEqual(args.ml_mode, "root-policy")
        self.assertEqual(args.black_depth, 2)
        self.assertEqual(args.white_depth, 3)
        self.assertEqual(args.black_time, 1.5)
        self.assertEqual(args.white_time, 2.5)
        self.assertEqual(args.max_moves, 20)
        self.assertEqual(args.temperature, 0.8)
        self.assertEqual(args.black_temperature, 0.4)
        self.assertEqual(args.sample_top_k, 5)
        self.assertEqual(args.seed, 7)
        self.assertTrue(args.symmetry_ensemble)
        self.assertTrue(args.white_symmetry_ensemble)
        self.assertEqual(args.white_ml_mode, "full")
        self.assertTrue(args.search_summary)
        self.assertTrue(args.time_trace)
        self.assertEqual(args.stats_jsonl, Path("logs/search.jsonl"))

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
            ml_mode="root-policy",
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
            ml_mode="root-policy",
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


if __name__ == "__main__":
    unittest.main()
