from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import queue
import random
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from ukumog_engine import (
    BOARD_SIZE,
    Color,
    MoveResult,
    Position,
    SearchResult,
    analyze_tactics,
    coord_to_index,
    index_to_coord,
    play_move,
)
from ukumog_engine.app_runtime import (
    EngineController,
    EngineSpec,
    announce_result,
    build_engine_controller,
    choose_engine_move,
    record_search_totals,
)


ML_MODE_CHOICES = ("auto", "quiet-value", "full", "policy-only", "root-policy", "root-hybrid")
DEVICE_CHOICES = ("cpu", "cuda", "auto")
MODE_CHOICES = ("human-vs-human", "human-vs-engine", "engine-vs-engine")
HUMAN_CHOICES = ("black", "white")
WORKER_POLL_MS = 80
BOARD_PADDING = 32


@dataclass(frozen=True, slots=True)
class BoardMetrics:
    origin_x: float
    origin_y: float
    board_span: float
    cell_size: float
    stone_radius: float


@dataclass(slots=True)
class PlayedMove:
    previous_position: Position
    next_position: Position
    move: int
    result: MoveResult
    actor: str
    color: Color


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the Ukumog desktop GUI.")
    parser.add_argument("--mode", choices=MODE_CHOICES, default="human-vs-human")
    parser.add_argument("--human", choices=HUMAN_CHOICES, default="black")
    parser.add_argument("--depth", type=int, default=4)
    parser.add_argument("--time", type=float, default=10.0)
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument("--ml-mode", choices=ML_MODE_CHOICES, default="auto")
    parser.add_argument("--learned-weight", type=float, default=0.10)
    parser.add_argument("--device", choices=DEVICE_CHOICES, default="cpu")
    parser.add_argument("--symmetry-ensemble", action="store_true")
    parser.add_argument("--black-model", type=Path, default=None)
    parser.add_argument("--white-model", type=Path, default=None)
    parser.add_argument("--black-depth", type=int, default=None)
    parser.add_argument("--white-depth", type=int, default=None)
    parser.add_argument("--black-time", type=float, default=None)
    parser.add_argument("--white-time", type=float, default=None)
    parser.add_argument("--black-learned-weight", type=float, default=None)
    parser.add_argument("--white-learned-weight", type=float, default=None)
    parser.add_argument("--black-ml-mode", choices=ML_MODE_CHOICES, default=None)
    parser.add_argument("--white-ml-mode", choices=ML_MODE_CHOICES, default=None)
    parser.add_argument("--black-symmetry-ensemble", action="store_true")
    parser.add_argument("--white-symmetry-ensemble", action="store_true")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--black-temperature", type=float, default=None)
    parser.add_argument("--white-temperature", type=float, default=None)
    parser.add_argument("--temperature-plies", type=int, default=10)
    parser.add_argument("--sample-top-k", type=int, default=4)
    parser.add_argument("--max-moves", type=int, default=121)
    parser.add_argument("--seed", type=int, default=20260419)
    return parser.parse_args(argv)


def format_score_text(score: int) -> str:
    return f"{score:+d}"


def format_move_text(move: int | None) -> str:
    if move is None:
        return "--"
    row, col = index_to_coord(move)
    return f"{row}, {col}"


def format_pv_text(principal_variation: tuple[int, ...], *, limit: int = 8) -> str:
    if not principal_variation:
        return "--"
    shown = [format_move_text(move) for move in principal_variation[:limit]]
    suffix = " ..." if len(principal_variation) > limit else ""
    return " -> ".join(shown) + suffix


def top_root_rows(result: SearchResult, *, limit: int = 5) -> list[tuple[int, str, str]]:
    rows: list[tuple[int, str, str]] = []
    for index, root_score in enumerate(result.root_move_scores[:limit], start=1):
        rows.append((index, format_move_text(root_score.move), format_score_text(root_score.score)))
    if not rows and result.best_move is not None:
        rows.append((1, format_move_text(result.best_move), format_score_text(result.score)))
    return rows


def compute_board_metrics(
    width: int,
    height: int,
    *,
    board_size: int = BOARD_SIZE,
    padding: int = BOARD_PADDING,
) -> BoardMetrics:
    usable = max(180.0, float(min(width, height) - (padding * 2)))
    cell_size = usable / board_size
    board_span = cell_size * board_size
    origin_x = (width - board_span) / 2.0
    origin_y = (height - board_span) / 2.0
    return BoardMetrics(
        origin_x=origin_x,
        origin_y=origin_y,
        board_span=board_span,
        cell_size=cell_size,
        stone_radius=max(8.0, cell_size * 0.32),
    )


def board_cell_from_point(x: float, y: float, metrics: BoardMetrics, *, board_size: int = BOARD_SIZE) -> tuple[int, int] | None:
    local_x = x - metrics.origin_x
    local_y = y - metrics.origin_y
    if local_x < 0 or local_y < 0 or local_x >= metrics.board_span or local_y >= metrics.board_span:
        return None
    col = int(local_x // metrics.cell_size)
    row = int(local_y // metrics.cell_size)
    if not (0 <= row < board_size and 0 <= col < board_size):
        return None
    return row, col


def position_from_history(history: list[PlayedMove], current_ply: int) -> Position:
    if current_ply <= 0 or not history:
        return Position.initial()
    return history[current_ply - 1].next_position


def last_move_from_history(history: list[PlayedMove], current_ply: int) -> int | None:
    if current_ply <= 0 or not history:
        return None
    return history[current_ply - 1].move


class EngineSettingsPanel(ttk.LabelFrame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        title: str,
        depth: int,
        time_seconds: float,
        temperature: float,
        learned_weight: float,
        model_path: Path | None,
        ml_mode: str,
        device: str,
        symmetry_ensemble: bool,
    ) -> None:
        super().__init__(master, text=title, padding=12)
        self.columnconfigure(1, weight=1)

        self.depth_var = tk.StringVar(value=str(depth))
        self.time_var = tk.StringVar(value=f"{time_seconds:g}")
        self.temperature_var = tk.StringVar(value=f"{temperature:g}")
        self.learned_weight_var = tk.StringVar(value=f"{learned_weight:g}")
        self.model_var = tk.StringVar(value="" if model_path is None else str(model_path))
        self.ml_mode_var = tk.StringVar(value=ml_mode)
        self.device_var = tk.StringVar(value=device)
        self.symmetry_var = tk.BooleanVar(value=symmetry_ensemble)

        self._add_row("Depth", ttk.Entry(self, textvariable=self.depth_var, width=10), 0)
        self._add_row("Time (s)", ttk.Entry(self, textvariable=self.time_var, width=10), 1)
        self._add_row("Temperature", ttk.Entry(self, textvariable=self.temperature_var, width=10), 2)
        self._add_row("Learned weight", ttk.Entry(self, textvariable=self.learned_weight_var, width=10), 3)

        ml_box = ttk.Combobox(self, textvariable=self.ml_mode_var, values=ML_MODE_CHOICES, state="readonly", width=14)
        self._add_row("ML mode", ml_box, 4)

        device_box = ttk.Combobox(self, textvariable=self.device_var, values=DEVICE_CHOICES, state="readonly", width=10)
        self._add_row("Device", device_box, 5)

        model_frame = ttk.Frame(self)
        model_frame.columnconfigure(0, weight=1)
        model_entry = ttk.Entry(model_frame, textvariable=self.model_var)
        model_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(model_frame, text="Browse", command=self._choose_model).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(model_frame, text="Clear", command=lambda: self.model_var.set("")).grid(row=0, column=2, padx=(8, 0))
        self._add_row("Model", model_frame, 6)

        symmetry = ttk.Checkbutton(self, text="Symmetry ensemble", variable=self.symmetry_var)
        symmetry.grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def _add_row(self, label: str, widget: tk.Widget, row: int) -> None:
        ttk.Label(self, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 12))
        widget.grid(row=row, column=1, sticky="ew", pady=4)

    def _choose_model(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Choose a model checkpoint",
            filetypes=[("PyTorch checkpoints", "*.pt"), ("NumPy archives", "*.npz"), ("All files", "*.*")],
        )
        if chosen:
            self.model_var.set(chosen)

    def to_spec(self, name: str) -> EngineSpec:
        model_text = self.model_var.get().strip()
        model_path = Path(model_text) if model_text else None
        return EngineSpec(
            name=name,
            model_path=model_path,
            ml_mode=self.ml_mode_var.get(),
            device=self.device_var.get(),
            depth=int(self.depth_var.get().strip()),
            time_seconds=float(self.time_var.get().strip()),
            learned_weight=float(self.learned_weight_var.get().strip()),
            temperature=float(self.temperature_var.get().strip()),
            symmetry_ensemble=bool(self.symmetry_var.get()),
        )


class CollapsibleSection(ttk.Frame):
    def __init__(self, master: tk.Misc, *, title: str, collapsed: bool = False) -> None:
        super().__init__(master)
        self.columnconfigure(0, weight=1)
        self._title = title
        self._collapsed = collapsed
        self.toggle_button = ttk.Button(self, command=self.toggle)
        self.toggle_button.grid(row=0, column=0, sticky="ew")
        self.content = ttk.Frame(self)
        self.content.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.content.columnconfigure(0, weight=1)
        self._refresh()

    def attach(self, widget: tk.Widget) -> None:
        widget.grid(row=0, column=0, sticky="ew")

    def toggle(self) -> None:
        self._collapsed = not self._collapsed
        self._refresh()

    def _refresh(self) -> None:
        glyph = "+" if self._collapsed else "-"
        self.toggle_button.configure(text=f"{glyph} {self._title}")
        if self._collapsed:
            self.content.grid_remove()
        else:
            self.content.grid()


class UkumogGUI(tk.Tk):
    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__()
        self.title("Ukumog Studio")
        self.geometry("1480x920")
        self.minsize(1220, 760)
        self.configure(bg="#091723")

        self.position = Position.initial()
        self.history: list[PlayedMove] = []
        self.current_ply = 0
        self.last_move: int | None = None
        self.analysis_best_move: int | None = None
        self.hovered_cell: tuple[int, int] | None = None
        self.autoplay_enabled = False
        self.search_busy = False
        self.active_task_id = 0
        self.worker_queue: queue.Queue[dict[str, object]] = queue.Queue()
        self.controller_cache: dict[tuple[object, ...], EngineController] = {}
        self.mode_var = tk.StringVar(value=args.mode)
        self.human_var = tk.StringVar(value=args.human)
        self.temperature_plies_var = tk.StringVar(value=str(args.temperature_plies))
        self.sample_top_k_var = tk.StringVar(value=str(args.sample_top_k))
        self.max_moves_var = tk.StringVar(value=str(args.max_moves))
        self.seed_var = tk.StringVar(value=str(args.seed))
        self.board_size_note_var = tk.StringVar(value="11x11 fixed for now; the engine is still board-size specific.")
        self.status_var = tk.StringVar(value="Ready. Plain board mode is active; build a position or click Analyze.")
        self.analysis_title_var = tk.StringVar(value="Current position analysis")
        self.analysis_engine_var = tk.StringVar(value="--")
        self.analysis_recommendation_var = tk.StringVar(value="--")
        self.analysis_score_var = tk.StringVar(value="--")
        self.analysis_best_var = tk.StringVar(value="--")
        self.analysis_depth_var = tk.StringVar(value="--")
        self.analysis_nodes_var = tk.StringVar(value="--")
        self.analysis_time_var = tk.StringVar(value="--")
        self.analysis_pv_var = tk.StringVar(value="--")
        self.analysis_tactics_var = tk.StringVar(value="--")
        self.turn_var = tk.StringVar()
        self.mode_hint_var = tk.StringVar()

        self._configure_style()
        self._build_layout(args)
        self._set_log_writable(False)
        self._update_turn_label()
        self._update_mode_hints()
        self.after(WORKER_POLL_MS, self._poll_worker_queue)
        self.after(120, self._advance_autoplay_if_needed)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background="#091723", foreground="#e9f2f8", fieldbackground="#102536")
        style.configure("TFrame", background="#091723")
        style.configure("Panel.TFrame", background="#102536")
        style.configure("TLabel", background="#091723", foreground="#e9f2f8")
        style.configure("Panel.TLabel", background="#102536", foreground="#d8e6ef")
        style.configure("Title.TLabel", background="#091723", foreground="#f6f3d3", font=("Segoe UI Semibold", 22))
        style.configure("Subtle.TLabel", background="#091723", foreground="#9fb6c9")
        style.configure("Card.TLabel", background="#102536", foreground="#f3f5f8")
        style.configure("TLabelframe", background="#102536", foreground="#f6f3d3", bordercolor="#24485f")
        style.configure("TLabelframe.Label", background="#102536", foreground="#f6f3d3", font=("Segoe UI Semibold", 11))
        style.configure("TButton", background="#c98d3d", foreground="#091723", borderwidth=0, focusthickness=0, padding=(12, 8))
        style.map("TButton", background=[("active", "#e0a95c"), ("disabled", "#435c6f")], foreground=[("disabled", "#c7d2db")])
        style.configure("Accent.TButton", background="#5eb0ef", foreground="#08131d")
        style.map("Accent.TButton", background=[("active", "#84c5f5"), ("disabled", "#435c6f")])
        style.configure("Treeview", background="#0f2231", fieldbackground="#0f2231", foreground="#e9f2f8", bordercolor="#24485f")
        style.configure("Treeview.Heading", background="#17384e", foreground="#f6f3d3")
        style.configure("TEntry", fieldbackground="#0f2231", foreground="#e9f2f8")
        style.configure("TCombobox", fieldbackground="#0f2231", foreground="#e9f2f8")

    def _build_layout(self, args: argparse.Namespace) -> None:
        shell = ttk.Frame(self, padding=18)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=7)
        shell.columnconfigure(1, weight=4)
        shell.rowconfigure(1, weight=1)

        header = ttk.Frame(shell)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Ukumog Studio", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Mouse-first play, engine analysis, and side-by-side search tuning without losing the CLI.",
            style="Subtle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        board_panel = ttk.Frame(shell, style="Panel.TFrame", padding=16)
        board_panel.grid(row=1, column=0, sticky="nsew", padx=(0, 16))
        board_panel.columnconfigure(0, weight=1)
        board_panel.rowconfigure(1, weight=1)

        top_bar = ttk.Frame(board_panel, style="Panel.TFrame")
        top_bar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        top_bar.columnconfigure(0, weight=1)
        ttk.Label(top_bar, textvariable=self.turn_var, style="Card.TLabel", font=("Segoe UI Semibold", 12)).grid(row=0, column=0, sticky="w")
        ttk.Label(top_bar, textvariable=self.mode_hint_var, style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.board_canvas = tk.Canvas(
            board_panel,
            bg="#132b1f",
            highlightthickness=0,
            relief="flat",
        )
        self.board_canvas.grid(row=1, column=0, sticky="nsew")
        self.board_canvas.bind("<Configure>", lambda _event: self._redraw_board())
        self.board_canvas.bind("<Motion>", self._handle_board_motion)
        self.board_canvas.bind("<Leave>", self._handle_board_leave)
        self.board_canvas.bind("<Button-1>", self._handle_board_click)

        board_note = ttk.Label(
            board_panel,
            textvariable=self.board_size_note_var,
            style="Panel.TLabel",
            wraplength=680,
        )
        board_note.grid(row=2, column=0, sticky="ew", pady=(12, 0))

        side_shell = ttk.Frame(shell)
        side_shell.grid(row=1, column=1, sticky="nsew")
        side_shell.columnconfigure(0, weight=1)
        side_shell.rowconfigure(0, weight=1)

        side_canvas = tk.Canvas(side_shell, bg="#091723", highlightthickness=0, relief="flat")
        side_canvas.grid(row=0, column=0, sticky="nsew")
        side_scrollbar = ttk.Scrollbar(side_shell, orient="vertical", command=side_canvas.yview)
        side_scrollbar.grid(row=0, column=1, sticky="ns")
        side_canvas.configure(yscrollcommand=side_scrollbar.set)
        side_panel = ttk.Frame(side_canvas)
        side_panel.columnconfigure(0, weight=1)
        side_window = side_canvas.create_window((0, 0), window=side_panel, anchor="nw")

        def _sync_side_panel(_event: tk.Event[tk.Widget]) -> None:
            side_canvas.configure(scrollregion=side_canvas.bbox("all"))

        def _sync_side_width(event: tk.Event[tk.Canvas]) -> None:
            side_canvas.itemconfigure(side_window, width=event.width)

        side_panel.bind("<Configure>", _sync_side_panel)
        side_canvas.bind("<Configure>", _sync_side_width)

        def _on_side_mousewheel(event: tk.Event[tk.Widget]) -> None:
            if side_canvas.winfo_height() < side_panel.winfo_height():
                side_canvas.yview_scroll(int(-event.delta / 120), "units")

        side_canvas.bind_all("<MouseWheel>", _on_side_mousewheel)

        controls = ttk.LabelFrame(side_panel, text="Game Controls", padding=12)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(3, weight=1)

        ttk.Label(controls, text="Mode").grid(row=0, column=0, sticky="w")
        mode_box = ttk.Combobox(controls, textvariable=self.mode_var, values=MODE_CHOICES, state="readonly")
        mode_box.grid(row=0, column=1, sticky="ew", padx=(8, 14), pady=4)
        mode_box.bind("<<ComboboxSelected>>", lambda _event: self._on_mode_changed())

        ttk.Label(controls, text="Human side").grid(row=0, column=2, sticky="w")
        self.human_box = ttk.Combobox(controls, textvariable=self.human_var, values=HUMAN_CHOICES, state="readonly")
        self.human_box.grid(row=0, column=3, sticky="ew", padx=(8, 0), pady=4)
        self.human_box.bind("<<ComboboxSelected>>", lambda _event: self._on_mode_changed())

        ttk.Label(controls, text="Opening sample plies").grid(row=1, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.temperature_plies_var, width=10).grid(row=1, column=1, sticky="ew", padx=(8, 14), pady=4)
        ttk.Label(controls, text="Top-K").grid(row=1, column=2, sticky="w")
        ttk.Entry(controls, textvariable=self.sample_top_k_var, width=10).grid(row=1, column=3, sticky="ew", padx=(8, 0), pady=4)

        ttk.Label(controls, text="Move cap").grid(row=2, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.max_moves_var, width=10).grid(row=2, column=1, sticky="ew", padx=(8, 14), pady=4)
        ttk.Label(controls, text="Seed").grid(row=2, column=2, sticky="w")
        ttk.Entry(controls, textvariable=self.seed_var, width=10).grid(row=2, column=3, sticky="ew", padx=(8, 0), pady=4)

        actions = ttk.Frame(controls)
        actions.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        for column in range(4):
            actions.columnconfigure(column, weight=1)
        ttk.Button(actions, text="New Game", command=self._new_game).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(actions, text="Analyze", style="Accent.TButton", command=self._analyze_current_position).grid(row=0, column=1, sticky="ew", padx=8)
        self.autoplay_button = ttk.Button(actions, text="Start Autoplay", command=self._toggle_autoplay)
        self.autoplay_button.grid(row=0, column=2, sticky="ew", padx=8)
        ttk.Button(actions, text="Branch Here", command=self._branch_here).grid(row=0, column=3, sticky="ew", padx=(8, 0))

        timeline = ttk.Frame(controls)
        timeline.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        for column in range(4):
            timeline.columnconfigure(column, weight=1)
        ttk.Button(timeline, text="Start", command=self._go_start).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(timeline, text="Prev", command=self._go_prev).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(timeline, text="Next", command=self._go_next).grid(row=0, column=2, sticky="ew", padx=8)
        ttk.Button(timeline, text="End", command=self._go_end).grid(row=0, column=3, sticky="ew", padx=(8, 0))

        black_section = CollapsibleSection(side_panel, title="Black Engine", collapsed=True)
        black_section.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        self.black_panel = EngineSettingsPanel(
            black_section.content,
            title="Black Engine Settings",
            depth=args.black_depth or args.depth,
            time_seconds=args.black_time if args.black_time is not None else args.time,
            temperature=args.black_temperature if args.black_temperature is not None else args.temperature,
            learned_weight=args.black_learned_weight if args.black_learned_weight is not None else args.learned_weight,
            model_path=args.black_model or args.model,
            ml_mode=args.black_ml_mode or args.ml_mode,
            device=args.device,
            symmetry_ensemble=args.black_symmetry_ensemble or args.symmetry_ensemble,
        )
        black_section.attach(self.black_panel)

        white_section = CollapsibleSection(side_panel, title="White Engine", collapsed=True)
        white_section.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        self.white_panel = EngineSettingsPanel(
            white_section.content,
            title="White Engine Settings",
            depth=args.white_depth or args.depth,
            time_seconds=args.white_time if args.white_time is not None else args.time,
            temperature=args.white_temperature if args.white_temperature is not None else args.temperature,
            learned_weight=args.white_learned_weight if args.white_learned_weight is not None else args.learned_weight,
            model_path=args.white_model or args.model,
            ml_mode=args.white_ml_mode or args.ml_mode,
            device=args.device,
            symmetry_ensemble=args.white_symmetry_ensemble or args.symmetry_ensemble,
        )
        white_section.attach(self.white_panel)

        analysis = ttk.LabelFrame(side_panel, text="Analysis", padding=12)
        analysis.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        analysis.columnconfigure(1, weight=1)
        ttk.Label(analysis, textvariable=self.analysis_title_var).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Label(
            analysis,
            textvariable=self.analysis_recommendation_var,
            style="Card.TLabel",
            font=("Segoe UI Semibold", 11),
            wraplength=430,
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        self._analysis_row(analysis, "Engine", self.analysis_engine_var, 2)
        self._analysis_row(analysis, "Score", self.analysis_score_var, 3)
        self._analysis_row(analysis, "Best move", self.analysis_best_var, 4)
        self._analysis_row(analysis, "Depth", self.analysis_depth_var, 5)
        self._analysis_row(analysis, "Nodes", self.analysis_nodes_var, 6)
        self._analysis_row(analysis, "Elapsed", self.analysis_time_var, 7)
        self._analysis_row(analysis, "PV", self.analysis_pv_var, 8, wraplength=430)
        self._analysis_row(analysis, "Tactics", self.analysis_tactics_var, 9, wraplength=430)

        self.top_moves = ttk.Treeview(analysis, columns=("rank", "move", "score"), show="headings", height=5)
        self.top_moves.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.top_moves.heading("rank", text="#")
        self.top_moves.heading("move", text="Move")
        self.top_moves.heading("score", text="Score")
        self.top_moves.column("rank", width=48, anchor="center")
        self.top_moves.column("move", width=110, anchor="center")
        self.top_moves.column("score", width=110, anchor="center")

        activity = ttk.LabelFrame(side_panel, text="Activity", padding=12)
        activity.grid(row=4, column=0, sticky="nsew", pady=(14, 0))
        activity.columnconfigure(0, weight=1)
        activity.rowconfigure(0, weight=1)
        self.log = tk.Text(
            activity,
            height=10,
            wrap="word",
            bg="#0f2231",
            fg="#e9f2f8",
            insertbackground="#e9f2f8",
            relief="flat",
            padx=10,
            pady=10,
        )
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(activity, orient="vertical", command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

        status = ttk.Label(shell, textvariable=self.status_var, style="Subtle.TLabel")
        status.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(14, 0))

        self._append_log("GUI ready. Plain board mode is the default; place stones, navigate the timeline, and analyze any current position.")
        self._redraw_board()

    def _analysis_row(
        self,
        parent: ttk.LabelFrame,
        label: str,
        variable: tk.StringVar,
        row: int,
        *,
        wraplength: int | None = None,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=2)
        ttk.Label(parent, textvariable=variable, wraplength=wraplength).grid(row=row, column=1, sticky="w", pady=2)

    def _set_log_writable(self, writable: bool) -> None:
        self.log.configure(state="normal" if writable else "disabled")

    def _append_log(self, message: str) -> None:
        self._set_log_writable(True)
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self._set_log_writable(False)

    def _metrics(self) -> BoardMetrics:
        width = max(1, self.board_canvas.winfo_width())
        height = max(1, self.board_canvas.winfo_height())
        return compute_board_metrics(width, height)

    def _redraw_board(self) -> None:
        metrics = self._metrics()
        canvas = self.board_canvas
        canvas.delete("all")

        canvas.create_rectangle(0, 0, canvas.winfo_width(), canvas.winfo_height(), fill="#132b1f", outline="")
        canvas.create_rectangle(
            metrics.origin_x - 10,
            metrics.origin_y - 10,
            metrics.origin_x + metrics.board_span + 10,
            metrics.origin_y + metrics.board_span + 10,
            fill="#d3b173",
            outline="#f0d7a1",
            width=3,
        )

        for offset in range(BOARD_SIZE + 1):
            x = metrics.origin_x + (offset * metrics.cell_size)
            y = metrics.origin_y + (offset * metrics.cell_size)
            canvas.create_line(x, metrics.origin_y, x, metrics.origin_y + metrics.board_span, fill="#805b2f", width=2)
            canvas.create_line(metrics.origin_x, y, metrics.origin_x + metrics.board_span, y, fill="#805b2f", width=2)

        for index in range(BOARD_SIZE):
            cell_center = metrics.origin_x + (index + 0.5) * metrics.cell_size
            canvas.create_text(cell_center, metrics.origin_y - 16, text=str(index), fill="#f6f3d3", font=("Segoe UI", 10))
            canvas.create_text(metrics.origin_x - 16, cell_center, text=str(index), fill="#f6f3d3", font=("Segoe UI", 10))

        if self.hovered_cell is not None:
            row, col = self.hovered_cell
            if self._can_play_human_move() and self.position.is_empty(coord_to_index(row, col)):
                self._draw_cell_highlight(row, col, metrics, fill="#6bcf9f", stipple="gray25")

        if self.last_move is not None:
            row, col = index_to_coord(self.last_move)
            self._draw_cell_highlight(row, col, metrics, fill="#5eb0ef", stipple="gray50")

        if self.analysis_best_move is not None and self.position.is_empty(self.analysis_best_move):
            row, col = index_to_coord(self.analysis_best_move)
            self._draw_cell_highlight(row, col, metrics, fill="#f3a53d", stipple="gray25")

        for move in range(BOARD_SIZE * BOARD_SIZE):
            row, col = index_to_coord(move)
            left = metrics.origin_x + col * metrics.cell_size + 6
            top = metrics.origin_y + row * metrics.cell_size + 6
            right = left + metrics.cell_size - 12
            bottom = top + metrics.cell_size - 12
            move_bit = 1 << move
            if self.position.black_bits & move_bit:
                canvas.create_oval(left, top, right, bottom, fill="#101820", outline="#f6f3d3", width=2)
            elif self.position.white_bits & move_bit:
                canvas.create_oval(left, top, right, bottom, fill="#f7f1df", outline="#41586a", width=2)

    def _draw_cell_highlight(self, row: int, col: int, metrics: BoardMetrics, *, fill: str, stipple: str) -> None:
        left = metrics.origin_x + col * metrics.cell_size + 4
        top = metrics.origin_y + row * metrics.cell_size + 4
        right = left + metrics.cell_size - 8
        bottom = top + metrics.cell_size - 8
        self.board_canvas.create_rectangle(left, top, right, bottom, fill=fill, outline="", stipple=stipple)

    def _on_mode_changed(self) -> None:
        self.autoplay_enabled = False
        self._update_mode_hints()
        self._update_turn_label()
        self._advance_autoplay_if_needed()

    def _update_mode_hints(self) -> None:
        if self.mode_var.get() == "engine-vs-engine":
            self.mode_hint_var.set("Both sides use the configured engines. Use Start Autoplay to let the match run.")
            self.autoplay_button.configure(state="normal", text="Start Autoplay")
            self.human_box.configure(state="disabled")
        elif self.mode_var.get() == "human-vs-engine":
            human_side = self.human_var.get().title()
            self.mode_hint_var.set(f"You control {human_side}. The other side will answer automatically after each click.")
            self.autoplay_button.configure(state="disabled", text="Autoplay N/A")
            self.human_box.configure(state="readonly")
        else:
            self.mode_hint_var.set("Plain board mode. Click to place both sides, build a position, and run Analyze.")
            self.autoplay_button.configure(state="disabled", text="Autoplay N/A")
            self.human_box.configure(state="disabled")

    def _update_turn_label(self) -> None:
        side = "Black" if self.position.side_to_move is Color.BLACK else "White"
        self.turn_var.set(f"Turn: {side} to move   |   Ply: {self.current_ply} / {len(self.history)}")

    def _current_human_color(self) -> Color:
        return Color.BLACK if self.human_var.get() == "black" else Color.WHITE

    def _is_at_history_head(self) -> bool:
        return self.current_ply == len(self.history)

    def _is_terminal(self) -> bool:
        if self.current_ply <= 0 or not self.history:
            return False
        return self.history[self.current_ply - 1].result is not MoveResult.NONTERMINAL

    def _sync_position_from_history(self) -> None:
        self.position = position_from_history(self.history, self.current_ply)
        self.last_move = last_move_from_history(self.history, self.current_ply)
        self.hovered_cell = None
        self._update_turn_label()
        self._redraw_board()

    def _cancel_inflight_work(self, message: str | None = None) -> None:
        if self.search_busy:
            self.active_task_id += 1
            self.search_busy = False
            self.autoplay_enabled = False
            if self.mode_var.get() == "engine-vs-engine":
                self.autoplay_button.configure(text="Start Autoplay")
            if message is not None:
                self.status_var.set(message)

    def _truncate_future_if_needed(self) -> None:
        if self._is_at_history_head():
            return
        removed = len(self.history) - self.current_ply
        del self.history[self.current_ply :]
        if removed > 0:
            self._append_log(f"Discarded {removed} future move(s) and started a new branch from ply {self.current_ply}.")

    def _max_moves(self) -> int:
        try:
            return max(1, int(self.max_moves_var.get().strip()))
        except ValueError:
            return 121

    def _temperature_plies(self) -> int:
        try:
            return max(0, int(self.temperature_plies_var.get().strip()))
        except ValueError:
            return 10

    def _sample_top_k(self) -> int:
        try:
            return max(1, int(self.sample_top_k_var.get().strip()))
        except ValueError:
            return 4

    def _rng_seed(self) -> int:
        try:
            return int(self.seed_var.get().strip())
        except ValueError:
            return 20260419

    def _engine_spec_for_side(self, color: Color) -> EngineSpec:
        panel = self.black_panel if color is Color.BLACK else self.white_panel
        label = "Black Engine" if color is Color.BLACK else "White Engine"
        return panel.to_spec(label)

    def _controller_key(self, color: Color, spec: EngineSpec) -> tuple[object, ...]:
        return (
            color.name,
            spec.name,
            None if spec.model_path is None else str(spec.model_path),
            spec.ml_mode,
            spec.device,
            spec.depth,
            spec.time_seconds,
            spec.learned_weight,
            spec.temperature,
            spec.symmetry_ensemble,
        )

    def _get_or_build_controller(self, color: Color, spec: EngineSpec) -> EngineController:
        key = self._controller_key(color, spec)
        controller = self.controller_cache.get(key)
        if controller is None:
            controller = build_engine_controller(
                color=color,
                model_path=spec.model_path,
                ml_mode=spec.ml_mode,
                depth=spec.depth,
                time_seconds=spec.time_seconds,
                learned_weight=spec.learned_weight,
                device=spec.device,
                temperature=spec.temperature,
                symmetry_ensemble=spec.symmetry_ensemble,
                label=spec.name,
            )
            self.controller_cache[key] = controller
        return controller

    def _can_play_human_move(self) -> bool:
        if self.search_busy or self._is_terminal():
            return False
        if self.mode_var.get() == "human-vs-human":
            return True
        if self.mode_var.get() != "human-vs-engine":
            return False
        return self.position.side_to_move is self._current_human_color()

    def _handle_board_motion(self, event: tk.Event[tk.Canvas]) -> None:
        cell = board_cell_from_point(event.x, event.y, self._metrics())
        if cell != self.hovered_cell:
            self.hovered_cell = cell
            self._redraw_board()

    def _handle_board_leave(self, _event: tk.Event[tk.Canvas]) -> None:
        if self.hovered_cell is not None:
            self.hovered_cell = None
            self._redraw_board()

    def _handle_board_click(self, event: tk.Event[tk.Canvas]) -> None:
        if not self._can_play_human_move():
            return
        cell = board_cell_from_point(event.x, event.y, self._metrics())
        if cell is None:
            return
        row, col = cell
        try:
            move = coord_to_index(row, col)
            next_position, result = play_move(self.position, move)
        except ValueError:
            return
        actor = "Human"
        if self.mode_var.get() == "human-vs-engine":
            actor = "You"
        self._apply_move(move, result, next_position, actor=actor, color=self.position.side_to_move)
        self._clear_analysis("Current position analysis")
        self._advance_autoplay_if_needed()

    def _apply_move(self, move: int, result: MoveResult, next_position: Position, *, actor: str, color: Color) -> None:
        self._truncate_future_if_needed()
        self.history.append(
            PlayedMove(
                previous_position=self.position,
                next_position=next_position,
                move=move,
                result=result,
                actor=actor,
                color=color,
            )
        )
        self.current_ply = len(self.history)
        self.position = next_position
        self.last_move = move
        self._append_log(announce_result(actor, color, move, result))
        self._update_turn_label()
        self._redraw_board()
        if result is MoveResult.WIN:
            self.status_var.set(f"{actor} wins immediately.")
        elif result is MoveResult.LOSS:
            if actor == "You":
                self.status_var.set("You created a losing four. The engine wins.")
            else:
                self.status_var.set(f"{actor} created a losing four. {color.opponent.name.title()} wins.")
        elif len(self.history) >= self._max_moves():
            self.status_var.set(f"Reached the configured move cap ({self._max_moves()}).")
        else:
            self.status_var.set(f"{actor} played {format_move_text(move)}.")

    def _clear_analysis(self, title: str) -> None:
        self.analysis_title_var.set(title)
        self.analysis_engine_var.set("--")
        self.analysis_recommendation_var.set("--")
        self.analysis_score_var.set("--")
        self.analysis_best_var.set("--")
        self.analysis_depth_var.set("--")
        self.analysis_nodes_var.set("--")
        self.analysis_time_var.set("--")
        self.analysis_pv_var.set("--")
        self.analysis_tactics_var.set("--")
        self.analysis_best_move = None
        for item_id in self.top_moves.get_children():
            self.top_moves.delete(item_id)
        self._redraw_board()

    def _toggle_autoplay(self) -> None:
        if self.mode_var.get() != "engine-vs-engine":
            return
        self.autoplay_enabled = not self.autoplay_enabled
        self.autoplay_button.configure(text="Pause Autoplay" if self.autoplay_enabled else "Start Autoplay")
        self.status_var.set("Autoplay running." if self.autoplay_enabled else "Autoplay paused.")
        self._advance_autoplay_if_needed()

    def _new_game(self) -> None:
        self._cancel_inflight_work("Started a fresh game.")
        self.status_var.set("Started a fresh game.")
        self.position = Position.initial()
        self.history.clear()
        self.current_ply = 0
        self.last_move = None
        self.hovered_cell = None
        self._clear_analysis("Current position analysis")
        self._append_log("New game.")
        self._update_turn_label()
        self._redraw_board()
        self._update_mode_hints()
        self.after(120, self._advance_autoplay_if_needed)

    def _navigate_to_ply(self, ply: int) -> None:
        target = max(0, min(ply, len(self.history)))
        if target == self.current_ply:
            return
        self._cancel_inflight_work("Moved to a different point in the game history.")
        self.current_ply = target
        self._clear_analysis("Current position analysis")
        self._sync_position_from_history()
        self.status_var.set(f"Showing ply {self.current_ply} of {len(self.history)}.")

    def _go_start(self) -> None:
        self._navigate_to_ply(0)

    def _go_prev(self) -> None:
        self._navigate_to_ply(self.current_ply - 1)

    def _go_next(self) -> None:
        self._navigate_to_ply(self.current_ply + 1)

    def _go_end(self) -> None:
        self._navigate_to_ply(len(self.history))

    def _branch_here(self) -> None:
        if self._is_at_history_head():
            self.status_var.set("Already at the end of the current line.")
            return
        self._cancel_inflight_work("Discarded future moves from the current branch point.")
        removed = len(self.history) - self.current_ply
        self._truncate_future_if_needed()
        self._clear_analysis("Current position analysis")
        self._sync_position_from_history()
        self.status_var.set(f"Discarded {removed} future move(s).")

    def _analyze_current_position(self) -> None:
        if self.search_busy:
            self.status_var.set("A search is already running.")
            return
        try:
            spec = self._engine_spec_for_side(self.position.side_to_move)
            temperature_plies = self._temperature_plies()
            sample_top_k = self._sample_top_k()
        except ValueError as exc:
            self.status_var.set(f"Invalid analysis settings: {exc}")
            return
        self._submit_worker_task(
            kind="analysis",
            color=self.position.side_to_move,
            position=self.position,
            spec=spec,
            temperature_plies=temperature_plies,
            sample_top_k=sample_top_k,
            plies_played=len(self.history),
        )

    def _advance_autoplay_if_needed(self) -> None:
        if self.search_busy or self._is_terminal() or self.current_ply >= self._max_moves():
            return
        if not self._is_at_history_head():
            return
        side_to_move = self.position.side_to_move
        if self.mode_var.get() == "engine-vs-engine":
            if not self.autoplay_enabled:
                return
        elif self.mode_var.get() == "human-vs-engine":
            if side_to_move is self._current_human_color():
                return
        else:
            return
        try:
            spec = self._engine_spec_for_side(side_to_move)
            temperature_plies = self._temperature_plies()
            sample_top_k = self._sample_top_k()
            seed = self._rng_seed()
        except ValueError as exc:
            self.status_var.set(f"Invalid engine settings: {exc}")
            return

        self._submit_worker_task(
            kind="engine_move",
            color=side_to_move,
            position=self.position,
            spec=spec,
            temperature_plies=temperature_plies,
            sample_top_k=sample_top_k,
            seed=seed + self.current_ply,
            plies_played=self.current_ply,
        )

    def _submit_worker_task(
        self,
        *,
        kind: str,
        color: Color,
        position: Position,
        spec: EngineSpec,
        temperature_plies: int,
        sample_top_k: int,
        plies_played: int,
        seed: int | None = None,
    ) -> None:
        self.search_busy = True
        self.active_task_id += 1
        task_id = self.active_task_id
        label = "analysis" if kind == "analysis" else f"{spec.name} move"
        self.status_var.set(f"Running {label}...")

        def worker() -> None:
            try:
                controller = self._get_or_build_controller(color, spec)
                if kind == "analysis":
                    search_result = controller.engine.search(position, max_depth=controller.depth, max_time_ms=controller.time_ms)
                    snapshot = analyze_tactics(position, include_move_maps=False)
                    payload = {
                        "kind": kind,
                        "task_id": task_id,
                        "controller": controller,
                        "position": position,
                        "search_result": search_result,
                        "snapshot": snapshot,
                    }
                else:
                    move, search_result, sampled = choose_engine_move(
                        position=position,
                        controller=controller,
                        plies_played=plies_played,
                        temperature_plies=temperature_plies,
                        sample_top_k=sample_top_k,
                        rng=random.Random(seed if seed is not None else 0),
                    )
                    payload = {
                        "kind": kind,
                        "task_id": task_id,
                        "controller": controller,
                        "position": position,
                        "search_result": search_result,
                        "move": move,
                        "sampled": sampled,
                        "color": color,
                    }
                self.worker_queue.put(payload)
            except Exception as exc:  # pragma: no cover - surfaced in UI
                self.worker_queue.put({"kind": "error", "task_id": task_id, "error": exc})

        threading.Thread(target=worker, daemon=True).start()

    def _poll_worker_queue(self) -> None:
        try:
            while True:
                payload = self.worker_queue.get_nowait()
                task_id = int(payload["task_id"])
                is_active = task_id == self.active_task_id
                if payload["kind"] == "error":
                    if is_active:
                        self.search_busy = False
                        self.status_var.set(f"Search failed: {payload['error']}")
                        self._append_log(f"Error: {payload['error']}")
                    continue
                if not is_active:
                    self.search_busy = False
                    self.status_var.set("Background search result discarded because the position changed.")
                    self._advance_autoplay_if_needed()
                    continue
                if payload["kind"] == "analysis":
                    self._handle_analysis_result(payload)
                elif payload["kind"] == "engine_move":
                    self._handle_engine_move_result(payload)
        except queue.Empty:
            pass
        finally:
            self.after(WORKER_POLL_MS, self._poll_worker_queue)

    def _handle_analysis_result(self, payload: dict[str, object]) -> None:
        self.search_busy = False
        controller = payload["controller"]
        position = payload["position"]
        search_result = payload["search_result"]
        snapshot = payload["snapshot"]
        assert isinstance(controller, EngineController)
        assert isinstance(position, Position)
        assert isinstance(search_result, SearchResult)
        record_search_totals(controller, search_result)
        self._populate_analysis(
            title="Current position analysis",
            controller=controller,
            position=position,
            search_result=search_result,
            snapshot=snapshot,
        )
        self.status_var.set(f"Analysis complete at depth {search_result.depth}.")
        self._advance_autoplay_if_needed()

    def _handle_engine_move_result(self, payload: dict[str, object]) -> None:
        self.search_busy = False
        controller = payload["controller"]
        position_before = payload["position"]
        search_result = payload["search_result"]
        move = payload["move"]
        sampled = bool(payload["sampled"])
        color = payload["color"]
        assert isinstance(controller, EngineController)
        assert isinstance(position_before, Position)
        assert isinstance(search_result, SearchResult)
        assert isinstance(color, Color)
        record_search_totals(controller, search_result)

        if move is None:
            self.status_var.set(f"{controller.label} found no legal move.")
            self._append_log(f"{controller.label} found no legal move.")
            return

        next_position, result = play_move(position_before, move)
        self._populate_analysis(
            title="Latest engine search (before move)",
            controller=controller,
            position=position_before,
            search_result=search_result,
            snapshot=None,
        )
        self._apply_move(move, result, next_position, actor=controller.label, color=color)
        if sampled and search_result.best_move is not None:
            self._append_log(
                f"{controller.label} sampled from its opening shortlist instead of taking strict best move {format_move_text(search_result.best_move)}."
            )
        self._advance_autoplay_if_needed()

    def _populate_analysis(
        self,
        *,
        title: str,
        controller: EngineController,
        position: Position,
        search_result: SearchResult,
        snapshot: object | None,
    ) -> None:
        self.analysis_title_var.set(title)
        side = "Black" if position.side_to_move is Color.BLACK else "White"
        self.analysis_engine_var.set(f"{controller.label} ({side} to move)")
        self.analysis_best_move = search_result.best_move
        if search_result.best_move is None:
            self.analysis_recommendation_var.set("No legal move recommendation for this position.")
        else:
            self.analysis_recommendation_var.set(f"Recommended move: {format_move_text(search_result.best_move)}")
        self.analysis_score_var.set(format_score_text(search_result.score))
        self.analysis_best_var.set(format_move_text(search_result.best_move))
        self.analysis_depth_var.set(str(search_result.depth))
        total_nodes = search_result.stats.nodes + search_result.stats.quiescence_nodes
        self.analysis_nodes_var.set(f"{total_nodes} total ({search_result.stats.nodes} + {search_result.stats.quiescence_nodes} q)")
        self.analysis_time_var.set(f"{search_result.stats.elapsed_seconds:.3f}s")
        self.analysis_pv_var.set(format_pv_text(search_result.principal_variation))
        if snapshot is None:
            self.analysis_tactics_var.set("--")
        else:
            self.analysis_tactics_var.set(
                "wins="
                f"{len(snapshot.winning_moves)}  blocks={len(snapshot.forced_blocks)}  "
                f"safe threats={len(snapshot.safe_threats)}  double threats={len(snapshot.double_threats)}"
            )
        for item_id in self.top_moves.get_children():
            self.top_moves.delete(item_id)
        for rank, move_text, score_text in top_root_rows(search_result):
            self.top_moves.insert("", "end", values=(rank, move_text, score_text))
        self._redraw_board()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app = UkumogGUI(args)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
