"""Desktop chat app for the Sabrina Zohar advice bot — no terminal window.

This is a plain tkinter app (Python stdlib, no extra GUI dependencies) meant to
be packaged with PyInstaller in --windowed mode, so launching it from a desktop
shortcut opens only the chat window and never a console. All work (RAG lookup,
API calls) runs in-process on a background thread — no subprocesses, so nothing
can pop a terminal.

Build the .exe with build_exe.bat, or download it from the "build-windows-exe"
GitHub Actions artifact.
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, simpledialog

from config import ROOT_DIR

APP_TITLE = "Sabrina Zohar Advice Bot"


def ensure_api_key(root: tk.Tk) -> bool:
    """Prompt for an Anthropic API key on first run and persist it to .env."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    key = simpledialog.askstring(
        APP_TITLE,
        "Enter your Anthropic API key\n(it will be saved to .env next to the app):",
        show="*",
        parent=root,
    )
    if not key or not key.strip():
        return False
    key = key.strip()
    os.environ["ANTHROPIC_API_KEY"] = key
    try:
        with open(ROOT_DIR / ".env", "a", encoding="utf-8") as f:
            f.write(f"\nANTHROPIC_API_KEY={key}\n")
    except OSError:
        pass  # still usable for this session even if we can't persist it
    return True


class AdvisorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("720x560")
        self.root.minsize(520, 400)

        self.history: list[dict] = []
        self.image_path: str | None = None
        self.results: queue.Queue = queue.Queue()
        self.busy = False

        # --- Chat transcript ---
        self.chat = scrolledtext.ScrolledText(root, wrap="word", state="disabled", padx=8, pady=8)
        self.chat.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        self.chat.tag_configure("you", foreground="#1a5fb4", font=("TkDefaultFont", 10, "bold"))
        self.chat.tag_configure("bot", foreground="#813d9c", font=("TkDefaultFont", 10, "bold"))
        self.chat.tag_configure("meta", foreground="#777777", font=("TkDefaultFont", 9, "italic"))

        # --- Attachment row ---
        attach_row = tk.Frame(root)
        attach_row.pack(fill="x", padx=8)
        tk.Button(attach_row, text="Attach screenshot…", command=self.pick_image).pack(side="left")
        self.image_label = tk.Label(attach_row, text="", anchor="w", fg="#555555")
        self.image_label.pack(side="left", padx=8)
        self.clear_btn = tk.Button(attach_row, text="✕", command=self.clear_image)

        # --- Input row ---
        input_row = tk.Frame(root)
        input_row.pack(fill="x", padx=8, pady=(4, 8))
        self.entry = tk.Text(input_row, height=3, wrap="word")
        self.entry.pack(side="left", fill="both", expand=True)
        self.entry.bind("<Return>", self.on_enter)
        self.entry.bind("<Shift-Return>", lambda e: None)  # Shift+Enter = newline
        self.send_btn = tk.Button(input_row, text="Send", width=8, command=self.send)
        self.send_btn.pack(side="left", padx=(6, 0), fill="y")

        self.status = tk.Label(root, text="Ready", anchor="w", fg="#555555")
        self.status.pack(fill="x", padx=8, pady=(0, 6))

        self.append_meta(
            "Ask a dating/relationship question, or attach a screenshot of a "
            "conversation. Shift+Enter for a new line."
        )
        self.root.after(100, self.poll_results)

    # --- UI helpers ---------------------------------------------------------

    def append(self, who: str, text: str, tag: str):
        self.chat.configure(state="normal")
        self.chat.insert("end", f"{who}\n", tag)
        self.chat.insert("end", f"{text}\n\n")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def append_meta(self, text: str):
        self.chat.configure(state="normal")
        self.chat.insert("end", f"{text}\n\n", "meta")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def pick_image(self):
        path = filedialog.askopenfilename(
            title="Choose a screenshot",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.webp"), ("All files", "*.*")],
        )
        if path:
            self.image_path = path
            self.image_label.config(text=os.path.basename(path))
            self.clear_btn.pack(side="left")

    def clear_image(self):
        self.image_path = None
        self.image_label.config(text="")
        self.clear_btn.pack_forget()

    def on_enter(self, event):
        if not (event.state & 0x0001):  # plain Enter (no Shift) sends
            self.send()
            return "break"
        return None

    # --- Sending / receiving ------------------------------------------------

    def send(self):
        if self.busy:
            return
        query = self.entry.get("1.0", "end").strip()
        image_path = self.image_path
        if not query and not image_path:
            return
        if not ensure_api_key(self.root):
            messagebox.showwarning(APP_TITLE, "An Anthropic API key is required to get advice.")
            return

        self.entry.delete("1.0", "end")
        shown = query or "(screenshot)"
        if query and image_path:
            shown = f"{query}  [+ {os.path.basename(image_path)}]"
        elif image_path:
            shown = f"[{os.path.basename(image_path)}]"
        self.append("You", shown, "you")
        self.clear_image()

        self.busy = True
        self.send_btn.config(state="disabled")
        self.status.config(text="Thinking…")
        threading.Thread(
            target=self._worker, args=(query, image_path), daemon=True
        ).start()

    def _worker(self, query: str, image_path: str | None):
        try:
            from advisor.sabrina_advisor import generate_sabrina_advice

            reply = generate_sabrina_advice(query, image_path=image_path, history=self.history)
            self.results.put(("ok", reply))
        except Exception as exc:  # surfaced in the UI — the app must never die silently
            self.results.put(("err", f"{exc}"))

    def poll_results(self):
        try:
            while True:
                kind, payload = self.results.get_nowait()
                self.busy = False
                self.send_btn.config(state="normal")
                self.status.config(text="Ready")
                if kind == "ok":
                    self.append("Sabrina Bot", payload, "bot")
                else:
                    self.append_meta(f"Error: {payload}")
        except queue.Empty:
            pass
        self.root.after(100, self.poll_results)


def main():
    root = tk.Tk()
    AdvisorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
