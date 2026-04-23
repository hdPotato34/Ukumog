from .eval_lookup import DEFAULT_EVAL_LOOKUPS, EvalLookupTables
from .incremental import IncrementalState, IncrementalTacticalSummary, UndoToken
from .board import BOARD_CELLS, BOARD_SIZE, index_to_coord, coord_to_index
from .masks import DEFAULT_MASKS, MaskTables, PatternMask, generate_masks
from .position import Color, MoveResult, MoveType, Position, classify_move, play_move
from .search import SearchEngine, SearchResult, SearchStats, evaluate
from .solver import TacticalOutcome, TacticalSolveResult, TacticalSolveStats, TacticalSolver
from .tactics import TacticalSnapshot, analyze_tactics, immediate_winning_moves, relevant_empty_cells
from .validator import brute_force_move_result

__version__ = "0.1.0"

__all__ = [
    "BOARD_CELLS",
    "BOARD_SIZE",
    "Color",
    "DEFAULT_MASKS",
    "DEFAULT_EVAL_LOOKUPS",
    "EvalLookupTables",
    "IncrementalState",
    "IncrementalTacticalSummary",
    "MaskTables",
    "MoveResult",
    "MoveType",
    "PatternMask",
    "Position",
    "SearchEngine",
    "SearchResult",
    "SearchStats",
    "TacticalOutcome",
    "TacticalSolveResult",
    "TacticalSolveStats",
    "TacticalSolver",
    "UndoToken",
    "TacticalSnapshot",
    "analyze_tactics",
    "brute_force_move_result",
    "classify_move",
    "coord_to_index",
    "evaluate",
    "generate_masks",
    "immediate_winning_moves",
    "index_to_coord",
    "play_move",
    "relevant_empty_cells",
    "__version__",
]
