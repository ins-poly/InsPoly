from __future__ import annotations

import json
import queue
import subprocess
import threading
import tkinter as tk
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median
from tkinter import messagebox, ttk

from app.config import AppConfig
from app.polymarket import MarketStatus, PolymarketClient, WalletPosition
from app.scanner import ProgressEvent, Scanner
from app.site_categories import SiteCategory
from app.storage import Storage


BG = "#08111f"
SURFACE = "#0d1a2b"
SURFACE_ALT = "#11233a"
SURFACE_SOFT = "#0a1524"
BORDER = "#23395d"
BORDER_STRONG = "#35507c"
TEXT = "#eaf1ff"
TEXT_MUTED = "#a9b9d6"
TEXT_SUBTLE = "#7f91b3"
ACCENT = "#6f86ff"
ACCENT_SOFT = "#24365e"
ACCENT_HOVER = "#8aa0ff"
SUCCESS = "#59b48a"
AMBER = "#d6a446"
RED = "#d95b74"

RISK_STYLES = {
    "Strong Risk": {"bg": "#34151d", "fg": "#ffd0d8", "border": "#83404f"},
    "Worth a look": {"bg": "#332710", "fg": "#ffe0a1", "border": "#86642b"},
    "Low Risk": {"bg": "#11251c", "fg": "#b5e6d0", "border": "#2f7357"},
}


class ActionChip(tk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        *,
        text: str,
        command: object,
        bg: str,
        fg: str,
        hover_bg: str,
        disabled_bg: str,
        disabled_fg: str,
        border: str,
        font: tuple[str, int, str] | tuple[str, int],
        padx: int,
        pady: int,
    ) -> None:
        super().__init__(
            parent,
            bg=bg,
            highlightbackground=border,
            highlightcolor=border,
            highlightthickness=1,
            bd=0,
            cursor="hand2",
        )
        self._command = command
        self._bg = bg
        self._fg = fg
        self._hover_bg = hover_bg
        self._disabled_bg = disabled_bg
        self._disabled_fg = disabled_fg
        self._state = "normal"
        self._pressed = False
        self._label = tk.Label(self, text=text, bg=bg, fg=fg, font=font, padx=padx, pady=pady, cursor="hand2")
        self._label.pack()
        for widget in (self, self._label):
            widget.bind("<Button-1>", self._handle_click, add="+")
            widget.bind("<Enter>", self._handle_enter, add="+")
            widget.bind("<Leave>", self._handle_leave, add="+")

    def _handle_click(self, _event: tk.Event) -> None:
        if self._state == "disabled":
            return
        self._pressed = True
        self._apply_visual_state()
        callback = self._command
        if callable(callback):
            callback()

    def _handle_enter(self, _event: tk.Event) -> None:
        if self._state != "disabled":
            self._pressed = True
            self._apply_visual_state()

    def _handle_leave(self, _event: tk.Event) -> None:
        self._pressed = False
        self._apply_visual_state()

    def _apply_visual_state(self) -> None:
        if self._state == "disabled":
            bg = self._disabled_bg
            fg = self._disabled_fg
            cursor = "arrow"
        else:
            bg = self._hover_bg if self._pressed else self._bg
            fg = self._fg
            cursor = "hand2"
        super().configure(bg=bg, cursor=cursor)
        self._label.configure(bg=bg, fg=fg, cursor=cursor)

    def configure(self, cnf: dict | None = None, **kw: object) -> object:
        options = dict(cnf or {})
        options.update(kw)
        if "text" in options:
            self._label.configure(text=options.pop("text"))
        if "command" in options:
            self._command = options.pop("command")
        if "bg" in options:
            self._bg = str(options["bg"])
        if "fg" in options:
            self._fg = str(options["fg"])
        if "activebackground" in options:
            self._hover_bg = str(options.pop("activebackground"))
        if "state" in options:
            self._state = str(options.pop("state"))
        result = super().configure(options)
        self._apply_visual_state()
        return result

    config = configure


class DesktopApp:
    def __init__(self) -> None:
        self.config = AppConfig.load()
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        self.storage.init()
        self.client = PolymarketClient()
        self.scanner = Scanner(self.client, self.storage, self.config)
        self.site_categories = self.client.fetch_site_categories()

        self.root = tk.Tk()
        self.root.title("InsPoly Scanner")
        self.root.geometry("1620x980")
        self.root.minsize(1360, 860)
        self.root.configure(bg=BG)

        self.style = ttk.Style()
        self._configure_styles()

        self.progress_var = tk.DoubleVar(value=0)
        self.status_var = tk.StringVar(value="Ready")
        self.status_meta_var = tk.StringVar(value="No scan running")
        self.lookback_var = tk.StringVar(value=self.config.default_lookback)
        self.min_amount_var = tk.StringVar(value="10000")
        self.max_amount_var = tk.StringVar(value="")
        self.output_path_var = tk.StringVar(value="No output loaded")
        self.sort_var = tk.StringVar(value="Risk first")
        self.risk_filter_var = tk.StringVar(value="All risks")
        self.detail_mode_var = tk.StringVar(value="Human summary")
        self.scan_state_var = tk.StringVar(value="Ready")
        self.selected_run_var = tk.StringVar(value="Selected run: none")
        self.applied_filters_var = tk.StringVar(value="Filters: not applied")
        self.flagged_count_var = tk.StringVar(value="Flagged: 0")
        self.analysis_mode_var = tk.StringVar(value="Analysis: quick")
        self.selection_state_var = tk.StringVar(value="Selected case: none")
        self.summary_title_var = tk.StringVar(value="Run summary")
        self.progress_label_var = tk.StringVar(value="Ready")
        self.sort_menu: tk.Menu | None = None

        default_labels = {"Politics", "World", "Ukraine", "Middle East"}
        self.category_vars = {
            category.label: tk.BooleanVar(value=category.label in default_labels)
            for category in self.site_categories
        }

        self.event_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.current_cases: list[dict] = []
        self.filtered_cases: list[dict] = []
        self.current_report: dict | None = None
        self.current_output_path: Path | None = None
        self.selected_case: dict | None = None
        self.selected_case_id: str | None = None
        self.output_run_records: list[dict] = []
        self.case_detail_cache: dict[str, dict] = {}
        self.card_widgets: dict[str, tk.Frame] = {}
        self.summary_metric_labels: dict[str, tk.StringVar] = {}
        self._scroll_targets: dict[str, tk.Widget] = {}
        self._active_scroll_target: tk.Widget | None = None
        self._context_menu = tk.Menu(self.root, tearoff=0, bg=SURFACE, fg=TEXT, activebackground=ACCENT)
        self._context_widget: tk.Widget | None = None
        self.analyst_state_path = self.config.data_dir / "analyst_state.json"
        self.analyst_state = self._load_analyst_state()
        self.notes_text: tk.Text | None = None

        self._build_ui()
        self._install_global_scroll()
        self._refresh_recent_outputs()
        self._update_applied_filters()
        self._update_status_bar()
        self.root.after(200, self._poll_events)

    def _configure_styles(self) -> None:
        self.style.theme_use("clam")
        self.style.configure(
            "Dark.Horizontal.TProgressbar",
            troughcolor=SURFACE_SOFT,
            background=ACCENT,
            bordercolor=BORDER,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            thickness=12,
        )
        self.style.configure(
            "Dark.TCombobox",
            fieldbackground=SURFACE_SOFT,
            background=SURFACE_SOFT,
            foreground=TEXT,
            arrowcolor=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            insertcolor=TEXT,
        )
        self.style.map("Dark.TCombobox", fieldbackground=[("readonly", SURFACE_SOFT)], foreground=[("readonly", TEXT)])
        self.root.option_add("*TCombobox*Listbox*Background", SURFACE)
        self.root.option_add("*TCombobox*Listbox*Foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox*selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox*selectForeground", TEXT)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        header = tk.Frame(self.root, bg=BG, padx=24, pady=20)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=0)

        title_block = tk.Frame(header, bg=BG)
        title_block.grid(row=0, column=0, sticky="nw")
        tk.Label(
            title_block,
            text="INS POLY SCANNER",
            bg=BG,
            fg=TEXT_SUBTLE,
            font=("SF Pro Display", 10, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title_block,
            text="Suspicious Trading Review Console",
            bg=BG,
            fg=TEXT,
            font=("SF Pro Display", 24, "bold"),
        ).pack(anchor="w", pady=(4, 0))
        actions = tk.Frame(header, bg=BG)
        actions.grid(row=0, column=1, sticky="ne")
        self.start_button = self._action_button(actions, "Start scan", self._toggle_scan, primary=True)
        self.start_button.pack(side="left")
        self._action_button(actions, "Open output", self._open_latest_output).pack(side="left", padx=(10, 0))
        self._action_button(actions, "Copy cards", self._copy_cards_text).pack(side="left", padx=(10, 0))

        status_row = tk.Frame(header, bg=BG)
        status_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        status_row.columnconfigure(1, weight=1)

        status_meta = tk.Frame(status_row, bg=BG)
        status_meta.grid(row=0, column=0, sticky="w", padx=(0, 16))
        tk.Label(status_meta, textvariable=self.selected_run_var, bg=BG, fg=TEXT_MUTED, font=("SF Pro Text", 10)).pack(anchor="w")
        tk.Label(status_meta, textvariable=self.progress_label_var, bg=BG, fg=TEXT, font=("SF Pro Text", 10, "bold")).pack(
            anchor="w", pady=(4, 0)
        )

        progress_wrap = tk.Frame(status_row, bg=BG)
        progress_wrap.grid(row=0, column=1, sticky="ew")
        self.progress_bar = ttk.Progressbar(
            progress_wrap,
            variable=self.progress_var,
            maximum=100,
            style="Dark.Horizontal.TProgressbar",
        )
        self.progress_bar.pack(fill="x")
        self.progress_status_label = tk.Label(
            progress_wrap,
            textvariable=self.status_meta_var,
            bg=BG,
            fg=TEXT_MUTED,
            anchor="w",
            justify="left",
            font=("SF Pro Text", 10),
        )
        self.progress_status_label.pack(fill="x", pady=(6, 0))

        content = tk.Frame(self.root, bg=BG, padx=24, pady=0)
        content.grid(row=1, column=0, sticky="nsew")
        content.columnconfigure(0, weight=0)
        content.columnconfigure(1, weight=6)
        content.columnconfigure(2, weight=8)
        content.rowconfigure(0, weight=1)

        self.left_rail = tk.Frame(content, bg=BG, width=292)
        self.left_rail.grid(row=0, column=0, sticky="nsw", padx=(0, 18))
        self.center_column = tk.Frame(content, bg=BG)
        self.center_column.grid(row=0, column=1, sticky="nsew", padx=(0, 18))
        self.right_column = tk.Frame(content, bg=BG)
        self.right_column.grid(row=0, column=2, sticky="nsew")

        self.left_rail.grid_propagate(False)
        self.left_canvas = tk.Canvas(self.left_rail, bg=BG, highlightthickness=0, bd=0, width=292, takefocus=1)
        self.left_scrollbar = tk.Scrollbar(
            self.left_rail,
            orient="vertical",
            command=self.left_canvas.yview,
            bg=SURFACE_SOFT,
            troughcolor=SURFACE_SOFT,
            activebackground=ACCENT,
            highlightthickness=0,
        )
        self.left_inner = tk.Frame(self.left_canvas, bg=BG)
        self.left_inner.bind(
            "<Configure>",
            lambda _event: self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all")),
        )
        self.left_canvas_window = self.left_canvas.create_window((0, 0), window=self.left_inner, anchor="nw")
        self.left_canvas.bind(
            "<Configure>",
            lambda event: self.left_canvas.itemconfigure(self.left_canvas_window, width=max(event.width - 2, 1)),
        )
        self.left_canvas.configure(yscrollcommand=self.left_scrollbar.set)
        self.left_canvas.pack(side="left", fill="both", expand=True)
        self.left_scrollbar.pack(side="right", fill="y")
        self._register_scroll_target(self.left_canvas, self.left_canvas, self.left_inner, self.left_rail)
        self._build_left_rail()
        self._build_center_column()
        self._build_right_column()
        self._build_status_bar()

    def _build_left_rail(self) -> None:
        rail_parent = self.left_inner

        filters_panel = self._panel(rail_parent, "Scan filters", compact=True)
        filters_panel.pack(fill="x")
        self._field_label(filters_panel, "Lookback").pack(anchor="w")
        ttk.Combobox(
            filters_panel,
            textvariable=self.lookback_var,
            values=("1h", "4h", "12h", "24h", "7d"),
            state="readonly",
            width=16,
            style="Dark.TCombobox",
        ).pack(fill="x", pady=(6, 14))

        amount_row = tk.Frame(filters_panel, bg=SURFACE)
        amount_row.pack(fill="x")
        left_amount = tk.Frame(amount_row, bg=SURFACE)
        left_amount.pack(side="left", fill="x", expand=True)
        right_amount = tk.Frame(amount_row, bg=SURFACE)
        right_amount.pack(side="left", fill="x", expand=True, padx=(10, 0))
        self._field_label(left_amount, "Min size").pack(anchor="w")
        min_entry = self._entry(left_amount, self.min_amount_var)
        min_entry.pack(fill="x", pady=(6, 0))
        self._field_label(right_amount, "Max size").pack(anchor="w")
        max_entry = self._entry(right_amount, self.max_amount_var)
        max_entry.pack(fill="x", pady=(6, 0))
        self._enable_context_menu(min_entry)
        self._enable_context_menu(max_entry)

        self._field_label(filters_panel, "Risk level").pack(anchor="w", pady=(16, 6))
        risk_row = tk.Frame(filters_panel, bg=SURFACE)
        risk_row.pack(fill="x")
        for label in ("All risks", "Strong Risk", "Worth a look", "Low Risk"):
            self._filter_button(risk_row, label, self.risk_filter_var, self._apply_case_filters).pack(
                side="left", padx=(0, 6)
            )

        self._field_label(filters_panel, "Topics").pack(anchor="w", pady=(16, 6))
        categories_outer = tk.Frame(filters_panel, bg=SURFACE)
        categories_outer.pack(fill="x")
        categories_canvas = tk.Canvas(
            categories_outer,
            bg=SURFACE,
            highlightthickness=0,
            bd=0,
            height=176,
            takefocus=1,
        )
        self.categories_canvas = categories_canvas
        categories_scroll = tk.Scrollbar(
            categories_outer,
            orient="vertical",
            command=categories_canvas.yview,
            bg=SURFACE_SOFT,
            troughcolor=SURFACE_SOFT,
            activebackground=ACCENT,
            highlightthickness=0,
        )
        self.categories_inner = tk.Frame(categories_canvas, bg=SURFACE)
        self.categories_inner.bind(
            "<Configure>",
            lambda _event: categories_canvas.configure(scrollregion=categories_canvas.bbox("all")),
        )
        self.categories_canvas_window = categories_canvas.create_window((0, 0), window=self.categories_inner, anchor="nw")
        categories_canvas.bind(
            "<Configure>",
            lambda event: categories_canvas.itemconfigure(self.categories_canvas_window, width=max(event.width - 2, 1)),
        )
        categories_canvas.configure(yscrollcommand=categories_scroll.set)
        categories_canvas.pack(side="left", fill="x", expand=True)
        categories_scroll.pack(side="right", fill="y")
        self._register_scroll_target(categories_canvas, categories_canvas, self.categories_inner)

        for idx in range(2):
            self.categories_inner.columnconfigure(idx, weight=1)
        for index, category in enumerate(self.site_categories):
            row = index // 2
            column = index % 2
            chip = self._toggle_chip(
                self.categories_inner,
                category.label,
                self.category_vars[category.label],
                self._apply_case_filters,
            )
            chip.grid(row=row, column=column, sticky="w", padx=(0, 8), pady=4)

        self._register_scroll_tree(self.categories_canvas, self.categories_inner)
        self._register_scroll_tree(
            self.left_canvas,
            filters_panel,
            skip={str(self.categories_canvas), str(self.categories_inner)},
        )

        summary_panel = self._panel(rail_parent, variable=self.summary_title_var, compact=True)
        summary_panel.pack(fill="x", pady=(16, 0))
        metrics_grid = tk.Frame(summary_panel, bg=SURFACE)
        metrics_grid.pack(fill="x")
        metrics = [
            ("Flagged cards", "flagged"),
            ("Strong risk", "strong"),
            ("Worth a look", "worth"),
            ("Low risk", "low"),
        ]
        for idx, (label, key) in enumerate(metrics):
            tile = tk.Frame(
                metrics_grid,
                bg=SURFACE_SOFT,
                highlightbackground=BORDER,
                highlightcolor=BORDER,
                highlightthickness=1,
                bd=0,
                padx=10,
                pady=10,
            )
            tile.grid(row=idx // 2, column=idx % 2, sticky="nsew", padx=4, pady=4)
            metrics_grid.columnconfigure(idx % 2, weight=1)
            tk.Label(tile, text=label, bg=SURFACE_SOFT, fg=TEXT_SUBTLE, font=("SF Pro Text", 10)).pack(anchor="w")
            value_var = tk.StringVar(value="0")
            self.summary_metric_labels[key] = value_var
            tk.Label(tile, textvariable=value_var, bg=SURFACE_SOFT, fg=TEXT, font=("SF Pro Display", 20, "bold")).pack(
                anchor="w", pady=(4, 0)
            )

        self.run_context_label = tk.Label(
            summary_panel,
            text="No run loaded yet.",
            bg=SURFACE,
            fg=TEXT_MUTED,
            justify="left",
            wraplength=260,
            font=("SF Pro Text", 10),
        )
        self.run_context_label.pack(anchor="w", pady=(14, 0))
        self._bind_dynamic_wrap(summary_panel, self.run_context_label, pad=28, min_width=220)

        self._register_scroll_tree(self.left_canvas, summary_panel)

        recent_panel = self._panel(rail_parent, "Recent runs", compact=True)
        recent_panel.pack(fill="both", expand=True, pady=(16, 0))
        recent_header = tk.Frame(recent_panel, bg=SURFACE)
        recent_header.pack(fill="x")
        self._action_button(recent_header, "Copy run list", self._copy_outputs_list, compact=True).pack(side="right")
        tk.Label(
            recent_header,
            text="Runs are grouped by scan settings and flagged output.",
            bg=SURFACE,
            fg=TEXT_SUBTLE,
            font=("SF Pro Text", 9),
        ).pack(anchor="w")

        runs_outer = tk.Frame(recent_panel, bg=SURFACE)
        self.runs_outer = runs_outer
        runs_outer.pack(fill="both", expand=True, pady=(10, 0))
        self.runs_canvas = tk.Canvas(runs_outer, bg=SURFACE, highlightthickness=0, bd=0, takefocus=1)
        runs_scroll = tk.Scrollbar(
            runs_outer,
            orient="vertical",
            command=self.runs_canvas.yview,
            bg=SURFACE_SOFT,
            troughcolor=SURFACE_SOFT,
            activebackground=ACCENT,
            highlightthickness=0,
        )
        self.runs_inner = tk.Frame(self.runs_canvas, bg=SURFACE)
        self.runs_inner.bind("<Configure>", lambda _event: self.runs_canvas.configure(scrollregion=self.runs_canvas.bbox("all")))
        self.runs_canvas_window = self.runs_canvas.create_window((0, 0), window=self.runs_inner, anchor="nw")
        self.runs_canvas.bind(
            "<Configure>",
            lambda event: self.runs_canvas.itemconfigure(self.runs_canvas_window, width=max(event.width - 2, 1)),
        )
        self.runs_canvas.configure(yscrollcommand=runs_scroll.set)
        self.runs_canvas.pack(side="left", fill="both", expand=True)
        runs_scroll.pack(side="right", fill="y")
        self._register_scroll_target(self.runs_canvas, self.runs_canvas, self.runs_inner)
        self._register_scroll_tree(
            self.left_canvas,
            recent_panel,
            skip={str(self.runs_outer), str(self.runs_canvas), str(self.runs_inner)},
        )

    def _build_center_column(self) -> None:
        toolbar = tk.Frame(self.center_column, bg=BG)
        toolbar.pack(fill="x", pady=(0, 14))
        left = tk.Frame(toolbar, bg=BG)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(
            left,
            text="Flagged trade cards",
            bg=BG,
            fg=TEXT,
            font=("SF Pro Display", 18, "bold"),
        ).pack(anchor="w")
        self.cards_subtitle = tk.Label(
            left,
            text="Run the scanner or load a previous run to review flagged cases.",
            bg=BG,
            fg=TEXT_MUTED,
            font=("SF Pro Text", 11),
        )
        self.cards_subtitle.pack(anchor="w", pady=(4, 0))

        right = tk.Frame(toolbar, bg=BG)
        right.pack(side="right")
        self.sort_button = self._action_button(right, f"Sort: {self.sort_var.get()}", self._show_sort_menu, compact=True)
        self.sort_button.pack(anchor="e")
        self.sort_var.trace_add("write", lambda *_args: self._apply_case_filters())
        self.sort_var.trace_add("write", lambda *_args: self.sort_button.configure(text=f"Sort: {self.sort_var.get()}"))
        self._action_button(right, "Copy visible", self._copy_cards_text, compact=True).pack(anchor="e", pady=(8, 0))

        cards_panel = self._panel(self.center_column, compact=True)
        cards_panel.pack(fill="both", expand=True)
        self.cards_canvas = tk.Canvas(cards_panel, bg=SURFACE, highlightthickness=0, bd=0, takefocus=1)
        self.cards_scrollbar = tk.Scrollbar(
            cards_panel,
            orient="vertical",
            command=self.cards_canvas.yview,
            bg=SURFACE_SOFT,
            troughcolor=SURFACE_SOFT,
            activebackground=ACCENT,
            highlightthickness=0,
        )
        self.cards_inner = tk.Frame(self.cards_canvas, bg=SURFACE)
        self.cards_inner.bind("<Configure>", lambda _event: self.cards_canvas.configure(scrollregion=self.cards_canvas.bbox("all")))
        self.cards_canvas_window = self.cards_canvas.create_window((0, 0), window=self.cards_inner, anchor="nw")
        self.cards_canvas.bind(
            "<Configure>",
            lambda event: self.cards_canvas.itemconfigure(self.cards_canvas_window, width=max(event.width - 2, 1)),
        )
        self.cards_canvas.configure(yscrollcommand=self.cards_scrollbar.set)
        self.cards_canvas.pack(side="left", fill="both", expand=True)
        self.cards_scrollbar.pack(side="right", fill="y")
        self._register_scroll_target(self.cards_canvas, self.cards_canvas, self.cards_inner)

    def _build_right_column(self) -> None:
        self.detail_header = self._panel(self.right_column, compact=True)
        self.detail_header.pack(fill="x")
        self.detail_content = self._panel(self.right_column, compact=True)
        self.detail_content.pack(fill="both", expand=True, pady=(16, 0))

        detail_top = tk.Frame(self.detail_content, bg=SURFACE)
        detail_top.pack(fill="x")
        self._filter_button(detail_top, "Human summary", self.detail_mode_var, self._render_detail_panel).pack(side="left")
        self._filter_button(detail_top, "Technical detail", self.detail_mode_var, self._render_detail_panel).pack(
            side="left", padx=(8, 0)
        )
        self._action_button(detail_top, "Copy analysis", self._copy_detail_text, compact=True).pack(side="right")

        detail_outer = tk.Frame(self.detail_content, bg=SURFACE)
        detail_outer.pack(fill="both", expand=True, pady=(12, 0))
        self.detail_canvas = tk.Canvas(detail_outer, bg=SURFACE, highlightthickness=0, bd=0, takefocus=1)
        detail_scroll = tk.Scrollbar(
            detail_outer,
            orient="vertical",
            command=self.detail_canvas.yview,
            bg=SURFACE_SOFT,
            troughcolor=SURFACE_SOFT,
            activebackground=ACCENT,
            highlightthickness=0,
        )
        self.detail_inner = tk.Frame(self.detail_canvas, bg=SURFACE)
        self.detail_inner.bind("<Configure>", lambda _event: self.detail_canvas.configure(scrollregion=self.detail_canvas.bbox("all")))
        self.detail_canvas_window = self.detail_canvas.create_window((0, 0), window=self.detail_inner, anchor="nw")
        self.detail_canvas.bind(
            "<Configure>",
            lambda event: self.detail_canvas.itemconfigure(self.detail_canvas_window, width=max(event.width - 2, 1)),
        )
        self.detail_canvas.configure(yscrollcommand=detail_scroll.set)
        self.detail_canvas.pack(side="left", fill="both", expand=True)
        detail_scroll.pack(side="right", fill="y")
        self._register_scroll_target(self.detail_canvas, self.detail_canvas, self.detail_inner)
        self._render_detail_panel()

    def _build_status_bar(self) -> None:
        status_bar = tk.Frame(self.root, bg="#070b12", padx=24, pady=12, highlightbackground=BORDER, highlightthickness=1)
        status_bar.grid(row=2, column=0, sticky="ew", pady=(18, 0))
        for idx in range(5):
            status_bar.columnconfigure(idx, weight=1 if idx < 4 else 0)

        labels = [
            self.scan_state_var,
            self.flagged_count_var,
            self.selection_state_var,
            self.analysis_mode_var,
            self.applied_filters_var,
        ]
        for idx, variable in enumerate(labels):
            tk.Label(
                status_bar,
                textvariable=variable,
                bg="#070b12",
                fg=TEXT_MUTED,
                font=("SF Pro Text", 10),
                anchor="w",
                justify="left",
            ).grid(row=0, column=idx, sticky="w", padx=(0, 18))

    def _panel(
        self,
        parent: tk.Widget,
        title: str | None = None,
        variable: tk.StringVar | None = None,
        *,
        compact: bool = False,
    ) -> tk.Frame:
        panel = tk.Frame(
            parent,
            bg=SURFACE,
            highlightbackground=BORDER,
            highlightcolor=BORDER,
            highlightthickness=1,
            bd=0,
            padx=14 if compact else 16,
            pady=12 if compact else 16,
        )
        if title or variable is not None:
            label = title if title is not None else ""
            tk.Label(
                panel,
                text=label,
                textvariable=variable,
                bg=SURFACE,
                fg=TEXT,
                font=("SF Pro Display", 12, "bold"),
                anchor="w",
            ).pack(anchor="w", pady=(0, 12))
        return panel

    def _field_label(self, parent: tk.Widget, text: str) -> tk.Label:
        return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=TEXT_SUBTLE, font=("SF Pro Text", 10, "bold"))

    def _entry(self, parent: tk.Widget, variable: tk.StringVar) -> tk.Entry:
        return tk.Entry(
            parent,
            textvariable=variable,
            bg=SURFACE_SOFT,
            fg=TEXT,
            insertbackground=TEXT,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            highlightthickness=1,
            relief="flat",
            bd=0,
            font=("SF Pro Text", 11),
        )

    def _action_button(self, parent: tk.Widget, text: str, command: object, *, primary: bool = False, compact: bool = False) -> ActionChip:
        return ActionChip(
            parent,
            text=text,
            command=command,
            bg=ACCENT if primary else SURFACE_ALT,
            fg=TEXT,
            hover_bg=ACCENT_HOVER if primary else "#1f3456",
            disabled_bg="#16263f",
            disabled_fg=TEXT_SUBTLE,
            border=BORDER,
            font=("SF Pro Text", 10, "bold" if primary else "normal"),
            padx=14 if compact else 18,
            pady=7 if compact else 10,
        )

    def _filter_button(
        self,
        parent: tk.Widget,
        label: str,
        variable: tk.StringVar,
        callback: object,
    ) -> ActionChip:
        def on_click() -> None:
            variable.set(label)
            callback()

        button = ActionChip(
            parent,
            text=label,
            command=on_click,
            bg=ACCENT_SOFT if variable.get() == label else SURFACE_ALT,
            fg=TEXT if variable.get() == label else TEXT_MUTED,
            hover_bg="#31497f" if variable.get() == label else "#1c2d4b",
            disabled_bg="#16263f",
            disabled_fg=TEXT_SUBTLE,
            border=BORDER,
            font=("SF Pro Text", 10),
            padx=10,
            pady=7,
        )

        def refresh(*_args: object) -> None:
            active = variable.get() == label
            button.configure(
                bg=ACCENT_SOFT if active else SURFACE_ALT,
                fg=TEXT if active else TEXT_MUTED,
                activebackground="#31497f" if active else "#1c2d4b",
            )

        variable.trace_add("write", refresh)
        return button

    def _toggle_chip(
        self,
        parent: tk.Widget,
        label: str,
        variable: tk.BooleanVar,
        callback: object,
    ) -> ActionChip:
        def on_click() -> None:
            variable.set(not variable.get())
            callback()

        button = ActionChip(
            parent,
            text=label,
            command=on_click,
            bg=ACCENT_SOFT if variable.get() else SURFACE_ALT,
            fg=TEXT if variable.get() else TEXT_MUTED,
            hover_bg="#31497f" if variable.get() else "#1c2d4b",
            disabled_bg="#16263f",
            disabled_fg=TEXT_SUBTLE,
            border="#3d52a3" if variable.get() else BORDER,
            font=("SF Pro Text", 10),
            padx=12,
            pady=7,
        )

        def refresh(*_args: object) -> None:
            active = variable.get()
            button.configure(
                bg=ACCENT_SOFT if active else SURFACE_ALT,
                fg=TEXT if active else TEXT_MUTED,
                activebackground="#31497f" if active else "#1c2d4b",
            )
            button.configure(highlightbackground="#3d52a3" if active else BORDER, highlightcolor="#3d52a3" if active else BORDER)

        variable.trace_add("write", refresh)
        return button

    def _badge(self, parent: tk.Widget, text: str, severity: str) -> tk.Label:
        style = RISK_STYLES.get(severity, {"bg": SURFACE_SOFT, "fg": TEXT_MUTED, "border": BORDER})
        badge = tk.Label(
            parent,
            text=text,
            bg=style["bg"],
            fg=style["fg"],
            padx=10,
            pady=5,
            font=("SF Pro Text", 10, "bold"),
            highlightbackground=style["border"],
            highlightcolor=style["border"],
            highlightthickness=1,
            bd=0,
        )
        return badge

    def _metric_tile(self, parent: tk.Widget, label: str, value: str) -> tk.Frame:
        tile = tk.Frame(
            parent,
            bg=SURFACE_SOFT,
            highlightbackground=BORDER,
            highlightcolor=BORDER,
            highlightthickness=1,
            bd=0,
            padx=12,
            pady=12,
        )
        tk.Label(tile, text=label, bg=SURFACE_SOFT, fg=TEXT_SUBTLE, font=("SF Pro Text", 10)).pack(anchor="w")
        value_label = tk.Label(tile, text=value, bg=SURFACE_SOFT, fg=TEXT, font=("SF Pro Text", 12, "bold"), justify="left")
        value_label.pack(anchor="w", fill="x", pady=(6, 0))
        self._bind_dynamic_wrap(tile, value_label, pad=24, min_width=140)
        return tile

    def _bind_dynamic_wrap(self, container: tk.Widget, label: tk.Label, *, pad: int = 24, min_width: int = 120) -> None:
        def update_wrap(_event: tk.Event | None = None) -> None:
            width = container.winfo_width()
            if width <= 1:
                return
            label.configure(wraplength=max(min_width, width - pad))

        container.bind("<Configure>", update_wrap, add="+")
        self.root.after_idle(update_wrap)

    def _section_panel(self, parent: tk.Widget, title: str) -> tk.Frame:
        panel = tk.Frame(
            parent,
            bg=SURFACE_ALT,
            highlightbackground=BORDER,
            highlightcolor=BORDER,
            highlightthickness=1,
            bd=0,
            padx=14,
            pady=14,
        )
        tk.Label(panel, text=title, bg=SURFACE_ALT, fg=TEXT, font=("SF Pro Display", 12, "bold")).pack(anchor="w")
        return panel

    def _install_global_scroll(self) -> None:
        self.root.bind_all("<MouseWheel>", self._dispatch_mousewheel, add="+")
        self.root.bind_all("<Button-4>", lambda event: self._dispatch_linux_scroll(event, -1), add="+")
        self.root.bind_all("<Button-5>", lambda event: self._dispatch_linux_scroll(event, 1), add="+")
        self.root.bind_all("<Command-c>", self._handle_copy_shortcut, add="+")
        self.root.bind_all("<Command-a>", self._handle_select_all_shortcut, add="+")
        self.root.bind_all("<Control-c>", self._handle_copy_shortcut, add="+")
        self.root.bind_all("<Control-a>", self._handle_select_all_shortcut, add="+")

    def _enable_context_menu(self, widget: tk.Widget) -> None:
        widget.bind("<Button-2>", self._show_context_menu, add="+")
        widget.bind("<Button-3>", self._show_context_menu, add="+")
        widget.bind("<Control-Button-1>", self._show_context_menu, add="+")

    def _show_context_menu(self, event: tk.Event) -> str:
        widget = event.widget
        self._context_widget = widget
        self._context_menu.delete(0, tk.END)
        self._context_menu.add_command(label="Copy", command=self._copy_context_selection)
        self._context_menu.add_command(label="Select All", command=self._select_all_context)
        if self.selected_case is not None:
            self._context_menu.add_separator()
            self._context_menu.add_command(label="Copy selected case", command=self._copy_detail_text)
            self._context_menu.add_command(label="Copy quick summary", command=lambda: self._copy_case_summary(self.selected_case))
        try:
            self._context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._context_menu.grab_release()
        return "break"

    def _copy_context_selection(self) -> None:
        widget = self._context_widget
        if widget is None:
            return
        value = self._selected_text_from_widget(widget)
        if not value and isinstance(widget, tk.Text):
            value = widget.get("1.0", tk.END).strip()
        if not value and isinstance(widget, tk.Entry):
            value = widget.get()
        if value:
            self._copy_text(value)

    def _select_all_context(self) -> None:
        widget = self._context_widget
        if widget is None:
            return
        if isinstance(widget, tk.Text):
            widget.tag_add(tk.SEL, "1.0", tk.END)
            widget.mark_set(tk.INSERT, "1.0")
            widget.see(tk.INSERT)
            return
        if isinstance(widget, tk.Entry):
            widget.selection_range(0, tk.END)
            widget.icursor(0)

    def _selected_text_from_widget(self, widget: tk.Widget) -> str:
        try:
            if isinstance(widget, tk.Text):
                return widget.get(tk.SEL_FIRST, tk.SEL_LAST)
            if isinstance(widget, tk.Entry):
                return widget.selection_get()
        except tk.TclError:
            return ""
        return ""

    def _handle_copy_shortcut(self, _event: tk.Event) -> str:
        widget = self.root.focus_get()
        self._context_widget = widget
        if widget is not None:
            self._copy_context_selection()
        elif self.selected_case is not None:
            self._copy_detail_text()
        return "break"

    def _handle_select_all_shortcut(self, _event: tk.Event) -> str:
        widget = self.root.focus_get()
        if widget is None:
            return "break"
        self._context_widget = widget
        self._select_all_context()
        return "break"

    def _register_scroll_target(self, target: tk.Widget, *widgets: tk.Widget) -> None:
        for widget in widgets:
            self._scroll_targets[str(widget)] = target
            widget.bind("<Enter>", lambda _event, t=target: self._set_active_scroll_target(t), add="+")
            widget.bind("<Button-1>", lambda _event, t=target: self._set_active_scroll_target(t), add="+")
            widget.bind("<Motion>", lambda _event, t=target: self._set_active_scroll_target(t), add="+")
            widget.bind("<MouseWheel>", lambda event, t=target: self._scroll_target_by_event(t, event), add="+")
            widget.bind("<Shift-MouseWheel>", lambda event, t=target: self._scroll_target_by_event(t, event), add="+")
            widget.bind("<Button-4>", lambda event, t=target: self._scroll_target_by_step(t, event, -1), add="+")
            widget.bind("<Button-5>", lambda event, t=target: self._scroll_target_by_step(t, event, 1), add="+")

    def _register_scroll_tree(self, target: tk.Widget, root: tk.Widget, skip: set[str] | None = None) -> None:
        skipped = skip or set()
        if str(root) in skipped:
            return
        self._register_scroll_target(target, root)
        for child in root.winfo_children():
            self._register_scroll_tree(target, child, skip=skipped)

    def _set_active_scroll_target(self, target: tk.Widget) -> None:
        self._active_scroll_target = target
        try:
            target.focus_set()
        except tk.TclError:
            pass

    def _scroll_target_by_event(self, target: tk.Widget, event: tk.Event) -> str:
        self._set_active_scroll_target(target)
        delta = int(event.delta)
        if delta == 0:
            return "break"
        if abs(delta) >= 120:
            step = int(-delta / 120)
        else:
            step = -1 if delta > 0 else 1
        target.yview_scroll(step, "units")
        return "break"

    def _scroll_target_by_step(self, target: tk.Widget, _event: tk.Event, step: int) -> str:
        self._set_active_scroll_target(target)
        target.yview_scroll(step, "units")
        return "break"

    def _dispatch_mousewheel(self, event: tk.Event) -> str | None:
        target = self._resolve_scroll_target(event)
        if target is None:
            return None
        delta = int(event.delta)
        if delta == 0:
            return "break"
        if abs(delta) >= 120:
            step = int(-delta / 120)
        else:
            step = -1 if delta > 0 else 1
        target.yview_scroll(step, "units")
        return "break"

    def _dispatch_linux_scroll(self, event: tk.Event, step: int) -> str | None:
        target = self._resolve_scroll_target(event)
        if target is None:
            return None
        target.yview_scroll(step, "units")
        return "break"

    def _resolve_scroll_target(self, event: tk.Event) -> tk.Widget | None:
        target = self._resolve_widget_scroll_target(getattr(event, "widget", None))
        if target is not None:
            return target
        widget = self.root.winfo_containing(*self.root.winfo_pointerxy())
        return self._resolve_widget_scroll_target(widget) or self._active_scroll_target

    def _resolve_widget_scroll_target(self, widget: tk.Widget | None) -> tk.Widget | None:
        while widget is not None:
            direct = self._scroll_targets.get(str(widget))
            if direct is not None:
                return direct
            parent_name = widget.winfo_parent()
            if not parent_name:
                return None
            try:
                widget = widget.nametowidget(parent_name)
            except KeyError:
                return None
        return None

    def _show_sort_menu(self) -> None:
        if self.sort_menu is None:
            menu = tk.Menu(
                self.root,
                tearoff=0,
                bg=SURFACE,
                fg=TEXT,
                activebackground=ACCENT,
                activeforeground=TEXT,
                bd=0,
            )
            for option in (
                "Risk first",
                "Largest position first",
                "Highest liquidity share first",
                "Newest first",
                "Strongest timing anomaly first",
            ):
                menu.add_command(label=option, command=lambda value=option: self.sort_var.set(value))
            self.sort_menu = menu
        self.sort_menu.tk_popup(self.sort_button.winfo_rootx(), self.sort_button.winfo_rooty() + self.sort_button.winfo_height())

    def _load_analyst_state(self) -> dict:
        if not self.analyst_state_path.exists():
            return {"cases": {}}
        try:
            payload = json.loads(self.analyst_state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"cases": {}}
        if not isinstance(payload, dict):
            return {"cases": {}}
        payload.setdefault("cases", {})
        return payload

    def _save_analyst_state(self) -> None:
        self.analyst_state_path.write_text(json.dumps(self.analyst_state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _case_state(self, case: dict) -> dict:
        cases = self.analyst_state.setdefault("cases", {})
        trade_id = case["trade"]["trade_id"]
        cases.setdefault(trade_id, {"pinned": False, "false_positive": False, "follow_up": False, "note": ""})
        return cases[trade_id]

    def _selected_categories(self) -> tuple[SiteCategory, ...]:
        selected = tuple(category for category in self.site_categories if self.category_vars[category.label].get())
        if not selected:
            raise ValueError("Select at least one Polymarket category.")
        return selected

    def _parse_amount(self, raw: str) -> Decimal | None:
        text = raw.strip()
        if not text:
            return None
        try:
            return Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid amount: {raw}") from exc

    def _toggle_scan(self) -> None:
        if self.worker and self.worker.is_alive():
            self._stop_scan()
            return
        self._start_scan()

    def _start_scan(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        try:
            selected_categories = self._selected_categories()
            min_amount = self._parse_amount(self.min_amount_var.get())
            max_amount = self._parse_amount(self.max_amount_var.get())
        except ValueError as exc:
            messagebox.showerror("InsPoly", str(exc))
            return
        if min_amount is not None and max_amount is not None and min_amount > max_amount:
            messagebox.showerror("InsPoly", "Min amount cannot be greater than max amount.")
            return

        self.progress_var.set(0)
        self.status_var.set("Starting scan")
        self.status_meta_var.set("Preparing scanner")
        self.progress_label_var.set("Scan starting…")
        self.scan_state_var.set("Scan state: starting")
        self.current_cases = []
        self.filtered_cases = []
        self.selected_case = None
        self.selected_case_id = None
        self.case_detail_cache.clear()
        self.start_button.configure(text="Stop scan")
        self.start_button.configure(bg="#5e2d36", activebackground="#7a3c47")
        self.stop_event = threading.Event()
        self._render_case_cards([])
        self._render_detail_panel()

        self.worker = threading.Thread(
            target=self._run_scan_worker,
            args=(self.lookback_var.get(), selected_categories, min_amount, max_amount),
            daemon=True,
        )
        self.worker.start()

    def _stop_scan(self) -> None:
        if not (self.worker and self.worker.is_alive()):
            return
        self.stop_event.set()
        self.status_var.set("Stopping scan")
        self.status_meta_var.set("Saving partial run")
        self.progress_label_var.set("Stopping scan…")
        self.scan_state_var.set("Scan state: stopping and saving partial results")
        self.start_button.configure(state="disabled", bg="#16263f")

    def _run_scan_worker(
        self,
        lookback: str,
        categories: tuple[SiteCategory, ...],
        min_amount: Decimal | None,
        max_amount: Decimal | None,
    ) -> None:
        try:
            report = self.scanner.scan(
                lookback,
                self.config.reports_dir,
                selected_categories=categories,
                min_notional=min_amount,
                max_notional=max_amount,
                progress_callback=self._on_progress,
                stop_event=self.stop_event,
            )
        except Exception as exc:
            self.event_queue.put(("error", str(exc)))
            return
        self.event_queue.put(("done", report))

    def _on_progress(self, event: ProgressEvent) -> None:
        self.event_queue.put(("progress", event))

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.event_queue.get_nowait()
                if kind == "progress":
                    event = payload
                    assert isinstance(event, ProgressEvent)
                    self.progress_var.set(event.percent)
                    self.status_var.set(event.stage)
                    self.status_meta_var.set(event.detail)
                    self.progress_label_var.set(f"{event.stage} {event.percent:.0f}%")
                    self.scan_state_var.set(f"Scan state: {event.stage.lower()}")
                elif kind == "done":
                    report = payload
                    self.progress_var.set(100)
                    state = "stopped with partial results" if report.get("status") == "stopped" else "finished"
                    self.status_var.set("Run complete")
                    flagged = report.get("flagged_case_count", len(report.get("cases", [])))
                    self.status_meta_var.set(f"Scan completed: {flagged} flagged cases")
                    self.progress_label_var.set(f"Completed {flagged} flagged cases")
                    self.scan_state_var.set(f"Scan state: {state}")
                    self._load_report(report)
                    self.start_button.configure(text="Start scan", state="normal", bg=ACCENT, activebackground=ACCENT_HOVER)
                    self.worker = None
                elif kind == "error":
                    self.status_var.set("Failed")
                    self.status_meta_var.set(str(payload))
                    self.progress_label_var.set("Scan failed")
                    self.scan_state_var.set("Scan state: failed")
                    messagebox.showerror("InsPoly", str(payload))
                    self.start_button.configure(text="Start scan", state="normal", bg=ACCENT, activebackground=ACCENT_HOVER)
                    self.worker = None
        except queue.Empty:
            pass
        self.root.after(200, self._poll_events)

    def _load_report(self, report: dict) -> None:
        report = self._normalize_report(report)
        self.current_report = report
        output_path = report.get("report_txt_path")
        self.current_output_path = Path(output_path) if output_path else None
        self.output_path_var.set(str(self.current_output_path) if self.current_output_path else "No output loaded")
        self.current_cases = report.get("cases", [])
        self.summary_title_var.set("Run summary")
        self._render_run_summary(report)
        self._apply_case_filters()
        self._refresh_recent_outputs()
        self._update_status_bar()

    def _report_paths_from_output(self, output_path: Path) -> tuple[Path, Path]:
        stem = output_path.stem
        json_path = self.config.reports_dir / f"{stem}.json"
        txt_path = self.config.outputs_dir / f"{stem}.txt"
        return json_path, txt_path

    def _load_output_file(self, output_path: Path) -> None:
        json_path, txt_path = self._report_paths_from_output(output_path)
        if not json_path.exists():
            messagebox.showerror("InsPoly", f"Missing matching JSON report for {output_path.name}")
            return
        report = self._normalize_report(json.loads(json_path.read_text(encoding="utf-8")))
        report["report_json_path"] = str(json_path)
        report["report_txt_path"] = str(txt_path if txt_path.exists() else output_path)
        self.status_var.set("Loaded run")
        self.status_meta_var.set(output_path.name)
        self.progress_label_var.set("Loaded previous run")
        self.scan_state_var.set("Scan state: reviewing loaded run")
        self._load_report(report)

    def _normalize_report(self, report: dict) -> dict:
        normalized = dict(report)
        cases = normalized.get("cases", [])
        normalized_cases: list[dict] = []
        for case in cases:
            if "raw_metrics" in case:
                normalized_cases.append(case)
                continue
            trade = dict(case.get("trade", {}))
            market = dict(case.get("market", {}))
            wallet = dict(case.get("wallet_inspection", {}))
            normalized_cases.append(
                {
                    "severity": self._normalize_legacy_severity(case.get("level", "Low Risk")),
                    "suspicion_score": case.get("score", 0),
                    "confidence_score": case.get("confidence_score", 100),
                    "review_priority": case.get("review_priority", "Medium"),
                    "verdict": case.get("verdict", "Needs manual review"),
                    "trade_count_window": case.get("trade_count_window", 0),
                    "window_start": case.get("window_start", trade.get("timestamp", "")),
                    "window_end": case.get("window_end", trade.get("timestamp", "")),
                    "trade": trade,
                    "market": market,
                    "wallet_inspection": wallet,
                    "subscores": case.get("subscores", {}),
                    "flags": case.get("flags", []),
                    "explanation": case.get("reasons", []),
                    "reasons_against": case.get("reasons_against", []),
                    "raw_metrics": case.get("metrics", {}),
                }
            )
        normalized["cases"] = normalized_cases
        if "flagged_case_count" not in normalized:
            normalized["flagged_case_count"] = len(normalized_cases)
        if "candidate_trade_count" not in normalized:
            normalized["candidate_trade_count"] = normalized.get("filtered_trade_count", len(normalized_cases))
        return normalized

    def _normalize_legacy_severity(self, value: str) -> str:
        mapping = {
            "HIGH": "Strong Risk",
            "MEDIUM": "Worth a look",
            "LOW": "Low Risk",
        }
        return mapping.get(str(value).upper(), str(value))

    def _apply_case_filters(self) -> None:
        cases = list(self.current_cases)
        risk_filter = self.risk_filter_var.get()
        if risk_filter != "All risks":
            cases = [case for case in cases if case["severity"] == risk_filter]
        selected_topics = {label for label, var in self.category_vars.items() if var.get()}
        if selected_topics:
            topic_filtered: list[dict] = []
            for case in cases:
                categories = set(case["market"].get("site_categories", []))
                if not categories or categories & selected_topics:
                    topic_filtered.append(case)
            cases = topic_filtered
        sort_choice = self.sort_var.get()
        if sort_choice == "Risk first":
            order = {"Strong Risk": 3, "Worth a look": 2, "Low Risk": 1}
            cases.sort(
                key=lambda case: (
                    order.get(case["severity"], 0),
                    case["suspicion_score"],
                    float(case["raw_metrics"].get("trade_notional_usdc", "0")),
                ),
                reverse=True,
            )
        elif sort_choice == "Largest position first":
            cases.sort(key=lambda case: float(case["raw_metrics"].get("trade_notional_usdc", "0")), reverse=True)
        elif sort_choice == "Highest liquidity share first":
            cases.sort(key=lambda case: self._parse_percent(case["raw_metrics"].get("liquidity_ratio", "0%")), reverse=True)
        elif sort_choice == "Strongest timing anomaly first":
            cases.sort(key=lambda case: float(case["raw_metrics"].get("hours_to_resolution", "99999")), reverse=False)
        else:
            cases.sort(key=lambda case: case["trade"]["timestamp"], reverse=True)

        self.filtered_cases = cases
        if self.selected_case_id and not any(case["trade"]["trade_id"] == self.selected_case_id for case in cases):
            self.selected_case = None
            self.selected_case_id = None
        if self.selected_case is None and cases:
            self.selected_case = cases[0]
            self.selected_case_id = cases[0]["trade"]["trade_id"]
        else:
            for case in cases:
                if case["trade"]["trade_id"] == self.selected_case_id:
                    self.selected_case = case
                    break
        self._render_case_cards(cases)
        self._render_detail_panel()
        self._update_applied_filters()
        self._update_status_bar()

    def _render_case_cards(self, cases: list[dict]) -> None:
        self.card_widgets = {}
        for child in self.cards_inner.winfo_children():
            child.destroy()
        if not cases:
            empty = tk.Label(
                self.cards_inner,
                text="No cases match the current filters.\nTry another risk level or load a different run.",
                bg=SURFACE,
                fg=TEXT_MUTED,
                justify="left",
                font=("SF Pro Text", 12),
            )
            empty.pack(anchor="w", fill="x", padx=8, pady=8)
            self._bind_dynamic_wrap(self.cards_inner, empty, pad=24, min_width=220)
            self._register_scroll_tree(self.cards_canvas, empty)
            self.cards_subtitle.configure(text="Filtered view is empty.")
            return

        total = self.current_report.get("flagged_case_count", len(self.current_cases)) if self.current_report else len(cases)
        self.cards_subtitle.configure(text=f"{len(cases)} visible cases from {total} flagged in the selected run.")
        for case in cases:
            self._add_case_card(case)
        self.cards_canvas.yview_moveto(0)

    def _add_case_card(self, case: dict) -> None:
        trade = case["trade"]
        state = self._case_state(case)
        selected = trade["trade_id"] == self.selected_case_id
        border = ACCENT if selected else BORDER
        background = SURFACE_ALT if selected else SURFACE
        card = tk.Frame(
            self.cards_inner,
            bg=background,
            highlightbackground=border,
            highlightcolor=border,
            highlightthickness=2 if selected else 1,
            bd=0,
            padx=14,
            pady=14,
        )
        card.pack(fill="x", pady=(0, 12))
        self._register_scroll_target(self.cards_canvas, card)
        self.card_widgets[trade["trade_id"]] = card

        top = tk.Frame(card, bg=background)
        top.pack(fill="x")
        title_wrap = tk.Frame(top, bg=background)
        title_wrap.pack(side="left", fill="x", expand=True)
        title_label = tk.Label(
            title_wrap,
            text=trade["title"],
            bg=background,
            fg=TEXT,
            justify="left",
            font=("SF Pro Display", 13, "bold"),
        )
        title_label.pack(anchor="w", fill="x")
        self._bind_dynamic_wrap(title_wrap, title_label, pad=12, min_width=220)
        subtitle = f"Wallet {self._short_wallet(trade['wallet'])}  •  {trade['side']} {trade['outcome']}  •  {self._format_timestamp(trade['timestamp'])}"
        subtitle_label = tk.Label(
            title_wrap,
            text=subtitle,
            bg=background,
            fg=TEXT_MUTED,
            justify="left",
            font=("SF Pro Text", 10),
        )
        subtitle_label.pack(anchor="w", fill="x", pady=(4, 0))
        self._bind_dynamic_wrap(title_wrap, subtitle_label, pad=12, min_width=220)
        self._badge(top, case["severity"], case["severity"]).pack(side="right", anchor="ne")

        metrics = tk.Frame(card, bg=background)
        metrics.pack(fill="x", pady=(12, 0))
        metric_values = [
            ("Score", str(case["suspicion_score"])),
            ("Position", f"${float(case['raw_metrics'].get('trade_notional_usdc', '0')):,.0f}"),
            ("Signal", self._card_signal(case)),
        ]
        for idx, (label, value) in enumerate(metric_values):
            tile = self._metric_tile(metrics, label, value)
            tile.configure(bg=SURFACE_SOFT)
            for child in tile.winfo_children():
                child.configure(bg=SURFACE_SOFT)
            tile.grid(row=0, column=idx, sticky="nsew", padx=(0 if idx == 0 else 8, 0))
            metrics.columnconfigure(idx, weight=1)

        quick_text = self._quick_analysis(case)
        quick_box = self._readonly_text(
            card,
            quick_text,
            min_height=4,
            bg=SURFACE_SOFT,
            fg=TEXT_MUTED,
            padx=10,
            pady=8,
        )
        quick_box.pack(fill="x", pady=(12, 0))
        self._register_scroll_target(self.cards_canvas, quick_box)

        tag_row = tk.Frame(card, bg=background)
        tag_row.pack(fill="x", pady=(10, 0))
        for label in self._case_tag_labels(case, state):
            tk.Label(
                tag_row,
                text=label,
                bg=ACCENT_SOFT if label in {"Pinned", "Follow-up"} else "#2c1d1d",
                fg=TEXT,
                padx=8,
                pady=4,
                font=("SF Pro Text", 9),
            ).pack(side="left", padx=(0, 6))

        actions = tk.Frame(card, bg=background)
        actions.pack(fill="x", pady=(12, 0))
        self._action_button(actions, "Detailed analysis", lambda c=case: self._select_case(c, detailed=True), compact=True).pack(
            side="right"
        )
        self._action_button(actions, "Copy summary", lambda c=case: self._copy_case_summary(c), compact=True).pack(
            side="right", padx=(0, 8)
        )

        self._bind_click_recursive(card, lambda c=case: self._select_case(c))
        self._register_scroll_tree(self.cards_canvas, card)

    def _render_run_summary(self, report: dict) -> None:
        counts = {"Strong Risk": 0, "Worth a look": 0, "Low Risk": 0}
        for case in report.get("cases", []):
            counts[case["severity"]] = counts.get(case["severity"], 0) + 1

        self.summary_metric_labels["flagged"].set(str(report.get("flagged_case_count", 0)))
        self.summary_metric_labels["strong"].set(str(counts.get("Strong Risk", 0)))
        self.summary_metric_labels["worth"].set(str(counts.get("Worth a look", 0)))
        self.summary_metric_labels["low"].set(str(counts.get("Low Risk", 0)))

        selected_run = self.current_output_path.name if self.current_output_path else "current session"
        self.selected_run_var.set(f"Selected run: {selected_run}")
        self.run_context_label.configure(
            text=(
                f"Lookback: {report.get('lookback', 'Unknown')}\n"
                f"Topics: {report.get('topic_scope', 'Unknown')}\n"
                f"Scanned trades: {report.get('raw_trade_count', 0)} total, "
                f"{report.get('candidate_trade_count', 0)} after filters.\n"
                f"Generated: {self._format_timestamp(report.get('generated_at', ''))}"
            )
        )

    def _select_case(self, case: dict, *, detailed: bool = False) -> None:
        self.selected_case = case
        self.selected_case_id = case["trade"]["trade_id"]
        if detailed:
            self.detail_mode_var.set("Technical detail")
        self.analysis_mode_var.set(f"Analysis: {'detailed' if self.detail_mode_var.get() == 'Technical detail' else 'quick'}")
        self._render_case_cards(self.filtered_cases)
        self._render_detail_panel()
        self._update_status_bar()

    def _render_detail_panel(self) -> None:
        for child in self.detail_header.winfo_children():
            child.destroy()
        for child in self.detail_inner.winfo_children():
            child.destroy()

        if self.selected_case is None:
            self._render_empty_detail()
            return

        case = self.selected_case
        trade = case["trade"]
        state = self._case_state(case)

        top = tk.Frame(self.detail_header, bg=SURFACE)
        top.pack(fill="x")
        top.columnconfigure(0, weight=1)
        title_wrap = tk.Frame(top, bg=SURFACE)
        title_wrap.grid(row=0, column=0, sticky="ew", padx=(0, 16))
        tk.Label(
            title_wrap,
            text="Selected case",
            bg=SURFACE,
            fg=TEXT_SUBTLE,
            font=("SF Pro Text", 10, "bold"),
        ).pack(anchor="w")
        title_label = tk.Label(
            title_wrap,
            text=trade["title"],
            bg=SURFACE,
            fg=TEXT,
            justify="left",
            font=("SF Pro Display", 20, "bold"),
        )
        title_label.pack(anchor="w", fill="x", pady=(4, 0))
        self._bind_dynamic_wrap(title_wrap, title_label, pad=20, min_width=260)
        meta = f"Wallet {trade['wallet']}  •  {self._display_username(trade)}"
        meta_label = tk.Label(title_wrap, text=meta, bg=SURFACE, fg=TEXT_MUTED, justify="left", font=("SF Pro Text", 11))
        meta_label.pack(anchor="w", fill="x", pady=(8, 0))
        self._bind_dynamic_wrap(title_wrap, meta_label, pad=20, min_width=260)

        right = tk.Frame(top, bg=SURFACE)
        right.grid(row=0, column=1, sticky="ne")
        self._badge(right, case["severity"], case["severity"]).pack(side="right")
        tk.Label(
            right,
            text=f"Score {case['suspicion_score']}/100",
            bg=SURFACE,
            fg=TEXT_MUTED,
            font=("SF Pro Text", 11),
        ).pack(side="right", padx=(0, 10))

        actions = tk.Frame(self.detail_header, bg=SURFACE)
        actions.pack(fill="x", pady=(14, 0))
        row_one = tk.Frame(actions, bg=SURFACE)
        row_one.pack(fill="x")
        row_two = tk.Frame(actions, bg=SURFACE)
        row_two.pack(fill="x", pady=(8, 0))
        self._action_button(row_one, "Copy summary", lambda c=case: self._copy_case_summary(c), compact=True).pack(side="left")
        self._action_button(row_one, "Open output", self._open_latest_output, compact=True).pack(side="left", padx=(8, 0))
        self._action_button(row_two, "Pin case", lambda c=case: self._toggle_case_flag(c, "pinned"), compact=True).pack(
            side="left"
        )
        self._action_button(
            row_two,
            "False positive",
            lambda c=case: self._toggle_case_flag(c, "false_positive"),
            compact=True,
        ).pack(side="left", padx=(8, 0))
        self._action_button(row_two, "Follow-up", lambda c=case: self._toggle_case_flag(c, "follow_up"), compact=True).pack(
            side="left", padx=(8, 0)
        )

        if state["pinned"] or state["false_positive"] or state["follow_up"]:
            tag_row = tk.Frame(self.detail_header, bg=SURFACE)
            tag_row.pack(fill="x", pady=(10, 0))
            for label in self._case_tag_labels(case, state):
                tk.Label(tag_row, text=label, bg=ACCENT_SOFT, fg=TEXT, padx=8, pady=4, font=("SF Pro Text", 9)).pack(
                    side="left", padx=(0, 6)
                )

        key_context = tk.Frame(self.detail_inner, bg=SURFACE)
        key_context.pack(fill="x")
        tk.Label(
            key_context,
            text="Key context",
            bg=SURFACE,
            fg=TEXT_SUBTLE,
            font=("SF Pro Text", 10, "bold"),
        ).pack(anchor="w", pady=(0, 10))

        context_grid = tk.Frame(key_context, bg=SURFACE)
        context_grid.pack(fill="x")
        context_items = self._key_context_items(case)
        for idx, (label, value) in enumerate(context_items):
            tile = self._metric_tile(context_grid, label, value)
            tile.grid(row=idx // 2, column=idx % 2, sticky="nsew", padx=4, pady=4)
            context_grid.columnconfigure(idx % 2, weight=1)

        row = tk.Frame(self.detail_inner, bg=SURFACE)
        row.pack(fill="x", pady=(16, 0))
        stands_out = self._section_panel(row, "What stands out")
        stands_out.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self._bullet_list(stands_out, case["explanation"])

        reduces = self._section_panel(row, "What reduces concern")
        reduces.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self._bullet_list(
            reduces,
            case["reasons_against"] or ["No strong benign pattern clearly reduces concern in the loaded sample."],
        )

        interpretation = self._section_panel(self.detail_inner, "How the system interpreted this case")
        interpretation.pack(fill="x", pady=(16, 0))
        interpretation_text = self._readonly_text(
            interpretation,
            self._interpretation_paragraph(case),
            min_height=4,
            bg=SURFACE_ALT,
            fg=TEXT_MUTED,
        )
        interpretation_text.pack(fill="x", pady=(10, 0))
        self._register_scroll_target(self.detail_canvas, interpretation_text)

        bottom_line = self._section_panel(self.detail_inner, "Overall assessment")
        bottom_line.pack(fill="x", pady=(16, 0))
        bottom_text = self._readonly_text(
            bottom_line,
            self._bottom_line(case),
            min_height=3,
            bg=SURFACE_ALT,
            fg=TEXT,
        )
        bottom_text.pack(fill="x", pady=(10, 0))
        self._register_scroll_target(self.detail_canvas, bottom_text)

        wallet_data = self._get_case_detail_data(case)
        snapshot = self._section_panel(self.detail_inner, "Lifetime stats")
        snapshot.pack(fill="x", pady=(16, 0))
        snapshot_grid = tk.Frame(snapshot, bg=SURFACE_ALT)
        snapshot_grid.pack(fill="x", pady=(10, 0))
        for idx, (label, value) in enumerate(self._wallet_snapshot_items(case, wallet_data)):
            tile = self._metric_tile(snapshot_grid, label, value)
            tile.grid(row=idx // 2, column=idx % 2, sticky="nsew", padx=4, pady=4)
            snapshot_grid.columnconfigure(idx % 2, weight=1)

        positions = self._section_panel(self.detail_inner, "Recent closed positions")
        positions.pack(fill="x", pady=(16, 0))
        self._positions_table(positions, wallet_data["closed_positions"])

        if self.detail_mode_var.get() == "Technical detail":
            debug = self._section_panel(self.detail_inner, "Technical detail")
            debug.pack(fill="x", pady=(16, 0))
            technical_lines = self._debug_summary_lines(case) + self._technical_metric_lines(case, wallet_data)
            self._bullet_list(debug, technical_lines)

        notes = self._section_panel(self.detail_inner, "Analyst notes")
        notes.pack(fill="x", pady=(16, 0))
        self.notes_text = tk.Text(
            notes,
            height=5,
            wrap="word",
            bg=SURFACE_SOFT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            highlightthickness=1,
            font=("SF Pro Text", 11),
        )
        self.notes_text.pack(fill="x", pady=(10, 0))
        self.notes_text.insert("1.0", state.get("note", ""))
        self._enable_context_menu(self.notes_text)
        footer = tk.Frame(notes, bg=SURFACE_ALT)
        footer.pack(fill="x", pady=(10, 0))
        self._action_button(footer, "Save note", self._save_selected_case_note, compact=True).pack(side="left")
        tk.Label(
            footer,
            text="Notes persist locally across sessions.",
            bg=SURFACE_ALT,
            fg=TEXT_SUBTLE,
            font=("SF Pro Text", 10),
        ).pack(side="left", padx=(10, 0))

        self.detail_canvas.yview_moveto(0)
        self._register_scroll_tree(self.detail_canvas, self.detail_header)
        self._register_scroll_tree(self.detail_canvas, self.detail_inner)

    def _render_empty_detail(self) -> None:
        tk.Label(
            self.detail_header,
            text="Selected case",
            bg=SURFACE,
            fg=TEXT_SUBTLE,
            font=("SF Pro Text", 10, "bold"),
        ).pack(anchor="w")
        empty_title = tk.Label(
            self.detail_header,
            text="Choose a flagged card to inspect it in detail.",
            bg=SURFACE,
            fg=TEXT,
            justify="left",
            font=("SF Pro Display", 18, "bold"),
        )
        empty_title.pack(anchor="w", fill="x", pady=(4, 0))
        self._bind_dynamic_wrap(self.detail_header, empty_title, pad=24, min_width=260)

        placeholder = self._section_panel(self.detail_inner, "Workflow")
        placeholder.pack(fill="x")
        self._bullet_list(
            placeholder,
            [
                "Run a scan or load a previous run from the left rail.",
                "Review flagged cards in the center column.",
                "Open a selected case for human summary or technical detail.",
                "Use pin, false-positive, follow-up, and notes to manage analyst flow.",
            ],
        )
        self._register_scroll_tree(self.detail_canvas, self.detail_header)
        self._register_scroll_tree(self.detail_canvas, self.detail_inner)

    def _quick_analysis(self, case: dict) -> str:
        lines = case["explanation"][:2] or ["No explanation available."]
        return "Quick analysis: " + " ".join(lines)

    def _card_signal(self, case: dict) -> str:
        if case["subscores"].get("cluster", 0) > 0:
            return "Crowd activity"
        if case["subscores"].get("timing", 0) > 0:
            return "Timing pressure"
        if case["subscores"].get("size", 0) > 0:
            return "Size"
        return "Context"

    def _case_tag_labels(self, case: dict, state: dict) -> list[str]:
        labels: list[str] = []
        if state.get("pinned"):
            labels.append("Pinned")
        if state.get("follow_up"):
            labels.append("Follow-up")
        if state.get("false_positive"):
            labels.append("False positive")
        if case["confidence_score"] < 95:
            labels.append(f"Coverage {case['confidence_score']}/100")
        return labels

    def _key_context_items(self, case: dict) -> list[tuple[str, str]]:
        raw = case["raw_metrics"]
        return [
            ("Market", case["trade"]["title"]),
            ("Wallet", case["trade"]["wallet"]),
            ("Username", self._display_username(case["trade"])),
            ("Overall assessment", case["severity"]),
            ("Position size", f"${float(raw.get('trade_notional_usdc', '0')):,.2f}"),
            ("Liquidity consumed", raw.get("liquidity_ratio", "Unavailable")),
            ("Relative to market", f"Percentile {raw.get('market_size_percentile', 'n/a')}"),
            (
                "Relative to wallet norm",
                raw.get("wallet_size_multiple_vs_median", "Unavailable"),
            ),
            ("Same-side participation", f"{raw.get('cluster_wallets_30m_same_side', '0')} other wallets"),
            ("Same-side dollar volume", raw.get("same_side_dollar_volume_30m", "Unavailable")),
            ("Same-side share of activity", raw.get("same_side_share_30m", "Unavailable")),
            ("Time until resolution", self._hours_label(raw.get("hours_to_resolution", "Unavailable"))),
        ]

    def _wallet_snapshot_items(self, case: dict, wallet_data: dict) -> list[tuple[str, str]]:
        wallet = case["wallet_inspection"]
        return [
            ("Visible loaded trade sample", str(wallet_data["trade_sample_size"])),
            ("Median loaded trade size", f"${wallet_data['wallet_median']:.2f}"),
            ("Unique markets", str(wallet.get("unique_market_count", "Unavailable"))),
            ("Focus-category count", str(wallet.get("focus_market_count", "Unavailable"))),
            ("First visible trade", self._format_timestamp(wallet.get("first_trade_at", ""))),
            ("Last visible trade", self._format_timestamp(wallet.get("last_trade_at", ""))),
            ("Closed positions", str(wallet_data["closed_summary"]["total_closed"])),
            ("Win rate", wallet_data["closed_summary"]["win_rate_label"]),
            ("Total realized P/L", self._format_money(wallet_data["closed_summary"]["total_realized_pnl"])),
            ("Average realized return", self._format_percent(wallet_data["closed_summary"]["average_realized_return"])),
            ("Open positions", str(wallet_data["open_summary"]["count"])),
            ("Open notional", self._format_money(wallet_data["open_summary"]["open_notional"])),
            ("Aggregate unrealized P/L", self._format_money(wallet_data["open_summary"]["aggregate_unrealized_pnl"])),
            ("Aggregate unrealized return", self._format_percent(wallet_data["open_summary"]["aggregate_unrealized_return"])),
        ]

    def _bullet_list(self, parent: tk.Widget, items: list[str]) -> None:
        body = tk.Frame(parent, bg=parent.cget("bg"))
        body.pack(fill="x", pady=(10, 0))
        for item in items:
            row = tk.Frame(body, bg=parent.cget("bg"))
            row.pack(fill="x", pady=2)
            tk.Label(row, text="•", bg=parent.cget("bg"), fg=TEXT_MUTED, font=("SF Pro Text", 11)).pack(side="left", anchor="n")
            block = self._readonly_text(
                row,
                item,
                min_height=2,
                bg=parent.cget("bg"),
                fg=TEXT_MUTED,
                border=False,
            )
            block.pack(side="left", fill="x", expand=True)
            self._register_scroll_target(self.detail_canvas, block)

    def _positions_table(self, parent: tk.Widget, rows: list[dict]) -> None:
        if not rows:
            tk.Label(
                parent,
                text="No likely closed positions were identified from the loaded sample.",
                bg=SURFACE_ALT,
                fg=TEXT_MUTED,
                font=("SF Pro Text", 11),
            ).pack(anchor="w", pady=(10, 0))
            return
        table = tk.Frame(parent, bg=SURFACE_ALT)
        table.pack(fill="x", pady=(10, 0))
        header = tk.Label(
            table,
            text="Date | Market | Direction | Result | Realized P/L | Return",
            bg=SURFACE_ALT,
            fg=TEXT_SUBTLE,
            anchor="w",
            font=("SF Pro Text", 10, "bold"),
        )
        header.pack(fill="x", pady=(0, 4))
        for item in rows[:10]:
            row = tk.Frame(table, bg=SURFACE_SOFT, highlightbackground=BORDER, highlightcolor=BORDER, highlightthickness=1, bd=0)
            row.pack(fill="x", pady=4)
            row_text = (
                f"{item['date']} | {item['market']} | {item['direction']} | {item['result']} | "
                f"{self._format_money(item['realized_pnl'])} | {self._format_percent(item['realized_return'])}"
            )
            block = self._readonly_text(
                row,
                row_text,
                min_height=2,
                bg=SURFACE_SOFT,
                fg=TEXT_MUTED,
                padx=8,
                pady=8,
            )
            block.pack(fill="x")
            self._register_scroll_target(self.detail_canvas, block)

    def _get_case_detail_data(self, case: dict) -> dict:
        trade_id = case["trade"]["trade_id"]
        cached = self.case_detail_cache.get(trade_id)
        if cached is not None:
            return cached
        trade = case["trade"]
        try:
            wallet_stats = self.client.fetch_wallet_stats(trade["wallet"], trade_limit=500)
            wallet_positions = self.client.fetch_wallet_positions(trade["wallet"])
            notionals = [float(item.notional) for item in wallet_stats.trades]
            wallet_median = median(notionals) if notionals else 0.0
            analytics = self._position_analytics(wallet_stats.trades, wallet_positions)
            result = {
                "wallet_stats": wallet_stats,
                "wallet_positions": wallet_positions,
                "wallet_median": wallet_median,
                "trade_sample_size": len(wallet_stats.trades),
                "closed_positions": analytics["closed_positions"],
                "closed_summary": analytics["closed_summary"],
                "open_summary": analytics["open_summary"],
            }
        except Exception as exc:
            result = {
                "wallet_stats": None,
                "wallet_positions": [],
                "wallet_median": 0.0,
                "trade_sample_size": 0,
                "closed_positions": [],
                "closed_summary": self._empty_closed_summary(),
                "open_summary": self._empty_open_summary(),
                "error": str(exc),
            }
        self.case_detail_cache[trade_id] = result
        return result

    def _bottom_line(self, case: dict) -> str:
        if case["severity"] == "Strong Risk":
            return "Several strong factors align here, so this case deserves close manual review."
        if case["severity"] == "Worth a look":
            return "This case is not enough to imply wrongdoing, but it has enough unusual features to justify a closer look."
        return "This case has some unusual elements, but current evidence is weak and may reflect ordinary trading."

    def _display_username(self, trade: dict) -> str:
        trader_name = (trade.get("trader_name") or "").strip()
        pseudonym = (trade.get("trader_pseudonym") or "").strip()
        if trader_name and pseudonym and trader_name != pseudonym:
            return f"{trader_name} ({pseudonym})"
        if trader_name:
            return trader_name
        if pseudonym:
            return pseudonym
        return "Not available"

    def _interpretation_paragraph(self, case: dict) -> str:
        parts = []
        if case["subscores"].get("timing", 0) == 0:
            parts.append("Timing did not materially raise concern.")
        else:
            parts.append("Timing contributed because the trade landed relatively close to market resolution.")
        if case["subscores"].get("size", 0) > 0:
            parts.append("Size mattered because the trade stood out either in market context, wallet context, or both.")
        if case["subscores"].get("cluster", 0) > 0:
            parts.append(
                "Several wallets entered the same side in a short time window. This may reflect coordination or a fast reaction to public news, but no stronger linkage was confirmed."
            )
        if case["subscores"].get("wallet_novelty", 0) == 0:
            parts.append("The wallet does not look obviously new in the loaded history.")
        return " ".join(parts)

    def _debug_summary_lines(self, case: dict) -> list[str]:
        lines: list[str] = []
        flags = set(case.get("flags", []))
        if "large_trade_absolute" in flags:
            lines.append("A large absolute trade-size signal was triggered.")
        if "large_trade_relative_to_market" in flags:
            lines.append("A large relative-to-market signal was triggered.")
        if "wallet_size_anomaly" in flags:
            lines.append("The trade was unusually large relative to this wallet's normal size.")
        if "wallet_recently_activated" in flags:
            lines.append("The wallet-history review found low-history characteristics.")
        if "synchronized_entry_cluster" in flags:
            lines.append("A same-side cluster signal was triggered because multiple wallets entered nearby in time.")
        if case["subscores"].get("benign_discount", 0) < 0:
            lines.append("A benign-pattern discount reduced the final concern level.")
        if not lines:
            lines.append("No additional debug signals were exposed for this case.")
        return lines

    def _technical_metric_lines(self, case: dict, wallet_data: dict) -> list[str]:
        raw = case["raw_metrics"]
        lines = [
            f"Review priority: {case.get('review_priority', 'Unknown')}",
            f"Confidence score: {case.get('confidence_score', 'Unknown')}/100",
            f"Verdict: {case.get('verdict', 'Unknown')}",
            f"Window: {self._format_timestamp(case.get('window_start', ''))} to {self._format_timestamp(case.get('window_end', ''))}",
            f"Related markets in 30m: {raw.get('related_markets_30m', '0')}",
            f"Market liquidity: ${float(raw.get('market_liquidity_usdc', '0')):,.2f}",
            f"Market volume: ${float(raw.get('market_volume_usdc', '0')):,.2f}",
        ]
        if wallet_data.get("error"):
            lines.append(f"Wallet enrichment failed: {wallet_data['error']}")
        return lines

    def _position_status_label(
        self,
        trade: object,
        market_status: MarketStatus | None,
        position: WalletPosition | None,
    ) -> str:
        if position is not None and not position.redeemable:
            return "Open position"
        if position is not None and position.redeemable:
            return "Resolved market, winning remainder still in wallet"
        if market_status is None:
            return "Status unavailable"
        if market_status.closed:
            return "Resolved market, final win/loss not recoverable from current feed"
        if market_status.accepting_orders:
            return "Open market"
        return "Market not accepting orders"

    def _position_analytics(self, trades: list[object], wallet_positions: list[WalletPosition]) -> dict:
        open_map = {position.asset_id: position for position in wallet_positions if position.size > 0}
        grouped: dict[str, list[object]] = defaultdict(list)
        for trade in trades:
            grouped[trade.asset_id].append(trade)

        closed_positions: list[dict] = []
        open_notional = 0.0
        aggregate_unrealized_pnl = 0.0
        aggregate_cost_basis = 0.0

        for asset_id, asset_trades in grouped.items():
            ordered = sorted(asset_trades, key=lambda item: item.timestamp)
            buy_notional = sum(float(item.notional) for item in ordered if item.side == "BUY")
            sell_notional = sum(float(item.notional) for item in ordered if item.side == "SELL")
            quantity = 0.0
            cost_basis = 0.0
            for item in ordered:
                size = float(item.size)
                price = float(item.price)
                if item.side == "BUY":
                    quantity += size
                    cost_basis += size * price
                elif quantity > 0:
                    average_cost = cost_basis / quantity
                    close_size = min(quantity, size)
                    quantity -= close_size
                    cost_basis -= average_cost * close_size

            latest = ordered[-1]
            if asset_id not in open_map:
                realized_pnl = sell_notional - buy_notional
                realized_return = (realized_pnl / buy_notional * 100.0) if buy_notional > 0 else 0.0
                closed_positions.append(
                    {
                        "date": self._format_timestamp(latest.timestamp.isoformat()),
                        "market": latest.title,
                        "direction": latest.outcome,
                        "result": "Won" if realized_pnl > 0 else "Lost" if realized_pnl < 0 else "Closed early",
                        "realized_pnl": realized_pnl,
                        "realized_return": realized_return,
                        "timestamp": latest.timestamp,
                    }
                )
                continue

            current_value = float(open_map[asset_id].current_value)
            open_notional += current_value
            aggregate_cost_basis += max(cost_basis, 0.0)
            aggregate_unrealized_pnl += current_value - max(cost_basis, 0.0)

        closed_positions.sort(key=lambda item: item["timestamp"], reverse=True)
        wins = sum(1 for item in closed_positions if item["realized_pnl"] > 0)
        losses = sum(1 for item in closed_positions if item["realized_pnl"] < 0)
        total_realized = sum(item["realized_pnl"] for item in closed_positions)
        average_return = (
            sum(item["realized_return"] for item in closed_positions) / len(closed_positions) if closed_positions else 0.0
        )
        win_rate = (wins / len(closed_positions) * 100.0) if closed_positions else 0.0
        open_return = (aggregate_unrealized_pnl / aggregate_cost_basis * 100.0) if aggregate_cost_basis > 0 else 0.0

        return {
            "closed_positions": closed_positions,
            "closed_summary": {
                "total_closed": len(closed_positions),
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
                "win_rate_label": f"{win_rate:.1f}%",
                "total_realized_pnl": total_realized,
                "average_realized_return": average_return,
            },
            "open_summary": {
                "count": len(open_map),
                "open_notional": open_notional,
                "aggregate_unrealized_pnl": aggregate_unrealized_pnl,
                "aggregate_unrealized_return": open_return,
            },
        }

    def _empty_closed_summary(self) -> dict:
        return {
            "total_closed": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "win_rate_label": "0.0%",
            "total_realized_pnl": 0.0,
            "average_realized_return": 0.0,
        }

    def _empty_open_summary(self) -> dict:
        return {
            "count": 0,
            "open_notional": 0.0,
            "aggregate_unrealized_pnl": 0.0,
            "aggregate_unrealized_return": 0.0,
        }

    def _card_text(self, case: dict) -> str:
        trade = case["trade"]
        lines = [
            f"{case['severity']} | {case['suspicion_score']}/100 | @{float(trade['price']):.3f} | {trade['title']}",
            f"{trade['timestamp']} | {trade['side']} {trade['outcome']} | ${case['raw_metrics']['trade_notional_usdc']}",
        ]
        lines.extend(f"- {item}" for item in case["explanation"][:3])
        return "\n".join(lines)

    def _detail_text_payload(self, case: dict) -> str:
        wallet_data = self._get_case_detail_data(case)
        lines = [
            "Detailed case analysis",
            "",
            f"Market: {case['trade']['title']}",
            f"Wallet: {case['trade']['wallet']}",
            f"Username: {self._display_username(case['trade'])}",
            f"Overall assessment: {case['severity']}",
            "",
            "Key context:",
        ]
        lines.extend(f"- {label}: {value}" for label, value in self._key_context_items(case))
        lines.extend(["", "What stands out:"])
        lines.extend(f"- {item}" for item in case["explanation"])
        lines.extend(["", "What reduces concern:"])
        lines.extend(f"- {item}" for item in (case["reasons_against"] or ["No strong benign pattern clearly reduces concern."]))
        lines.extend(
            [
                "",
                "How the system interpreted this case:",
                self._interpretation_paragraph(case),
                "",
                "Bottom line:",
                self._bottom_line(case),
                "",
                "Lifetime stats:",
            ]
        )
        lines.extend(f"- {label}: {value}" for label, value in self._wallet_snapshot_items(case, wallet_data))
        lines.extend(["", "Recent closed positions:"])
        if wallet_data["closed_positions"]:
            lines.extend(
                "- "
                + " | ".join(
                    [
                        item["date"],
                        item["market"],
                        item["direction"],
                        item["result"],
                        self._format_money(item["realized_pnl"]),
                        self._format_percent(item["realized_return"]),
                    ]
                )
                for item in wallet_data["closed_positions"]
            )
        else:
            lines.append("- No likely closed positions were identified from the loaded sample.")
        if self.detail_mode_var.get() == "Technical detail":
            lines.extend(["", "Technical detail:"])
            lines.extend(f"- {item}" for item in self._debug_summary_lines(case))
            lines.extend(f"- {item}" for item in self._technical_metric_lines(case, wallet_data))
        return "\n".join(lines)

    def _copy_text(self, value: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.root.update()

    def _copy_cards_text(self) -> None:
        cases = self.filtered_cases or self.current_cases
        if not cases:
            self._copy_text("No loaded cards.")
            return
        payload = "\n\n".join(self._card_text(case) for case in cases)
        self._copy_text(payload)

    def _copy_case_summary(self, case: dict) -> None:
        self._copy_text(self._detail_text_payload(case))

    def _copy_detail_text(self) -> None:
        if self.selected_case is None:
            self._copy_text("No analysis loaded.")
            return
        self._copy_text(self._detail_text_payload(self.selected_case))

    def _copy_outputs_list(self) -> None:
        if not self.output_run_records:
            self._copy_text("No outputs found.")
            return
        lines = []
        for run in self.output_run_records:
            lines.append(
                f"{run['display_time']} | {run['lookback']} | {run['topics']} | "
                f"min ${run['min_amount'] or 'n/a'} | {run['flagged']} flagged"
            )
        self._copy_text("\n".join(lines))

    def _refresh_recent_outputs(self) -> None:
        for child in self.runs_inner.winfo_children():
            child.destroy()
        self.output_run_records = []
        output_files = sorted(self.config.outputs_dir.glob("*.txt"), key=lambda path: path.stat().st_mtime, reverse=True)
        for output_path in output_files[:20]:
            json_path, _txt_path = self._report_paths_from_output(output_path)
            if not json_path.exists():
                continue
            try:
                report = self._normalize_report(json.loads(json_path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
            record = {
                "output_path": output_path,
                "display_time": self._format_timestamp(report.get("generated_at", "")),
                "lookback": report.get("lookback", "Unknown"),
                "topics": report.get("topic_scope", "Unknown"),
                "flagged": report.get("flagged_case_count", 0),
                "min_amount": self._infer_min_amount(report),
            }
            self.output_run_records.append(record)
            self._render_run_card(record)

    def _render_run_card(self, record: dict) -> None:
        selected = self.current_output_path == record["output_path"]
        frame = tk.Frame(
            self.runs_inner,
            bg=SURFACE_ALT if selected else SURFACE_SOFT,
            highlightbackground=ACCENT if selected else BORDER,
            highlightcolor=ACCENT if selected else BORDER,
            highlightthickness=2 if selected else 1,
            bd=0,
            padx=12,
            pady=12,
            cursor="hand2",
        )
        frame.pack(fill="x", pady=(0, 10))
        self._register_scroll_target(self.runs_canvas, frame)
        tk.Label(
            frame,
            text=record["display_time"],
            bg=frame.cget("bg"),
            fg=TEXT,
            font=("SF Pro Display", 12, "bold"),
            anchor="w",
        ).pack(anchor="w")
        details_label = tk.Label(
            frame,
            text=(
                f"Lookback: {record['lookback']}\n"
                f"Topics: {record['topics']}\n"
                f"Flagged cases: {record['flagged']}"
            ),
            bg=frame.cget("bg"),
            fg=TEXT_MUTED,
            justify="left",
            wraplength=250,
            font=("SF Pro Text", 10),
        )
        details_label.pack(anchor="w", fill="x", pady=(6, 0))
        self._bind_dynamic_wrap(frame, details_label, pad=24, min_width=220)
        self._bind_click_recursive(frame, lambda p=record["output_path"]: self._load_output_file(p))
        self._register_scroll_tree(self.runs_canvas, frame)

    def _infer_min_amount(self, report: dict) -> str | None:
        cases = report.get("cases") or []
        if not cases:
            return None
        try:
            return f"{min(float(case['raw_metrics'].get('trade_notional_usdc', '0')) for case in cases):,.0f}"
        except (TypeError, ValueError):
            return None

    def _open_latest_output(self) -> None:
        path = self.output_path_var.get()
        if path and path != "No output loaded":
            subprocess.run(["open", path], check=False)

    def _toggle_case_flag(self, case: dict, field: str) -> None:
        state = self._case_state(case)
        state[field] = not state.get(field, False)
        self._save_analyst_state()
        self._render_case_cards(self.filtered_cases)
        self._render_detail_panel()

    def _save_selected_case_note(self) -> None:
        if self.selected_case is None or self.notes_text is None:
            return
        state = self._case_state(self.selected_case)
        state["note"] = self.notes_text.get("1.0", tk.END).strip()
        self._save_analyst_state()
        self.status_var.set("Note saved")
        self.status_meta_var.set(self._short_wallet(self.selected_case["trade"]["wallet"]))

    def _update_applied_filters(self) -> None:
        topics = [label for label, var in self.category_vars.items() if var.get()]
        topic_preview = ", ".join(topics[:3]) + ("…" if len(topics) > 3 else "")
        amount_bits = [f"min ${self.min_amount_var.get() or '0'}"]
        if self.max_amount_var.get().strip():
            amount_bits.append(f"max ${self.max_amount_var.get().strip()}")
        self.applied_filters_var.set(
            f"Filters: {self.risk_filter_var.get()} • {self.lookback_var.get()} • {', '.join(amount_bits)} • {topic_preview or 'no topics'}"
        )

    def _update_status_bar(self) -> None:
        visible = len(self.filtered_cases)
        total = len(self.current_cases)
        self.flagged_count_var.set(f"Flagged: {visible}/{total} visible")
        if self.selected_case is None:
            self.selection_state_var.set("Selected case: none")
        else:
            self.selection_state_var.set(
                f"Selected case: {self._short_wallet(self.selected_case['trade']['wallet'])} • {self.selected_case['severity']}"
            )
        self.analysis_mode_var.set(
            f"Analysis: {'detailed' if self.detail_mode_var.get() == 'Technical detail' else 'quick'}"
        )
        self.scan_state_var.set(f"Scan state: {self.status_var.get()} • {self.status_meta_var.get()}")

    def _format_timestamp(self, value: str) -> str:
        if not value:
            return "Unknown"
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
        return dt.astimezone().strftime("%b %d, %H:%M")

    def _hours_label(self, value: str) -> str:
        if value == "Unavailable":
            return "Unavailable"
        try:
            hours = float(value)
        except ValueError:
            return value
        if hours >= 24:
            return f"{hours / 24:.1f} days"
        return f"{hours:.1f} hours"

    def _parse_percent(self, value: str) -> float:
        try:
            return float(value.replace("%", "").strip())
        except ValueError:
            return 0.0

    def _format_money(self, value: float) -> str:
        sign = "+" if value > 0 else ""
        return f"{sign}${value:,.2f}"

    def _format_percent(self, value: float) -> str:
        sign = "+" if value > 0 else ""
        return f"{sign}{value:.1f}%"

    def _short_wallet(self, value: str) -> str:
        if len(value) < 12:
            return value
        return f"{value[:6]}...{value[-4:]}"

    def _readonly_text(
        self,
        parent: tk.Widget,
        value: str,
        *,
        min_height: int = 3,
        bg: str,
        fg: str,
        padx: int = 0,
        pady: int = 0,
        border: bool = True,
    ) -> tk.Text:
        line_count = max(min_height, min(8, value.count("\n") + 1))
        widget = tk.Text(
            parent,
            width=1,
            height=line_count,
            wrap="word",
            bg=bg,
            fg=fg,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            highlightbackground=BORDER if border else bg,
            highlightcolor=ACCENT if border else bg,
            highlightthickness=1 if border else 0,
            padx=padx,
            pady=pady,
            font=("SF Pro Text", 10),
            undo=False,
        )
        widget.insert("1.0", value)
        widget.configure(state="disabled", cursor="xterm")
        self._enable_context_menu(widget)
        return widget

    def _bind_click_recursive(self, widget: tk.Widget, callback: object) -> None:
        widget.bind("<Button-1>", lambda _event: callback(), add="+")
        for child in widget.winfo_children():
            self._bind_click_recursive(child, callback)

    def run(self) -> None:
        self.root.mainloop()


def launch_desktop_app() -> None:
    DesktopApp().run()
