from __future__ import annotations

from dataclasses import asdict, dataclass

import torch
from torch import Tensor, nn

from ..board import BOARD_CELLS
from .features import FEATURE_CHANNELS


@dataclass(frozen=True, slots=True)
class ModelConfig:
    input_channels: int = FEATURE_CHANNELS
    trunk_channels: int = 64
    residual_blocks: int = 6
    value_hidden: int = 128
    norm_groups: int = 8

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


class ResidualBlock(nn.Module):
    def __init__(self, channels: int, norm_groups: int) -> None:
        super().__init__()
        groups = min(norm_groups, channels)
        self.block = nn.Sequential(
            nn.Conv2d(channels, channels, kernel_size=3, padding=1, bias=False),
            nn.GroupNorm(groups, channels),
            nn.SiLU(),
            nn.Conv2d(channels, channels, kernel_size=3, padding=1, bias=False),
            nn.GroupNorm(groups, channels),
        )
        self.activation = nn.SiLU()

    def forward(self, x: Tensor) -> Tensor:
        return self.activation(x + self.block(x))


class UkumogPolicyValueNet(nn.Module):
    def __init__(self, config: ModelConfig | None = None) -> None:
        super().__init__()
        self.config = config if config is not None else ModelConfig()
        groups = min(self.config.norm_groups, self.config.trunk_channels)

        self.stem = nn.Sequential(
            nn.Conv2d(self.config.input_channels, self.config.trunk_channels, kernel_size=3, padding=1, bias=False),
            nn.GroupNorm(groups, self.config.trunk_channels),
            nn.SiLU(),
        )
        self.trunk = nn.Sequential(
            *[
                ResidualBlock(self.config.trunk_channels, self.config.norm_groups)
                for _ in range(self.config.residual_blocks)
            ]
        )
        self.policy_head = nn.Sequential(
            nn.Conv2d(self.config.trunk_channels, 32, kernel_size=1, bias=False),
            nn.GroupNorm(8, 32),
            nn.SiLU(),
            nn.Flatten(),
            nn.Linear(32 * 11 * 11, BOARD_CELLS),
        )
        self.value_head = nn.Sequential(
            nn.Conv2d(self.config.trunk_channels, 32, kernel_size=1, bias=False),
            nn.GroupNorm(8, 32),
            nn.SiLU(),
            nn.Flatten(),
            nn.Linear(32 * 11 * 11, self.config.value_hidden),
            nn.SiLU(),
            nn.Linear(self.config.value_hidden, 1),
            nn.Tanh(),
        )

    def forward(self, x: Tensor) -> tuple[Tensor, Tensor]:
        trunk = self.trunk(self.stem(x))
        policy_logits = self.policy_head(trunk)
        value = self.value_head(trunk).squeeze(-1)
        return policy_logits, value
