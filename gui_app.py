"""Desktop chat app for the Sabrina Zohar advice bot — no terminal window.

A themed tkinter app (Python stdlib only) packaged with PyInstaller --windowed,
so launching it opens straight into the chat UI and never shows a console. All
work (RAG lookup, streaming API calls) runs in-process on a background thread —
no subprocesses, so nothing can pop a terminal.

Features: streamed replies, up to 10 screenshots per message, multi-turn memory
that survives restarts, transcript export, API-key management, window icon and
remembered geometry.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

from assets_embedded import ICON_PNG_B64
from config import ANTHROPIC_MODEL, MAX_IMAGES_PER_MESSAGE, ROOT_DIR

APP_TITLE = "Sabrina Zohar Advice Bot"
APP_VERSION = "1.2.0"

SETTINGS_PATH = ROOT_DIR / "app_settings.json"
HISTORY_PATH = ROOT_DIR / "chat_history.json"
MAX_SAVED_MESSAGES = 40  # keep the last N messages (20 exchanges) for context

# --- Palette ---------------------------------------------------------------
BG = "#faf6f1"          # warm cream
SURFACE = "#ffffff"
ACCENT = "#e85d75"      # rose
ACCENT_DARK = "#c94a61"
TEXT = "#2b2926"
MUTED = "#8a8580"
YOU = "#2d5da8"
BOT = "#b5537a"

FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_SMALL = ("Segoe UI", 9)

PLACEHOLDER = "Type your question…  (Enter to send, Shift+Enter for a new line)"


# --- Small persistence helpers ---------------------------------------------

def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, data):
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def sanitize_history(history: list[dict]) -> list[dict]:
    """Text-only copy of the API history, safe to persist (no base64 images)."""
    out = []
    for msg in history:
        content = msg.get("content")
        if isinstance(content, str):
            text = content
        else:
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block["text"])
                elif isinstance(block, dict) and block.get("type") == "image":
                    parts.append("[screenshot attached earlier — not saved]")
            text = "\n".join(parts)
        if text.strip():
            out.append({"role": msg["role"], "content": text})
    return out


def trim_history(history: list[dict]) -> list[dict]:
    """Cap history length and make sure it still starts with a user turn."""
    trimmed = history[-MAX_SAVED_MESSAGES:]
    while trimmed and trimmed[0].get("role") != "user":
        trimmed.pop(0)
    return trimmed


# --- API key management -----------------------------------------------------

def store_api_key(key: str):
    """Write/replace ANTHROPIC_API_KEY in the .env next to the app."""
    os.environ["ANTHROPIC_API_KEY"] = key
    env_path = ROOT_DIR / ".env"
    lines = []
    if env_path.exists():
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
    lines = [ln for ln in lines if not ln.strip().startswith("ANTHROPIC_API_KEY=")]
    lines.append(f"ANTHROPIC_API_KEY={key}")
    try:
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass  # key still works for this session
    # Force the advisor to rebuild its client with the new key
    try:
        import advisor.sabrina_advisor as adv

        adv._client = None
    except Exception:
        pass


def prompt_api_key(root, forced: bool = False) -> bool:
    if not forced and os.environ.get("ANTHROPIC_API_KEY"):
        return True
    key = simpledialog.askstring(
        APP_TITLE,
        "Enter your Anthropic API key\n(saved to .env next to the app — you'll only do this once):",
        show="*",
        parent=root,
    )
    if not key or not key.strip():
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    store_api_key(key.strip())
    return True


# --- Main app ----------------------------------------------------------------

class AdvisorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.configure(bg=BG)
        self.root.minsize(560, 440)

        settings = load_json(SETTINGS_PATH, {})
        self.root.geometry(settings.get("geometry", "760x600"))

        try:
            self.icon = tk.PhotoImage(data=ICON_PNG_B64)
            self.root.iconphoto(True, self.icon)
        except tk.TclError:
            pass

        self.history: list[dict] = []
        self.image_paths: list[str] = []
        self.results: queue.Queue = queue.Queue()
        self.busy = False
        self.streaming = False
        self._spinner_step = 0

        self._build_styles()
        self._build_menu()
        self._build_widgets()
        self._restore_history()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(80, self.poll_results)

    # -- construction --------------------------------------------------------

    def _build_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Accent.TButton", font=FONT_BOLD, foreground="#ffffff",
                        background=ACCENT, borderwidth=0, focuscolor=ACCENT, padding=(14, 6))
        style.map("Accent.TButton",
                  background=[("active", ACCENT_DARK), ("disabled", "#d8b3bb")])
        style.configure("Soft.TButton", font=FONT, foreground=TEXT,
                        background="#f0e9e1", borderwidth=0, padding=(10, 5))
        style.map("Soft.TButton", background=[("active", "#e5dcd1")])

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New conversation", accelerator="Ctrl+N", command=self.new_conversation)
        file_menu.add_command(label="Save transcript…", command=self.save_transcript)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Update API key…", command=lambda: prompt_api_key(self.root, forced=True))
        menubar.add_cascade(label="Settings", menu=settings_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)
        self.root.bind("<Control-n>", lambda e: self.new_conversation())

    def _build_widgets(self):
        # Chat transcript
        chat_frame = tk.Frame(self.root, bg=BG)
        chat_frame.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        self.chat = scrolledtext.ScrolledText(
            chat_frame, wrap="word", state="disabled", relief="flat",
            bg=SURFACE, fg=TEXT, font=FONT, padx=14, pady=12,
            selectbackground="#f3c9d2", insertbackground=TEXT,
        )
        self.chat.pack(fill="both", expand=True)
        self.chat.tag_configure("you", foreground=YOU, font=FONT_BOLD, spacing1=8)
        self.chat.tag_configure("bot", foreground=BOT, font=FONT_BOLD, spacing1=8)
        self.chat.tag_configure("body", lmargin1=14, lmargin2=14, spacing3=6)
        self.chat.tag_configure("meta", foreground=MUTED, font=FONT_SMALL, spacing1=6, spacing3=6)

        # Attachment row
        attach_row = tk.Frame(self.root, bg=BG)
        attach_row.pack(fill="x", padx=12)
        ttk.Button(attach_row, text=f"📎 Attach screenshots (max {MAX_IMAGES_PER_MESSAGE})",
                   style="Soft.TButton", command=self.pick_images).pack(side="left")
        self.image_label = tk.Label(attach_row, text="", anchor="w", bg=BG, fg=MUTED, font=FONT_SMALL)
        self.image_label.pack(side="left", padx=8)
        self.clear_btn = ttk.Button(attach_row, text="✕ clear", style="Soft.TButton",
                                    command=self.clear_images)

        # Input row
        input_row = tk.Frame(self.root, bg=BG)
        input_row.pack(fill="x", padx=12, pady=(6, 4))
        entry_frame = tk.Frame(input_row, bg="#e0d8cd", padx=1, pady=1)
        entry_frame.pack(side="left", fill="both", expand=True)
        self.entry = tk.Text(entry_frame, height=3, wrap="word", relief="flat",
                             bg=SURFACE, fg=MUTED, font=FONT, padx=10, pady=8,
                             insertbackground=TEXT)
        self.entry.pack(fill="both", expand=True)
        self.entry.insert("1.0", PLACEHOLDER)
        self._placeholder_active = True
        self.entry.bind("<FocusIn>", self._clear_placeholder)
        self.entry.bind("<FocusOut>", self._maybe_restore_placeholder)
        self.entry.bind("<Return>", self.on_enter)
        self.entry.bind("<Shift-Return>", lambda e: None)
        self.send_btn = ttk.Button(input_row, text="Send ➤", style="Accent.TButton", command=self.send)
        self.send_btn.pack(side="left", padx=(8, 0), fill="y")

        # Status + disclaimer footer
        footer = tk.Frame(self.root, bg=BG)
        footer.pack(fill="x", padx=14, pady=(0, 8))
        self.status = tk.Label(footer, text="Ready", anchor="w", bg=BG, fg=MUTED, font=FONT_SMALL)
        self.status.pack(side="left")
        tk.Label(footer, text="Coaching-style advice, not therapy · in crisis call 988 (US)",
                 anchor="e", bg=BG, fg=MUTED, font=FONT_SMALL).pack(side="right")

    # -- placeholder handling -------------------------------------------------

    def _clear_placeholder(self, _event=None):
        if self._placeholder_active:
            self.entry.delete("1.0", "end")
            self.entry.config(fg=TEXT)
            self._placeholder_active = False

    def _maybe_restore_placeholder(self, _event=None):
        if not self.entry.get("1.0", "end").strip():
            self.entry.delete("1.0", "end")
            self.entry.insert("1.0", PLACEHOLDER)
            self.entry.config(fg=MUTED)
            self._placeholder_active = True

    # -- transcript helpers ---------------------------------------------------

    def _append(self, parts: list[tuple[str, str]]):
        self.chat.configure(state="normal")
        for text, tag in parts:
            self.chat.insert("end", text, tag)
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def append_msg(self, who: str, text: str, tag: str):
        self._append([(f"{who}\n", tag), (f"{text}\n", "body")])

    def append_meta(self, text: str):
        self._append([(f"{text}\n", "meta")])

    # -- attachments ----------------------------------------------------------

    def pick_images(self):
        paths = filedialog.askopenfilenames(
            title=f"Choose up to {MAX_IMAGES_PER_MESSAGE} screenshots",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.webp"), ("All files", "*.*")],
        )
        if not paths:
            return
        room = MAX_IMAGES_PER_MESSAGE - len(self.image_paths)
        if len(paths) > room:
            messagebox.showwarning(
                APP_TITLE,
                f"Max {MAX_IMAGES_PER_MESSAGE} screenshots per message — "
                f"keeping the first {room} of your selection.",
            )
            paths = paths[:room]
        self.image_paths.extend(paths)
        self.update_image_label()

    def update_image_label(self):
        n = len(self.image_paths)
        if n == 0:
            self.image_label.config(text="")
            self.clear_btn.pack_forget()
        else:
            names = os.path.basename(self.image_paths[0]) if n == 1 else f"{n} screenshots attached"
            self.image_label.config(text=names)
            self.clear_btn.pack(side="left")

    def clear_images(self):
        self.image_paths = []
        self.update_image_label()

    # -- menu actions ---------------------------------------------------------

    def new_conversation(self):
        if self.busy:
            return
        self.history = []
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.configure(state="disabled")
        try:
            HISTORY_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        self.append_meta("New conversation started.")

    def save_transcript(self):
        path = filedialog.asksaveasfilename(
            title="Save transcript", defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")],
            initialfile="sabrina-advice-transcript.txt",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.chat.get("1.0", "end").strip() + "\n")
            self.append_meta(f"Transcript saved to {os.path.basename(path)}.")
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Could not save transcript: {exc}")

    def show_about(self):
        messagebox.showinfo(
            APP_TITLE,
            f"{APP_TITLE} v{APP_VERSION}\n\n"
            f"Dating & relationship advice in Sabrina Zohar's coaching style, "
            f"powered by Claude ({ANTHROPIC_MODEL}).\n\n"
            "Attach up to 10 screenshots of a conversation per message.\n\n"
            "This is coaching-style advice, not therapy or medical advice. "
            "If you're in crisis, call 988 (US) or your local emergency services.",
        )

    # -- persistence ----------------------------------------------------------

    def _restore_history(self):
        saved = load_json(HISTORY_PATH, [])
        if not saved:
            self.append_meta(
                f"Ask a dating/relationship question, or attach up to "
                f"{MAX_IMAGES_PER_MESSAGE} screenshots of a conversation."
            )
            return
        self.history = trim_history(saved)
        for msg in self.history:
            who, tag = ("You", "you") if msg["role"] == "user" else ("Sabrina", "bot")
            self.append_msg(who, msg["content"], tag)
        self.append_meta("— restored previous conversation (File → New conversation to start fresh) —")

    def _persist(self):
        save_json(HISTORY_PATH, sanitize_history(trim_history(self.history)))
        save_json(SETTINGS_PATH, {"geometry": self.root.geometry()})

    def on_close(self):
        self._persist()
        self.root.destroy()

    # -- sending / receiving --------------------------------------------------

    def on_enter(self, event):
        if not (event.state & 0x0001):  # plain Enter sends; Shift+Enter = newline
            self.send()
            return "break"
        return None

    def send(self):
        if self.busy:
            return
        query = "" if self._placeholder_active else self.entry.get("1.0", "end").strip()
        image_paths = list(self.image_paths)
        if not query and not image_paths:
            return
        if not prompt_api_key(self.root):
            messagebox.showwarning(APP_TITLE, "An Anthropic API key is required to get advice.")
            return

        self.entry.delete("1.0", "end")
        if len(image_paths) == 1:
            attach_note = f"[+ {os.path.basename(image_paths[0])}]"
        elif image_paths:
            attach_note = f"[+ {len(image_paths)} screenshots]"
        else:
            attach_note = ""
        shown = f"{query}  {attach_note}".strip() if query else attach_note
        self.append_msg("You", shown, "you")
        self.clear_images()

        # Keep request size bounded on long-running conversations
        self.history = trim_history(self.history)

        self.busy = True
        self.streaming = False
        self.send_btn.config(state="disabled")
        self._animate_status()
        threading.Thread(target=self._worker, args=(query, image_paths), daemon=True).start()

    def _worker(self, query: str, image_paths: list[str]):
        try:
            from advisor.sabrina_advisor import generate_sabrina_advice

            reply = generate_sabrina_advice(
                query,
                image_paths=image_paths,
                history=self.history,
                on_delta=lambda t: self.results.put(("delta", t)),
            )
            self.results.put(("done", reply))
        except Exception as exc:  # surfaced in the UI — the app must never die silently
            self.results.put(("err", f"{exc}"))

    def _animate_status(self):
        if not self.busy:
            self.status.config(text="Ready")
            return
        dots = "." * (self._spinner_step % 4)
        self.status.config(text=f"Sabrina is thinking{dots}")
        self._spinner_step += 1
        self.root.after(400, self._animate_status)

    def poll_results(self):
        try:
            while True:
                kind, payload = self.results.get_nowait()
                if kind == "delta":
                    if not self.streaming:
                        self.streaming = True
                        self._append([("Sabrina\n", "bot")])
                        self.status.config(text="Sabrina is typing…")
                    self._append([(payload, "body")])
                elif kind == "done":
                    if self.streaming:
                        self._append([("\n", "body")])
                    else:  # no deltas (e.g. a refusal) — show the full reply
                        self.append_msg("Sabrina", payload, "bot")
                    self._finish_turn()
                    self._persist()
                elif kind == "err":
                    if self.streaming:
                        self._append([("\n", "body")])
                    self.append_meta(f"⚠ {payload}")
                    self._finish_turn()
        except queue.Empty:
            pass
        self.root.after(80, self.poll_results)

    def _finish_turn(self):
        self.busy = False
        self.streaming = False
        self.send_btn.config(state="normal")
        self.status.config(text="Ready")


def main():
    root = tk.Tk()
    AdvisorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
