from __future__ import annotations

import argparse
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, Subset

from .data import DATASET_KIND_QUIET_VALUE_V1, NPZQuietValueDataset
from .model import MODEL_KIND_MASK_VALUE_V1, ModelConfig, UkumogMaskValueNet


def _resolve_group_labels(dataset: NPZQuietValueDataset, split_group: str) -> tuple[np.ndarray | None, str]:
    if split_group == "position":
        return None, "position"
    if split_group == "canonical":
        labels = dataset.metadata.get("canonical_hashes")
        if labels is None:
            labels = dataset.metadata.get("canonical_group_ids")
        if labels is None:
            raise ValueError("dataset does not contain canonical position metadata")
        return np.asarray(labels), "canonical"
    if split_group == "game":
        labels = dataset.metadata.get("game_ids")
        if labels is None:
            raise ValueError("dataset does not contain game_ids metadata")
        return np.asarray(labels), "game"

    if "canonical_hashes" in dataset.metadata:
        return np.asarray(dataset.metadata["canonical_hashes"]), "canonical"
    if "canonical_group_ids" in dataset.metadata:
        return np.asarray(dataset.metadata["canonical_group_ids"]), "canonical"
    if "game_ids" in dataset.metadata:
        return np.asarray(dataset.metadata["game_ids"]), "game"
    return None, "position"


def _split_dataset_indices(
    dataset: NPZQuietValueDataset,
    rng: np.random.Generator,
    val_fraction: float,
    split_group: str,
) -> tuple[np.ndarray, np.ndarray, str]:
    indices = np.arange(len(dataset))
    group_labels, resolved_group = _resolve_group_labels(dataset, split_group)

    if group_labels is None:
        rng.shuffle(indices)
        val_size = max(1, int(round(len(indices) * val_fraction)))
        train_indices = indices[val_size:]
        val_indices = indices[:val_size]
        return train_indices, val_indices, resolved_group

    unique_groups = np.unique(group_labels)
    if len(unique_groups) < 2:
        rng.shuffle(indices)
        val_size = max(1, int(round(len(indices) * val_fraction)))
        train_indices = indices[val_size:]
        val_indices = indices[:val_size]
        return train_indices, val_indices, "position"

    shuffled_groups = unique_groups.copy()
    rng.shuffle(shuffled_groups)
    target_val_samples = max(1, int(round(len(indices) * val_fraction)))
    val_mask = np.zeros(len(dataset), dtype=np.bool_)

    for group in shuffled_groups[:-1]:
        val_mask |= group_labels == group
        if int(val_mask.sum()) >= target_val_samples:
            break

    if not val_mask.any():
        val_mask |= group_labels == shuffled_groups[0]

    train_indices = indices[~val_mask]
    val_indices = indices[val_mask]
    if len(train_indices) == 0 or len(val_indices) == 0:
        raise ValueError("group-aware split produced an empty train or validation partition")
    return train_indices, val_indices, resolved_group


def _sign_accuracy(prediction: torch.Tensor, target: torch.Tensor) -> float:
    signs_match = (prediction >= 0.0) == (target >= 0.0)
    return float(signs_match.float().mean().item())


def train_model(
    data_path: str | Path,
    output_path: str | Path,
    epochs: int = 12,
    batch_size: int = 128,
    learning_rate: float = 3e-4,
    weight_decay: float = 1e-4,
    val_fraction: float = 0.1,
    seed: int = 20260419,
    device: str | None = None,
    model_config: ModelConfig | None = None,
    lr_decay: float = 0.97,
    split_group: str = "auto",
) -> Path:
    rng = np.random.default_rng(seed)
    dataset = NPZQuietValueDataset(data_path)

    train_indices, val_indices, resolved_split_group = _split_dataset_indices(
        dataset,
        rng,
        val_fraction,
        split_group,
    )
    if len(train_indices) == 0:
        raise ValueError("training split is empty; use a larger dataset or smaller val_fraction")

    train_dataset = Subset(dataset, train_indices.tolist())
    val_dataset = Subset(NPZQuietValueDataset(data_path), val_indices.tolist())
    print(
        f"dataset split={resolved_split_group} train_samples={len(train_indices)} "
        f"val_samples={len(val_indices)}"
    )

    resolved_device = torch.device(device if device is not None else ("cuda" if torch.cuda.is_available() else "cpu"))
    pin_memory = resolved_device.type == "cuda"
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, pin_memory=pin_memory)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False, pin_memory=pin_memory)

    config = model_config if model_config is not None else ModelConfig()
    model = UkumogMaskValueNet(config).to(resolved_device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    scaler = torch.amp.GradScaler("cuda", enabled=resolved_device.type == "cuda")
    scheduler = torch.optim.lr_scheduler.ExponentialLR(optimizer, gamma=lr_decay)

    best_val_loss = float("inf")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    for epoch in range(1, epochs + 1):
        model.train()
        train_loss_total = 0.0
        train_sign_acc_total = 0.0
        train_batches = 0

        for batch in train_loader:
            four_states = batch["four_states"].to(resolved_device)
            five_states = batch["five_states"].to(resolved_device)
            value_target = batch["value_target"].to(resolved_device)

            optimizer.zero_grad(set_to_none=True)
            amp_context = (
                torch.autocast(device_type="cuda", enabled=True)
                if resolved_device.type == "cuda"
                else nullcontext()
            )
            with amp_context:
                value = model(four_states, five_states)
                loss = F.smooth_l1_loss(value.float(), value_target.float(), beta=0.10)

            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()

            train_loss_total += float(loss.item())
            train_sign_acc_total += _sign_accuracy(value.detach(), value_target)
            train_batches += 1

        model.eval()
        val_loss_total = 0.0
        val_sign_acc_total = 0.0
        val_batches = 0
        with torch.no_grad():
            for batch in val_loader:
                four_states = batch["four_states"].to(resolved_device)
                five_states = batch["five_states"].to(resolved_device)
                value_target = batch["value_target"].to(resolved_device)

                value = model(four_states, five_states)
                loss = F.smooth_l1_loss(value.float(), value_target.float(), beta=0.10)

                val_loss_total += float(loss.item())
                val_sign_acc_total += _sign_accuracy(value, value_target)
                val_batches += 1

        train_loss = train_loss_total / max(1, train_batches)
        train_sign_acc = train_sign_acc_total / max(1, train_batches)
        val_loss = val_loss_total / max(1, val_batches)
        val_sign_acc = val_sign_acc_total / max(1, val_batches)
        print(
            f"epoch {epoch}/{epochs} "
            f"train_loss={train_loss:.4f} train_sign_acc={train_sign_acc:.3f} "
            f"val_loss={val_loss:.4f} val_sign_acc={val_sign_acc:.3f}"
        )

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            torch.save(
                {
                    "model_kind": MODEL_KIND_MASK_VALUE_V1,
                    "dataset_kind": DATASET_KIND_QUIET_VALUE_V1,
                    "model_state": model.state_dict(),
                    "model_config": config.to_dict(),
                    "best_val_loss": best_val_loss,
                    "split_group": resolved_split_group,
                },
                output,
            )

        scheduler.step()

    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the Ukumog quiet-value evaluator.")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--val-fraction", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=20260419)
    parser.add_argument("--device", type=str, default=None)
    parser.add_argument("--accumulator-width", type=int, default=64)
    parser.add_argument("--hidden-width", type=int, default=32)
    parser.add_argument(
        "--lr-decay",
        type=float,
        default=0.97,
        help="Exponential per-epoch learning-rate decay. Default: 0.97.",
    )
    parser.add_argument(
        "--split-group",
        choices=("auto", "position", "game", "canonical"),
        default="auto",
        help="How to group samples before the train/validation split. Default: auto.",
    )
    args = parser.parse_args()

    config = ModelConfig(
        accumulator_width=args.accumulator_width,
        hidden_width=args.hidden_width,
    )
    checkpoint = train_model(
        data_path=args.data,
        output_path=args.output,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        weight_decay=args.weight_decay,
        val_fraction=args.val_fraction,
        seed=args.seed,
        device=args.device,
        model_config=config,
        lr_decay=args.lr_decay,
        split_group=args.split_group,
    )
    print(f"saved checkpoint to {checkpoint}")


if __name__ == "__main__":
    main()
