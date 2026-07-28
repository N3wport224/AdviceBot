"""Desktop chat app for the Sabrina Zohar advice bot — no terminal window.

A themed tkinter app packaged with PyInstaller --windowed, so launching it
opens straight into the chat UI and never shows a console. All work (RAG
lookup, streaming API calls) runs in-process on a background thread — no
subprocesses, so nothing can pop a terminal.

Features: streamed replies, up to 10 screenshots per message (file picker or
Ctrl+V paste), light/dark themes, adjustable text size, quick-start suggestion
chips, multi-turn memory that survives restarts, transcript export, API-key
management, message timestamps, window icon and remembered geometry.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

from assets_embedded import ICON_PNG_B64
from config import ANTHROPIC_MODEL, MAX_IMAGES_PER_MESSAGE, ROOT_DIR

APP_TITLE = "Sabrina Zohar Advice Bot"
APP_VERSION = "1.3.0"

SETTINGS_PATH = ROOT_DIR / "app_settings.json"
HISTORY_PATH = ROOT_DIR / "chat_history.json"
PASTE_DIR = ROOT_DIR / "pasted_screenshots"
MAX_SAVED_MESSAGES = 40  # keep the last N messages (20 exchanges) for context

THEMES = {
    "light": dict(
        bg="#faf6f1", surface="#ffffff", text="#2b2926", muted="#8a8580",
        accent="#e85d75", accent_dark="#c94a61", accent_disabled="#d8b3bb",
        you="#2d5da8", bot="#b5537a", soft="#f0e9e1", soft_active="#e5dcd1",
        border="#e0d8cd", select="#f3c9d2",
    ),
    "dark": dict(
        bg="#211d1a", surface="#2c2724", text="#efe9e3", muted="#9b938c",
        accent="#e85d75", accent_dark="#c94a61", accent_disabled="#6b4a51",
        you="#8ab0ec", bot="#e390b0", soft="#3a332e", soft_active="#463d37",
        border="#463d37", select="#5a3a44",
    ),
}

SUGGESTIONS = [
    "Is he breadcrumbing me?",
    "Should I double-text?",
    "How do I stop obsessing?",
    "Read this convo for me 📎",
]

PLACEHOLDER = "Type your question…  (Enter to send · Shift+Enter for a new line · Ctrl+V pastes a screenshot)"


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
        self.root.minsize(560, 460)

        self.settings = load_json(SETTINGS_PATH, {})
        self.root.geometry(self.settings.get("geometry", "780x620"))
        self.theme_name = self.settings.get("theme", "light")
        if self.theme_name not in THEMES:
            self.theme_name = "light"
        self.font_size = int(self.settings.get("font_size", 10))
        self.font_size = min(max(self.font_size, 8), 16)

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
        self._placeholder_active = True

        self.style = ttk.Style(self.root)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        self._build_menu()
        self._build_widgets()
        self.apply_theme()
        self._restore_history()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(80, self.poll_results)
        self._cleanup_pasted()

    def _cleanup_pasted(self):
        """Delete pasted-screenshot temp files older than a week."""
        try:
            cutoff = time.time() - 7 * 86400
            for f in PASTE_DIR.glob("pasted_*.png"):
                if f.stat().st_mtime < cutoff:
                    f.unlink()
        except OSError:
            pass

    # -- fonts / theme --------------------------------------------------------

    def _fonts(self):
        s = self.font_size
        return {
            "base": ("Segoe UI", s),
            "bold": ("Segoe UI", s, "bold"),
            "small": ("Segoe UI", max(s - 1, 7)),
        }

    def apply_theme(self):
        t = THEMES[self.theme_name]
        f = self._fonts()

        self.root.configure(bg=t["bg"])
        for frame in self._bg_frames:
            frame.configure(bg=t["bg"])
        self.entry_border.configure(bg=t["border"])

        self.chat.configure(bg=t["surface"], fg=t["text"], font=f["base"],
                            selectbackground=t["select"], insertbackground=t["text"])
        self.chat.tag_configure("you", foreground=t["you"], font=f["bold"], spacing1=8)
        self.chat.tag_configure("bot", foreground=t["bot"], font=f["bold"], spacing1=8)
        self.chat.tag_configure("stamp", foreground=t["muted"], font=f["small"])
        self.chat.tag_configure("body", foreground=t["text"], font=f["base"],
                                lmargin1=14, lmargin2=14, spacing3=6)
        self.chat.tag_configure("meta", foreground=t["muted"], font=f["small"],
                                spacing1=6, spacing3=6)

        entry_fg = t["muted"] if self._placeholder_active else t["text"]
        self.entry.configure(bg=t["surface"], fg=entry_fg, font=f["base"],
                             insertbackground=t["text"])
        self.image_label.configure(bg=t["bg"], fg=t["muted"], font=f["small"])
        self.status.configure(bg=t["bg"], fg=t["muted"], font=f["small"])
        self.disclaimer.configure(bg=t["bg"], fg=t["muted"], font=f["small"])

        self.style.configure("Accent.TButton", font=f["bold"], foreground="#ffffff",
                             background=t["accent"], borderwidth=0,
                             focuscolor=t["accent"], padding=(14, 6))
        self.style.map("Accent.TButton",
                       background=[("active", t["accent_dark"]), ("disabled", t["accent_disabled"])])
        self.style.configure("Soft.TButton", font=f["base"], foreground=t["text"],
                             background=t["soft"], borderwidth=0, padding=(10, 5))
        self.style.map("Soft.TButton", background=[("active", t["soft_active"])])
        self.style.configure("Chip.TButton", font=f["small"], foreground=t["text"],
                             background=t["soft"], borderwidth=0, padding=(10, 4))
        self.style.map("Chip.TButton", background=[("active", t["soft_active"])])

    def toggle_theme(self):
        self.theme_name = "dark" if self.theme_name == "light" else "light"
        self.dark_var.set(self.theme_name == "dark")
        self.apply_theme()

    def change_font(self, delta: int | None):
        self.font_size = 10 if delta is None else min(max(self.font_size + delta, 8), 16)
        self.apply_theme()

    # -- construction --------------------------------------------------------

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New conversation", accelerator="Ctrl+N", command=self.new_conversation)
        file_menu.add_command(label="Save transcript…", command=self.save_transcript)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        self.dark_var = tk.BooleanVar(value=self.theme_name == "dark")
        view_menu.add_checkbutton(label="Dark mode", variable=self.dark_var, command=self.toggle_theme)
        view_menu.add_separator()
        view_menu.add_command(label="Larger text", accelerator="Ctrl+=", command=lambda: self.change_font(+1))
        view_menu.add_command(label="Smaller text", accelerator="Ctrl+-", command=lambda: self.change_font(-1))
        view_menu.add_command(label="Reset text size", accelerator="Ctrl+0", command=lambda: self.change_font(None))
        menubar.add_cascade(label="View", menu=view_menu)

        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Update API key…", command=lambda: prompt_api_key(self.root, forced=True))
        menubar.add_cascade(label="Settings", menu=settings_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)
        self.root.bind("<Control-n>", lambda e: self.new_conversation())
        self.root.bind("<Control-equal>", lambda e: self.change_font(+1))
        self.root.bind("<Control-plus>", lambda e: self.change_font(+1))
        self.root.bind("<Control-minus>", lambda e: self.change_font(-1))
        self.root.bind("<Control-0>", lambda e: self.change_font(None))

    def _build_widgets(self):
        self._bg_frames = []

        chat_frame = tk.Frame(self.root)
        chat_frame.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        self._bg_frames.append(chat_frame)
        self.chat = scrolledtext.ScrolledText(chat_frame, wrap="word", state="disabled",
                                              relief="flat", padx=14, pady=12)
        self.chat.pack(fill="both", expand=True)

        # Quick-start suggestion chips (shown while the conversation is empty)
        self.chips_frame = tk.Frame(self.root)
        self._bg_frames.append(self.chips_frame)
        for text in SUGGESTIONS:
            ttk.Button(self.chips_frame, text=text, style="Chip.TButton",
                       command=lambda q=text: self.use_suggestion(q)).pack(
                side="left", padx=(0, 6), pady=2)

        self.attach_row = tk.Frame(self.root)
        self.attach_row.pack(fill="x", padx=12)
        self._bg_frames.append(self.attach_row)
        ttk.Button(self.attach_row, text=f"📎 Attach screenshots (max {MAX_IMAGES_PER_MESSAGE})",
                   style="Soft.TButton", command=self.pick_images).pack(side="left")
        self.image_label = tk.Label(self.attach_row, text="", anchor="w")
        self.image_label.pack(side="left", padx=8)
        self.clear_btn = ttk.Button(self.attach_row, text="✕ clear", style="Soft.TButton",
                                    command=self.clear_images)

        input_row = tk.Frame(self.root)
        input_row.pack(fill="x", padx=12, pady=(6, 4))
        self._bg_frames.append(input_row)
        # Pack the button FIRST: with pack(), an expanding widget packed earlier
        # starves later siblings — packing the entry first crushed the button.
        self.send_btn = ttk.Button(input_row, text="Send ➤", style="Accent.TButton", command=self.send)
        self.send_btn.pack(side="right", padx=(8, 0), fill="y")
        self.entry_border = tk.Frame(input_row, padx=1, pady=1)
        self.entry_border.pack(side="left", fill="both", expand=True)
        self.entry = tk.Text(self.entry_border, height=3, wrap="word", relief="flat",
                             padx=10, pady=8)
        self.entry.pack(fill="both", expand=True)
        self.entry.insert("1.0", PLACEHOLDER)
        self.entry.bind("<FocusIn>", self._clear_placeholder)
        self.entry.bind("<FocusOut>", self._maybe_restore_placeholder)
        self.entry.bind("<Return>", self.on_enter)
        self.entry.bind("<Shift-Return>", lambda e: None)
        self.entry.bind("<Control-v>", self._on_paste)

        footer = tk.Frame(self.root)
        footer.pack(fill="x", padx=14, pady=(0, 8))
        self._bg_frames.append(footer)
        self.status = tk.Label(footer, text="Ready", anchor="w")
        self.status.pack(side="left")
        self.disclaimer = tk.Label(footer, text="Coaching-style advice, not therapy · in crisis call 988 (US)",
                                   anchor="e")
        self.disclaimer.pack(side="right")

    def show_chips(self):
        self.chips_frame.pack(fill="x", padx=12, pady=(0, 4), before=self.attach_row)

    def hide_chips(self):
        self.chips_frame.pack_forget()

    def use_suggestion(self, text: str):
        self._clear_placeholder()
        self.entry.delete("1.0", "end")
        self.entry.insert("1.0", text)
        self.entry.focus_set()

    # -- placeholder handling -------------------------------------------------

    def _clear_placeholder(self, _event=None):
        if self._placeholder_active:
            self.entry.delete("1.0", "end")
            self.entry.config(fg=THEMES[self.theme_name]["text"])
            self._placeholder_active = False

    def _maybe_restore_placeholder(self, _event=None):
        if not self.entry.get("1.0", "end").strip():
            self.entry.delete("1.0", "end")
            self.entry.insert("1.0", PLACEHOLDER)
            self.entry.config(fg=THEMES[self.theme_name]["muted"])
            self._placeholder_active = True

    # -- transcript helpers ---------------------------------------------------

    def _append(self, parts: list[tuple[str, str]]):
        # Only auto-scroll when the user is already at (or near) the bottom, so
        # scrolling up to reread isn't yanked away by streaming output.
        at_bottom = self.chat.yview()[1] >= 0.97
        self.chat.configure(state="normal")
        for text, tag in parts:
            self.chat.insert("end", text, tag)
        self.chat.configure(state="disabled")
        if at_bottom:
            self.chat.see("end")

    def _msg_header(self, who: str, tag: str, stamp: bool = True) -> list[tuple[str, str]]:
        if not stamp:
            return [(f"{who}\n", tag)]
        return [(f"{who}", tag), (f"  ·  {time.strftime('%H:%M')}\n", "stamp")]

    def append_msg(self, who: str, text: str, tag: str, stamp: bool = True):
        self._append(self._msg_header(who, tag, stamp) + [(f"{text}\n", "body")])

    def append_meta(self, text: str):
        self._append([(f"{text}\n", "meta")])

    # -- attachments ----------------------------------------------------------

    def pick_images(self):
        paths = filedialog.askopenfilenames(
            title=f"Choose up to {MAX_IMAGES_PER_MESSAGE} screenshots",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.webp"), ("All files", "*.*")],
        )
        if paths:
            self._add_images(paths)

    def _add_images(self, paths):
        room = MAX_IMAGES_PER_MESSAGE - len(self.image_paths)
        if len(paths) > room:
            messagebox.showwarning(
                APP_TITLE,
                f"Max {MAX_IMAGES_PER_MESSAGE} screenshots per message — "
                f"keeping the first {room} of your selection.",
            )
            paths = list(paths)[:room]
        self.image_paths.extend(paths)
        self.update_image_label()

    def _on_paste(self, _event=None):
        """Ctrl+V: attach an image from the clipboard; fall through to normal
        text paste when the clipboard holds text (or Pillow is unavailable)."""
        try:
            from PIL import Image, ImageGrab

            grabbed = ImageGrab.grabclipboard()
        except Exception:
            return None  # no Pillow / unsupported platform → default paste
        if grabbed is None:
            return None
        if isinstance(grabbed, list):  # copied files (Windows Explorer)
            image_files = [str(p) for p in grabbed
                           if str(p).lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))]
            if not image_files:
                return None
            self._add_images(image_files)
            return "break"
        if isinstance(grabbed, Image.Image):
            if len(self.image_paths) >= MAX_IMAGES_PER_MESSAGE:
                messagebox.showwarning(APP_TITLE, f"Max {MAX_IMAGES_PER_MESSAGE} screenshots per message.")
                return "break"
            try:
                PASTE_DIR.mkdir(exist_ok=True)
                path = PASTE_DIR / f"pasted_{int(time.time() * 1000)}.png"
                grabbed.save(path, "PNG")
            except OSError as exc:
                messagebox.showerror(APP_TITLE, f"Could not save pasted screenshot: {exc}")
                return "break"
            self._add_images([str(path)])
            return "break"
        return None

    def update_image_label(self):
        n = len(self.image_paths)
        if n == 0:
            self.image_label.config(text="")
            self.clear_btn.pack_forget()
        else:
            text = os.path.basename(self.image_paths[0]) if n == 1 else f"{n} screenshots attached"
            self.image_label.config(text=text)
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
        self.show_chips()

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
            "Attach up to 10 screenshots per message — use the 📎 button or just "
            "press Ctrl+V to paste one from the clipboard.\n\n"
            "This is coaching-style advice, not therapy or medical advice. "
            "If you're in crisis, call 988 (US) or your local emergency services.",
        )

    # -- persistence ----------------------------------------------------------

    def _restore_history(self):
        saved = load_json(HISTORY_PATH, [])
        if not saved:
            self.append_meta(
                f"Ask a dating/relationship question, or attach up to "
                f"{MAX_IMAGES_PER_MESSAGE} screenshots of a conversation "
                "(📎 or Ctrl+V)."
            )
            self.show_chips()
            return
        self.history = trim_history(saved)
        for msg in self.history:
            who, tag = ("You", "you") if msg["role"] == "user" else ("Sabrina", "bot")
            # No timestamp on restored messages — stamping them with the current
            # time would be misleading.
            self.append_msg(who, msg["content"], tag, stamp=False)
        self.append_meta("— restored previous conversation (File → New conversation to start fresh) —")

    def _persist(self):
        save_json(HISTORY_PATH, sanitize_history(trim_history(self.history)))
        self.settings.update({
            "geometry": self.root.geometry(),
            "theme": self.theme_name,
            "font_size": self.font_size,
        })
        save_json(SETTINGS_PATH, self.settings)

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
        self.hide_chips()
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
        if not self.streaming:
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
                        self._append(self._msg_header("Sabrina", "bot"))
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
