"""
ui_overlay.py
Floating always-on-top overlay widget for NotepadAI.
Dark terminal aesthetic – shows AI suggestions, improvements, and
English→Code conversions in a tabbed panel.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import os
from typing import List, Dict, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Colour tokens
# ─────────────────────────────────────────────────────────────────────────────
BG          = "#0d1117"
BG2         = "#161b22"
BG3         = "#21262d"
BORDER      = "#30363d"
TEXT        = "#e6edf3"
TEXT_DIM    = "#8b949e"
ACCENT_BLUE = "#58a6ff"
ACCENT_GRN  = "#3fb950"
ACCENT_YLW  = "#d29922"
ACCENT_RED  = "#f85149"
ACCENT_PRP  = "#bc8cff"
CODE_BG     = "#161b22"
FONT_MONO   = ("Consolas", 9)
FONT_MONO_B = ("Consolas", 9, "bold")
FONT_UI     = ("Segoe UI", 9)
FONT_UI_B   = ("Segoe UI", 9, "bold")
FONT_TITLE  = ("Consolas", 10, "bold")


# ─────────────────────────────────────────────────────────────────────────────
# Scrollable text widget helper
# ─────────────────────────────────────────────────────────────────────────────
class _ScrollText(tk.Frame):
    def __init__(self, parent, height=6, font=FONT_MONO, bg=CODE_BG, fg=TEXT, **kw):
        super().__init__(parent, bg=bg, **kw)
        self._text = tk.Text(
            self,
            height=height,
            font=font,
            bg=bg,
            fg=fg,
            relief="flat",
            bd=0,
            wrap="word",
            state="disabled",
            selectbackground=BG3,
            insertbackground=TEXT,
            padx=8,
            pady=6,
            cursor="arrow",
        )
        sb = tk.Scrollbar(self, orient="vertical", command=self._text.yview,
                          bg=BG2, troughcolor=BG, width=8, relief="flat", bd=0)
        self._text.configure(yscrollcommand=sb.set)
        self._text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def set_text(self, value: str, tag_configs: Optional[dict] = None):
        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        self._text.insert("end", value)
        if tag_configs:
            for tag, config in tag_configs.items():
                self._text.tag_configure(tag, **config)
        self._text.config(state="disabled")

    def get_text(self) -> str:
        return self._text.get("1.0", "end-1c")


# ─────────────────────────────────────────────────────────────────────────────
# Pill-style label
# ─────────────────────────────────────────────────────────────────────────────
def _pill(parent, text, color):
    return tk.Label(parent, text=text, font=("Consolas", 8),
                    bg=color, fg=BG, padx=6, pady=2, relief="flat")


# ─────────────────────────────────────────────────────────────────────────────
# Main Overlay Window
# ─────────────────────────────────────────────────────────────────────────────
class OverlayUI:
    WIDTH  = 400
    HEIGHT = 560

    def __init__(self, filepath: str, ai_engine, file_watcher):
        self.filepath     = filepath
        self.ai_engine    = ai_engine
        self.file_watcher = file_watcher

        self._current_code      = ""
        self._english_items: List[Dict] = []
        self._dragging          = False
        self._drag_start_x      = 0
        self._drag_start_y      = 0
        self._analyzing         = False
        self._last_save_str     = "–"

        self._build_root()
        self._build_header()
        self._build_notebook()
        self._build_statusbar()

    # ──────────────────────────────────────────────────────────────────
    # Window setup
    # ──────────────────────────────────────────────────────────────────
    def _build_root(self):
        self.root = tk.Tk()
        self.root.title("NotepadAI")
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x  = sw - self.WIDTH - 20
        y  = sh - self.HEIGHT - 60
        self.root.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
        self.root.configure(bg=BG)
        self.root.resizable(True, True)
        self.root.minsize(300, 400)

        # ttk styles
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure("TNotebook",          background=BG,  borderwidth=0, tabmargins=0)
        s.configure("TNotebook.Tab",      background=BG2, foreground=TEXT_DIM,
                    padding=[14, 6],      font=FONT_MONO)
        s.map("TNotebook.Tab",
              background=[("selected", BG)],
              foreground=[("selected", ACCENT_BLUE)])
        s.configure("TFrame", background=BG)

        # Enable dragging by header
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        self.ai_engine.cancel()
        self.root.destroy()

    # ──────────────────────────────────────────────────────────────────
    # Header bar
    # ──────────────────────────────────────────────────────────────────
    def _build_header(self):
        hdr = tk.Frame(self.root, bg=BG2, height=42)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        # drag support
        hdr.bind("<ButtonPress-1>",   self._on_drag_start)
        hdr.bind("<B1-Motion>",       self._on_drag_move)

        # left: logo + filename
        left = tk.Frame(hdr, bg=BG2)
        left.pack(side="left", padx=10, fill="y")
        tk.Label(left, text="⚡", font=("Segoe UI Emoji", 14), bg=BG2,
                 fg=ACCENT_BLUE).pack(side="left", pady=8)
        fname = os.path.basename(self.filepath)
        tk.Label(left, text=f" NotepadAI  ·  {fname}",
                 font=FONT_TITLE, bg=BG2, fg=TEXT).pack(side="left", pady=8)

        # right: status dot
        self.status_dot = tk.Label(hdr, text="●  Watching",
                                   font=("Consolas", 8), bg=BG2, fg=ACCENT_GRN)
        self.status_dot.pack(side="right", padx=12)

    # ──────────────────────────────────────────────────────────────────
    # Notebook tabs
    # ──────────────────────────────────────────────────────────────────
    def _build_notebook(self):
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=0, pady=0)

        self._tab_next    = self._make_tab("💡  Next Step",  self._build_next_tab)
        self._tab_improve = self._make_tab("🔧  Improve",    self._build_improve_tab)
        self._tab_english = self._make_tab("✨  English→Code", self._build_english_tab)

    def _make_tab(self, label, builder):
        frame = tk.Frame(self.nb, bg=BG)
        self.nb.add(frame, text=label)
        builder(frame)
        return frame

    # ── Next Step tab ──────────────────────────────────────────────────
    def _build_next_tab(self, parent):
        pad = tk.Frame(parent, bg=BG, padx=12, pady=10)
        pad.pack(fill="both", expand=True)

        # Lang + complexity pills row
        prow = tk.Frame(pad, bg=BG)
        prow.pack(fill="x", pady=(0, 8))
        self._lang_pill  = _pill(prow, "python", ACCENT_BLUE)
        self._lang_pill.pack(side="left", padx=(0, 6))
        self._comp_pill  = _pill(prow, "beginner", BG3)
        self._comp_pill.pack(side="left")
        self._comp_pill.config(fg=TEXT_DIM)

        tk.Label(pad, text="What to do next:", font=FONT_UI_B,
                 bg=BG, fg=TEXT_DIM).pack(anchor="w")
        self._next_box = _ScrollText(pad, height=7)
        self._next_box.pack(fill="both", expand=True, pady=(4, 0))
        self._next_box.set_text("Save your file (Ctrl+S) to get AI suggestions…")

    # ── Improve tab ────────────────────────────────────────────────────
    def _build_improve_tab(self, parent):
        pad = tk.Frame(parent, bg=BG, padx=12, pady=10)
        pad.pack(fill="both", expand=True)
        tk.Label(pad, text="Suggested improvement:", font=FONT_UI_B,
                 bg=BG, fg=TEXT_DIM).pack(anchor="w")
        self._improve_box = _ScrollText(pad, height=7)
        self._improve_box.pack(fill="both", expand=True, pady=(4, 8))
        self._improve_box.set_text("No suggestions yet. Save your file to analyse.")

    # ── English→Code tab ──────────────────────────────────────────────
    def _build_english_tab(self, parent):
        self._eng_parent = parent
        pad = tk.Frame(parent, bg=BG, padx=12, pady=10)
        pad.pack(fill="both", expand=True)

        tk.Label(pad, text="English lines detected in your code:",
                 font=FONT_UI_B, bg=BG, fg=TEXT_DIM).pack(anchor="w")
        tk.Label(pad,
                 text="Write a sentence in plain English inside your .py file\n"
                      "and NotepadAI will convert it to Python code.",
                 font=FONT_UI, bg=BG, fg=TEXT_DIM, justify="left").pack(anchor="w", pady=(2, 8))

        # Scrollable container for conversion cards
        canvas_frame = tk.Frame(pad, bg=BG)
        canvas_frame.pack(fill="both", expand=True)

        self._eng_canvas = tk.Canvas(canvas_frame, bg=BG, highlightthickness=0)
        eng_scroll = tk.Scrollbar(canvas_frame, orient="vertical",
                                  command=self._eng_canvas.yview,
                                  bg=BG2, width=8, relief="flat", bd=0)
        self._eng_canvas.configure(yscrollcommand=eng_scroll.set)
        self._eng_canvas.pack(side="left", fill="both", expand=True)
        eng_scroll.pack(side="right", fill="y")

        self._eng_inner = tk.Frame(self._eng_canvas, bg=BG)
        self._eng_canvas_window = self._eng_canvas.create_window(
            (0, 0), window=self._eng_inner, anchor="nw"
        )
        self._eng_inner.bind("<Configure>", self._on_eng_inner_configure)
        self._eng_canvas.bind("<Configure>", self._on_eng_canvas_configure)

        self._no_english_label = tk.Label(
            self._eng_inner,
            text="No English lines detected.\nTry writing a plain sentence in your .py file.",
            font=FONT_UI, bg=BG, fg=TEXT_DIM, justify="center",
        )
        self._no_english_label.pack(pady=30)

    def _on_eng_inner_configure(self, _event):
        self._eng_canvas.configure(scrollregion=self._eng_canvas.bbox("all"))

    def _on_eng_canvas_configure(self, event):
        self._eng_canvas.itemconfig(self._eng_canvas_window, width=event.width)

    # ──────────────────────────────────────────────────────────────────
    # Status bar
    # ──────────────────────────────────────────────────────────────────
    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg=BG2, height=26)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        self._status_bar = tk.Label(bar, text="Ready  ·  Open a .py file in Notepad and save to begin",
                                    font=("Consolas", 8), bg=BG2, fg=TEXT_DIM, anchor="w")
        self._status_bar.pack(side="left", padx=10, fill="y")

        self._topmost_btn = tk.Label(bar, text="📌 Pin", font=("Consolas", 8),
                                     bg=BG2, fg=ACCENT_BLUE, cursor="hand2")
        self._topmost_btn.pack(side="right", padx=10)
        self._topmost_btn.bind("<Button-1>", self._toggle_topmost)
        self._pinned = True

    def _toggle_topmost(self, _event=None):
        self._pinned = not self._pinned
        self.root.attributes("-topmost", self._pinned)
        self._topmost_btn.config(
            text="📌 Pin" if self._pinned else "📍 Unpin",
            fg=ACCENT_BLUE if self._pinned else TEXT_DIM,
        )

    # ──────────────────────────────────────────────────────────────────
    # Drag support
    # ──────────────────────────────────────────────────────────────────
    def _on_drag_start(self, event):
        self._drag_start_x = event.x_root - self.root.winfo_x()
        self._drag_start_y = event.y_root - self.root.winfo_y()

    def _on_drag_move(self, event):
        x = event.x_root - self._drag_start_x
        y = event.y_root - self._drag_start_y
        self.root.geometry(f"+{x}+{y}")

    # ──────────────────────────────────────────────────────────────────
    # Callbacks (called from background threads → must use after())
    # ──────────────────────────────────────────────────────────────────
    def on_file_changed(self, content: str):
        self._current_code = content
        self.root.after(0, self._set_analyzing_state, True)
        self.ai_engine.debounced_analyze(
            content,
            on_suggestions=lambda d: self.root.after(0, self._update_suggestions, d),
            on_english=lambda items: self.root.after(0, self._update_english, items),
            delay=1.8,
        )

    def _set_analyzing_state(self, analyzing: bool):
        if analyzing:
            self.status_dot.config(text="◌  Analyzing…", fg=ACCENT_YLW)
            self._status_bar.config(text="Analyzing code…")
        else:
            self.status_dot.config(text="●  Watching", fg=ACCENT_GRN)
            self._status_bar.config(
                text=f"Last analysis: {time.strftime('%H:%M:%S')}  ·  "
                     f"{self.filepath}"
            )

    def _update_suggestions(self, data: dict):
        self._set_analyzing_state(False)
        lang     = data.get("language", "python")
        next_s   = data.get("next_step", "")
        improve  = data.get("improvement", "")
        comp     = data.get("complexity", "")

        self._lang_pill.config(text=f" {lang} ")
        comp_colors = {
            "beginner":     ACCENT_GRN,
            "intermediate": ACCENT_YLW,
            "advanced":     ACCENT_RED,
        }
        self._comp_pill.config(
            text=f" {comp} ",
            bg=comp_colors.get(comp, BG3),
            fg=BG if comp in comp_colors else TEXT_DIM,
        )
        self._next_box.set_text(next_s or "Nothing to suggest yet.")
        self._improve_box.set_text(improve or "No improvements detected — looks good!")

    def _update_english(self, items: List[Dict]):
        # Clear previous cards
        for w in self._eng_inner.winfo_children():
            w.destroy()

        if not items:
            self._no_english_label = tk.Label(
                self._eng_inner,
                text="No English lines detected.\nWrite a plain sentence in your .py file!",
                font=FONT_UI, bg=BG, fg=TEXT_DIM, justify="center",
            )
            self._no_english_label.pack(pady=30)
            # Switch tab badge off
            idx = self.nb.index(self._tab_english)
            self.nb.tab(idx, text="✨  English→Code")
            return

        # Update tab badge
        idx = self.nb.index(self._tab_english)
        self.nb.tab(idx, text=f"✨  English→Code  ({len(items)})")

        for item in items:
            self._build_english_card(item)

    def _build_english_card(self, item: Dict):
        card = tk.Frame(self._eng_inner, bg=BG2, bd=0, relief="flat",
                        highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", pady=(0, 8), padx=2)

        # English line
        ehead = tk.Frame(card, bg=BG2)
        ehead.pack(fill="x", padx=8, pady=(8, 2))
        tk.Label(ehead, text="📝 English:", font=FONT_MONO_B,
                 bg=BG2, fg=TEXT_DIM).pack(side="left")
        tk.Label(ehead, text=f"  line {item['line_idx'] + 1}",
                 font=FONT_MONO, bg=BG2, fg=TEXT_DIM).pack(side="left")

        eng_lbl = tk.Label(card, text=item["english"], font=FONT_UI,
                           bg=BG3, fg=ACCENT_PRP, anchor="w", justify="left",
                           wraplength=340, padx=8, pady=4)
        eng_lbl.pack(fill="x", padx=8, pady=(0, 4))

        # Generated code
        tk.Label(card, text="⚡ Generated Python:", font=FONT_MONO_B,
                 bg=BG2, fg=TEXT_DIM).pack(anchor="w", padx=8, pady=(2, 0))

        code_box = _ScrollText(card, height=5, bg=CODE_BG)
        code_box.pack(fill="x", padx=8, pady=(2, 6))
        code_box.set_text(item["code"])

        # Buttons row
        btn_row = tk.Frame(card, bg=BG2)
        btn_row.pack(fill="x", padx=8, pady=(0, 8))

        apply_btn = tk.Button(
            btn_row,
            text="✅ Apply to File",
            font=FONT_UI_B,
            bg=ACCENT_GRN, fg=BG,
            relief="flat", bd=0,
            padx=10, pady=4,
            cursor="hand2",
            activebackground="#2ea043", activeforeground=BG,
            command=lambda i=item: self._apply_conversion(i),
        )
        apply_btn.pack(side="left", padx=(0, 6))

        copy_btn = tk.Button(
            btn_row,
            text="📋 Copy Code",
            font=FONT_UI,
            bg=BG3, fg=TEXT,
            relief="flat", bd=0,
            padx=10, pady=4,
            cursor="hand2",
            activebackground=BORDER, activeforeground=TEXT,
            command=lambda c=item["code"]: self._copy_to_clipboard(c),
        )
        copy_btn.pack(side="left")

    def _apply_conversion(self, item: Dict):
        """Replace the English line in the file with the generated code."""
        lines = self._current_code.splitlines(keepends=True)
        if item["line_idx"] >= len(lines):
            messagebox.showerror("Error", "Line index out of range. Save again.")
            return
        # Replace the line
        indent = len(lines[item["line_idx"]]) - len(lines[item["line_idx"]].lstrip())
        lines[item["line_idx"]] = item["code"] + "\n"
        new_content = "".join(lines)
        try:
            self.file_watcher.write(new_content)
            self._current_code = new_content
            messagebox.showinfo(
                "Applied ✅",
                f"English line replaced!\n\nNotepad may ask you to reload the file — click YES.",
            )
        except Exception as exc:
            messagebox.showerror("Write Error", str(exc))

    def _copy_to_clipboard(self, text: str):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    # ──────────────────────────────────────────────────────────────────
    # Entry point
    # ──────────────────────────────────────────────────────────────────
    def run(self):
        """Blocking call — runs the Tk main loop."""
        # Analyse whatever is already in the file
        initial = self.file_watcher.read_current()
        if initial.strip():
            self.on_file_changed(initial)
        self.root.mainloop()
