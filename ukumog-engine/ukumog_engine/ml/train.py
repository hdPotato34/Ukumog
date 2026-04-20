from __future__ import annotations

import argparse
from dataclasses import asdict
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch import Tensor, nn
from torch.utils.data import DataLoader, Subset

from .data import NPZPositionDataset
from .features import FEATURE_NAMES
from .model import ModelConfig, UkumogPolicyValueNet

POLICY_LABEL_SMOOTHING = 0.05


def _masked_policy_logits(policy_logits: Tensor, legal_mask: Tensor) -> Tensor:
    # Compute the policy loss in float32 so masking stays numerically safe
    # under autocast / float16 training on CUDA.
    logits = policy_logits.float()
    return logits.masked_fill(~legal_mask, torch.finfo(logits.dtype).min)


def _masked_policy_loss(policy_logits: Tensor, policy_target: Tensor, legal_mask: Tensor) -> Tensor:
    masked_logits = _masked_policy_logits(policy_logits, legal_mask)
    if POLICY_LABEL_SMOOTHING <= 0.0:
        return F.cross_entropy(masked_logits, policy_target)

    log_probs = F.log_softmax(masked_logits, dim=1)
    nll_loss = -log_probs.gather(1, policy_target.unsqueeze(1)).squeeze(1)
    legal_counts = legal_mask.sum(dim=1).clamp_min(1).to(log_probs.dtype)
    smooth_loss = -(log_probs.masked_fill(~legal_mask, 0.0).sum(dim=1) / legal_counts)
    return ((1.0 - POLICY_LABEL_SMOOTHING) * nll_loss + POLICY_LABEL_SMOOTHING * smooth_loss).mean()


def _policy_accuracy(policy_logits: Tensor, policy_target: Tensor, legal_mask: Tensor) -> float:
    masked_logits = _masked_policy_logits(policy_logits, legal_mask)
    predicted = masked_logits.argmax(dim=1)
    return float((predicted == policy_target).float().mean().item())


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
    policy_loss_weight: float = 1.0,
    value_loss_weight: float = 1.0,
    model_config: ModelConfig | None = None,
    symmetry_augment: bool = True,
    lr_decay: float = 0.97,
) -> Path:
    rng = np.random.default_rng(seed)
    dataset = NPZPositionDataset(data_path, symmetry_augment=symmetry_augment)

    indices = np.arange(len(dataset))
    rng.shuffle(indices)
    val_size = max(1, int(round(len(indices) * val_fraction)))
    train_indices = indices[val_size:]
    val_indices = indices[:val_size]
    if len(train_indices) == 0:
        raise ValueError("training split is empty; use a larger dataset or smaller val_fraction")

    train_dataset = Subset(dataset, train_indices.tolist())
    val_dataset = Subset(NPZPositionDataset(data_path, symmetry_augment=False), val_indices.tolist())

    resolved_device = torch.device(device if device is not None else ("cuda" if torch.cuda.is_available() else "cpu"))
    pin_memory = resolved_device.type == "cuda"
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, pin_memory=pin_memory)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False, pin_memory=pin_memory)

    config = model_config if model_config is not None else ModelConfig()
    model = UkumogPolicyValueNet(config).to(resolved_device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    scaler = torch.amp.GradScaler("cuda", enabled=resolved_device.type == "cuda")
    scheduler = torch.optim.lr_scheduler.ExponentialLR(optimizer, gamma=lr_decay)

    best_val_loss = float("inf")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    for epoch in range(1, epochs + 1):
        model.train()
        train_loss_total = 0.0
        train_policy_acc_total = 0.0
        train_batches = 0

        for batch in train_loader:
            features = batch["features"].to(resolved_device)
            legal_mask = batch["legal_mask"].to(resolved_device)
            policy_target = batch["policy_target"].to(resolved_device)
            value_target = batch["value_target"].to(resolved_device)

            optimizer.zero_grad(set_to_none=True)
            amp_context = (
                torch.autocast(device_type="cuda", enabled=True)
                if resolved_device.type == "cuda"
                else nullcontext()
            )
            with amp_context:
                policy_logits, value = model(features)
                policy_loss = _masked_policy_loss(policy_logits, policy_target, legal_mask)
                value_loss = F.smooth_l1_loss(value.float(), value_target.float(), beta=0.10)
                loss = policy_loss_weight * policy_loss + value_loss_weight * value_loss

            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()

            train_loss_total += float(loss.item())
            train_policy_acc_total += _policy_accuracy(policy_logits.detach(), policy_target, legal_mask)
            train_batches += 1

        model.eval()
        val_loss_total = 0.0
        val_policy_acc_total = 0.0
        val_batches = 0
        with torch.no_grad():
            for batch in val_loader:
                features = batch["features"].to(resolved_device)
                legal_mask = batch["legal_mask"].to(resolved_device)
                policy_target = batch["policy_target"].to(resolved_device)
                value_target = batch["value_target"].to(resolved_device)

                policy_logits, value = model(features)
                policy_loss = _masked_policy_loss(policy_logits, policy_target, legal_mask)
                value_loss = F.smooth_l1_loss(value.float(), value_target.float(), beta=0.10)
                loss = policy_loss_weight * policy_loss + value_loss_weight * value_loss

                val_loss_total += float(loss.item())
                val_policy_acc_total += _policy_accuracy(policy_logits, policy_target, legal_mask)
                val_batches += 1

        train_loss = train_loss_total / max(1, train_batches)
        train_policy_acc = train_policy_acc_total / max(1, train_batches)
        val_loss = val_loss_total / max(1, val_batches)
        val_policy_acc = val_policy_acc_total / max(1, val_batches)
        print(
            f"epoch {epoch}/{epochs} "
            f"train_loss={train_loss:.4f} train_policy_acc={train_policy_acc:.3f} "
            f"val_loss={val_loss:.4f} val_policy_acc={val_policy_acc:.3f}"
        )

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            torch.save(
                {
                    "model_state": model.state_dict(),
                    "model_config": asdict(config),
                    "feature_names": FEATURE_NAMES,
                    "best_val_loss": best_val_loss,
                },
                output,
            )

        scheduler.step()

    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the Ukumog learned evaluator.")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--val-fraction", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=20260419)
    parser.add_argument("--device", type=str, default=None)
    parser.add_argument("--channels", type=int, default=64)
    parser.add_argument("--blocks", type=int, default=6)
    parser.add_argument(
        "--no-symmetry-augment",
        action="store_true",
        help="Disable random board-symmetry augmentation during training.",
    )
    parser.add_argument(
        "--lr-decay",
        type=float,
        default=0.97,
        help="Exponential per-epoch learning-rate decay. Default: 0.97.",
    )
    args = parser.parse_args()

    config = ModelConfig(trunk_channels=args.channels, residual_blocks=args.blocks)
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
        symmetry_augment=not args.no_symmetry_augment,
        lr_decay=args.lr_decay,
    )
    print(f"saved checkpoint to {checkpoint}")


if __name__ == "__main__":
    main()
