from __future__ import annotations

from enum import Enum, auto


class TacticalDetail(Enum):
    BASIC = auto()
    ORDERING = auto()


def resolve_tactical_detail(
    detail: TacticalDetail | None = None,
    *,
    include_move_maps: bool = True,
) -> TacticalDetail:
    if detail is not None:
        return detail
    if include_move_maps:
        return TacticalDetail.ORDERING
    return TacticalDetail.BASIC
