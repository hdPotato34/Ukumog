from __future__ import annotations

from dataclasses import asdict, dataclass

import torch
from torch import Tensor, nn

from ..board import BOARD_CELLS
from .features import FEATURE_CHANNELS
from .mask_features import (
    FIVE_MASK_COUNT,
    FIVE_STATE_COUNT,
    FOUR_MASK_COUNT,
    FOUR_STATE_COUNT,
    TOTAL_MASK_FEATURES,
)

MODEL_KIND_MASK_VALUE_V1 = "mask_value_v1"
MODEL_KIND_LEGACY_POLICY_VALUE = "legacy_policy_value_v0"
MODEL_KIND_ROOT_POLICY_V1 = "root_policy_v1"


@dataclass(frozen=True, slots=True)
class ModelConfig:
    total_features: int = TOTAL_MASK_FEATURES
    accumulator_width: int = 64
    hidden_width: int = 32

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


class UkumogMaskValueNet(nn.Module):
    def __init__(self, config: ModelConfig | None = None) -> None:
        super().__init__()
        self.config = config if config is not None else ModelConfig()
        self.embedding = nn.Embedding(self.config.total_features, self.config.accumulator_width)
        self.hidden = nn.Linear(self.config.accumulator_width, self.config.hidden_width)
        self.output = nn.Linear(self.config.hidden_width, 1)
        self.register_buffer(
            "four_offsets",
            torch.arange(FOUR_MASK_COUNT, dtype=torch.long) * FOUR_STATE_COUNT,
            persistent=False,
        )
        self.register_buffer(
            "five_offsets",
            (torch.arange(FIVE_MASK_COUNT, dtype=torch.long) * FIVE_STATE_COUNT)
            + (FOUR_MASK_COUNT * FOUR_STATE_COUNT),
            persistent=False,
        )

    def forward(self, four_states: Tensor, five_states: Tensor) -> Tensor:
        four_indices = four_states.long() + self.four_offsets
        five_indices = five_states.long() + self.five_offsets
        accumulator = self.embedding(four_indices).sum(dim=1) + self.embedding(five_indices).sum(dim=1)
        accumulator = torch.clamp(accumulator, 0.0, 1.0)
        hidden = torch.clamp(self.hidden(accumulator), 0.0, 1.0)
        return torch.tanh(self.output(hidden)).squeeze(-1)


def _group_count(max_groups: int, channels: int) -> int:
    for groups in range(min(max_groups, channels), 0, -1):
        if channels % groups == 0:
            return groups
    return 1


@dataclass(frozen=True, slots=True)
class RootPolicyModelConfig:
    input_channels: int = FEATURE_CHANNELS
    trunk_channels: int = 56
    residual_blocks: int = 5
    policy_channels: int = 24
    norm_groups: int = 8
    trunk_dropout: float = 0.03
    head_dropout: float = 0.10

    def to_dict(self) -> dict[str, int | float]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LegacyModelConfig:
    input_channels: int = FEATURE_CHANNELS
    trunk_channels: int = 56
    residual_blocks: int = 5
    policy_channels: int = 24
    value_channels: int = 24
    value_hidden: int = 128
    norm_groups: int = 8
    trunk_dropout: float = 0.03
    head_dropout: float = 0.10
    head_mode: str = "dense"

    def to_dict(self) -> dict[str, int | float | str]:
        return asdict(self)


class ResidualBlock(nn.Module):
    def __init__(self, channels: int, norm_groups: int, dropout: float) -> None:
        super().__init__()
        groups = _group_count(norm_groups, channels)
        self.block = nn.Sequential(
            nn.Conv2d(channels, channels, kernel_size=3, padding=1, bias=False),
            nn.GroupNorm(groups, channels),
            nn.SiLU(),
            nn.Dropout2d(dropout) if dropout > 0.0 else nn.Identity(),
            nn.Conv2d(channels, channels, kernel_size=3, padding=1, bias=False),
            nn.GroupNorm(groups, channels),
        )
        self.activation = nn.SiLU()

    def forward(self, x: Tensor) -> Tensor:
        return self.activation(x + self.block(x))


class UkumogRootPolicyNet(nn.Module):
    def __init__(self, config: RootPolicyModelConfig | None = None) -> None:
        super().__init__()
        self.config = config if config is not None else RootPolicyModelConfig()
        trunk_groups = _group_count(self.config.norm_groups, self.config.trunk_channels)
        policy_groups = _group_count(self.config.norm_groups, self.config.policy_channels)

        self.stem = nn.Sequential(
            nn.Conv2d(self.config.input_channels, self.config.trunk_channels, kernel_size=3, padding=1, bias=False),
            nn.GroupNorm(trunk_groups, self.config.trunk_channels),
            nn.SiLU(),
            nn.Dropout2d(self.config.trunk_dropout) if self.config.trunk_dropout > 0.0 else nn.Identity(),
        )
        self.trunk = nn.Sequential(
            *[
                ResidualBlock(
                    self.config.trunk_channels,
                    self.config.norm_groups,
                    self.config.trunk_dropout,
                )
                for _ in range(self.config.residual_blocks)
            ]
        )
        self.policy_head = nn.Sequential(
            nn.Conv2d(self.config.trunk_channels, self.config.policy_channels, kernel_size=1, bias=False),
            nn.GroupNorm(policy_groups, self.config.policy_channels),
            nn.SiLU(),
            nn.Dropout2d(self.config.head_dropout) if self.config.head_dropout > 0.0 else nn.Identity(),
            nn.Flatten(),
            nn.Linear(self.config.policy_channels * 11 * 11, BOARD_CELLS),
        )

    def forward(self, x: Tensor) -> Tensor:
        trunk = self.trunk(self.stem(x))
        return self.policy_head(trunk)


class UkumogPolicyValueNet(nn.Module):
    def __init__(self, config: LegacyModelConfig | None = None) -> None:
        super().__init__()
        self.config = config if config is not None else LegacyModelConfig()
        if self.config.head_mode not in {"dense", "pooled"}:
            raise ValueError(f"unsupported head_mode: {self.config.head_mode}")
        trunk_groups = _group_count(self.config.norm_groups, self.config.trunk_channels)
        policy_groups = _group_count(self.config.norm_groups, self.config.policy_channels)
        value_groups = _group_count(self.config.norm_groups, self.config.value_channels)

        self.stem = nn.Sequential(
            nn.Conv2d(self.config.input_channels, self.config.trunk_channels, kernel_size=3, padding=1, bias=False),
            nn.GroupNorm(trunk_groups, self.config.trunk_channels),
            nn.SiLU(),
            nn.Dropout2d(self.config.trunk_dropout) if self.config.trunk_dropout > 0.0 else nn.Identity(),
        )
        self.trunk = nn.Sequential(
            *[
                ResidualBlock(
                    self.config.trunk_channels,
                    self.config.norm_groups,
                    self.config.trunk_dropout,
                )
                for _ in range(self.config.residual_blocks)
            ]
        )
        self.policy_dropout = nn.Dropout2d(self.config.head_dropout) if self.config.head_dropout > 0.0 else nn.Identity()
        self.value_dropout_2d = nn.Dropout2d(self.config.head_dropout) if self.config.head_dropout > 0.0 else nn.Identity()
        self.value_dropout = nn.Dropout(self.config.head_dropout) if self.config.head_dropout > 0.0 else nn.Identity()

        if self.config.head_mode == "dense":
            self.policy_head = nn.Sequential(
                nn.Conv2d(self.config.trunk_channels, self.config.policy_channels, kernel_size=1, bias=False),
                nn.GroupNorm(policy_groups, self.config.policy_channels),
                nn.SiLU(),
                nn.Flatten(),
                nn.Linear(self.config.policy_channels * 11 * 11, BOARD_CELLS),
            )
            self.value_head = nn.Sequential(
                nn.Conv2d(self.config.trunk_channels, self.config.value_channels, kernel_size=1, bias=False),
                nn.GroupNorm(value_groups, self.config.value_channels),
                nn.SiLU(),
                nn.Flatten(),
                nn.Linear(self.config.value_channels * 11 * 11, self.config.value_hidden),
                nn.SiLU(),
                nn.Linear(self.config.value_hidden, 1),
                nn.Tanh(),
            )
        else:
            self.policy_head = nn.Sequential(
                nn.Conv2d(self.config.trunk_channels, self.config.policy_channels, kernel_size=1, bias=False),
                nn.GroupNorm(policy_groups, self.config.policy_channels),
                nn.SiLU(),
                nn.Dropout2d(self.config.head_dropout) if self.config.head_dropout > 0.0 else nn.Identity(),
                nn.Conv2d(self.config.policy_channels, 1, kernel_size=1, bias=True),
            )
            self.value_head = nn.Sequential(
                nn.Conv2d(self.config.trunk_channels, self.config.value_channels, kernel_size=1, bias=False),
                nn.GroupNorm(value_groups, self.config.value_channels),
                nn.SiLU(),
                nn.Dropout2d(self.config.head_dropout) if self.config.head_dropout > 0.0 else nn.Identity(),
                nn.AdaptiveAvgPool2d(1),
                nn.Flatten(),
                nn.Linear(self.config.value_channels, self.config.value_hidden),
                nn.SiLU(),
                nn.Dropout(self.config.head_dropout) if self.config.head_dropout > 0.0 else nn.Identity(),
                nn.Linear(self.config.value_hidden, 1),
                nn.Tanh(),
            )

    def forward(self, x: Tensor) -> tuple[Tensor, Tensor]:
        trunk = self.trunk(self.stem(x))
        if self.config.head_mode == "dense":
            policy_logits = self.policy_head(self.policy_dropout(trunk))
            value_hidden_input = self.value_dropout_2d(trunk)
            value = self.value_head[0:4](value_hidden_input)
            value = self.value_head[4](value)
            value = self.value_head[5](value)
            value = self.value_dropout(value)
            value = self.value_head[6](value)
            value = self.value_head[7](value).squeeze(-1)
            return policy_logits, value

        policy_logits = self.policy_head(trunk).flatten(start_dim=1)
        value = self.value_head(trunk).squeeze(-1)
        return policy_logits, value
