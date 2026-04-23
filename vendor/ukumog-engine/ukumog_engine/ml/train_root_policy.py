from __future__ import annotations

import argparse
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, Subset

from .data import DATASET_KIND_ROOT_POLICY_V1, NPZRootPolicyDataset
from .model import MODEL_KIND_ROOT_POLICY_V1, RootPolicyModelConfig, UkumogRootPolicyNet
from .train import _split_dataset_indices


def _resolve_training_device(device: str | None) -> torch.device:
    requested = "auto" if device is None else device
    if requested == "auto":
        requested = "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        requested = "cpu"
    return torch.device(requested)


def _masked_logits(logits: torch.Tensor, legal_mask: torch.Tensor) -> torch.Tensor:
    min_value = torch.finfo(logits.dtype).min
    return logits.masked_fill(~legal_mask, min_value)


def _policy_accuracy(logits: torch.Tensor, legal_mask: torch.Tensor, target: torch.Tensor) -> float:
    prediction = _masked_logits(logits, legal_mask).argmax(dim=1)
    return float((prediction == target).float().mean().item())


def train_root_policy_model(
    data_path: str | Path,
    output_path: str | Path,
    epochs: int = 12,
    batch_size: int = 128,
    learning_rate: float = 3e-4,
    weight_decay: float = 1e-4,
    val_fraction: float = 0.1,
    seed: int = 20260421,
    device: str | None = None,
    model_config: RootPolicyModelConfig | None = None,
    lr_decay: float = 0.97,
    split_group: str = "auto",
) -> Path:
    rng = np.random.default_rng(seed)
    dataset = NPZRootPolicyDataset(data_path, symmetry_augment=False)
    train_indices, val_indices, resolved_split_group = _split_dataset_indices(
        dataset,
        rng,
        val_fraction,
        split_group,
    )
    if len(train_indices) == 0:
        raise ValueError("training split is empty; use a larger dataset or smaller val_fraction")

    train_dataset = Subset(NPZRootPolicyDataset(data_path, symmetry_augment=True), train_indices.tolist())
    val_dataset = Subset(NPZRootPolicyDataset(data_path, symmetry_augment=False), val_indices.tolist())
    print(
        f"dataset split={resolved_split_group} train_samples={len(train_indices)} "
        f"val_samples={len(val_indices)}"
    )

    resolved_device = _resolve_training_device(device)
    pin_memory = resolved_device.type == "cuda"
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, pin_memory=pin_memory)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False, pin_memory=pin_memory)

    config = model_config if model_config is not None else RootPolicyModelConfig()
    model = UkumogRootPolicyNet(config).to(resolved_device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    scaler = torch.amp.GradScaler("cuda", enabled=resolved_device.type == "cuda")
    scheduler = torch.optim.lr_scheduler.ExponentialLR(optimizer, gamma=lr_decay)

    best_val_loss = float("inf")
    best_val_accuracy = 0.0
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    for epoch in range(1, epochs + 1):
        model.train()
        train_loss_total = 0.0
        train_acc_total = 0.0
        train_batches = 0

        for batch in train_loader:
            features = batch["features"].to(resolved_device)
            legal_mask = batch["legal_mask"].to(resolved_device)
            policy_target = batch["policy_target"].to(resolved_device)

            optimizer.zero_grad(set_to_none=True)
            amp_context = (
                torch.autocast(device_type="cuda", enabled=True)
                if resolved_device.type == "cuda"
                else nullcontext()
            )
            with amp_context:
                logits = model(features)
                loss = F.cross_entropy(_masked_logits(logits, legal_mask), policy_target)

            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()

            train_loss_total += float(loss.item())
            train_acc_total += _policy_accuracy(logits.detach(), legal_mask, policy_target)
            train_batches += 1

        model.eval()
        val_loss_total = 0.0
        val_acc_total = 0.0
        val_batches = 0
        with torch.no_grad():
            for batch in val_loader:
                features = batch["features"].to(resolved_device)
                legal_mask = batch["legal_mask"].to(resolved_device)
                policy_target = batch["policy_target"].to(resolved_device)

                logits = model(features)
                loss = F.cross_entropy(_masked_logits(logits, legal_mask), policy_target)
                val_loss_total += float(loss.item())
                val_acc_total += _policy_accuracy(logits, legal_mask, policy_target)
                val_batches += 1

        train_loss = train_loss_total / max(1, train_batches)
        train_accuracy = train_acc_total / max(1, train_batches)
        val_loss = val_loss_total / max(1, val_batches)
        val_accuracy = val_acc_total / max(1, val_batches)
        print(
            f"epoch {epoch}/{epochs} "
            f"train_loss={train_loss:.4f} train_top1={train_accuracy:.3f} "
            f"val_loss={val_loss:.4f} val_top1={val_accuracy:.3f}"
        )

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_val_accuracy = val_accuracy
            torch.save(
                {
                    "model_kind": MODEL_KIND_ROOT_POLICY_V1,
                    "dataset_kind": DATASET_KIND_ROOT_POLICY_V1,
                    "model_state": model.state_dict(),
                    "model_config": config.to_dict(),
                    "best_val_loss": best_val_loss,
                    "best_val_top1": best_val_accuracy,
                    "split_group": resolved_split_group,
                },
                output,
            )

        scheduler.step()

    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the Ukumog root-policy evaluator.")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--val-fraction", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=20260421)
    parser.add_argument("--device", type=str, default="auto")
    parser.add_argument("--trunk-channels", type=int, default=56)
    parser.add_argument("--blocks", type=int, default=5)
    parser.add_argument("--policy-channels", type=int, default=24)
    parser.add_argument("--norm-groups", type=int, default=8)
    parser.add_argument("--trunk-dropout", type=float, default=0.03)
    parser.add_argument("--head-dropout", type=float, default=0.10)
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

    config = RootPolicyModelConfig(
        trunk_channels=args.trunk_channels,
        residual_blocks=args.blocks,
        policy_channels=args.policy_channels,
        norm_groups=args.norm_groups,
        trunk_dropout=args.trunk_dropout,
        head_dropout=args.head_dropout,
    )
    checkpoint = train_root_policy_model(
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
