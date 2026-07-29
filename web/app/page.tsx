"use client";

import {
  ArrowUp,
  Heart,
  ImagePlus,
  MessageCircleHeart,
  Sparkles,
  Wind,
  X,
} from "lucide-react";
import {
  FormEvent,
  KeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";

const MAX_IMAGES = 10;

type Message = {
  id: number;
  role: "user" | "assistant";
  content: string;
  /** Object URLs for user-attached screenshots (display only). */
  imageUrls?: string[];
};

type Attachment = { file: File; previewUrl: string };

const STARTERS = [
  {
    icon: MessageCircleHeart,
    title: "Analyze this text message…",
    subtitle: "Attach a screenshot and I'll read the dynamics",
    prompt:
      "I'm going to attach a screenshot of a conversation — can you tell me what's really going on?",
  },
  {
    icon: Sparkles,
    title: "Am I chasing potential?",
    subtitle: "Words vs. actions, and which one to believe",
    prompt:
      "I think I might be dating his potential instead of who he actually is. How do I tell?",
  },
  {
    icon: Wind,
    title: "How do I regulate my anxiety right now?",
    subtitle: "Calm the spiral before you hit send",
    prompt:
      "I'm spiraling waiting for a reply and I want to double-text. How do I regulate my anxiety right now?",
  },
];

let nextId = 1;

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [isThinking, setIsThinking] = useState(false); // waiting for first token
  const [isStreaming, setIsStreaming] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const busy = isThinking || isStreaming;

  // Auto-scroll to the newest message / typing indicator. Skip the empty
  // state — scrolling it on mount shoves the welcome screen under the header.
  useEffect(() => {
    if (messages.length === 0 && !isThinking) return;
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, isThinking]);

  // Auto-grow the textarea like iMessage (1–5 lines).
  function autoGrow() {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
  }

  function addFiles(files: FileList | null) {
    if (!files) return;
    const incoming = Array.from(files).filter((f) =>
      f.type.startsWith("image/"),
    );
    setAttachments((prev) => {
      const room = MAX_IMAGES - prev.length;
      return [
        ...prev,
        ...incoming.slice(0, room).map((file) => ({
          file,
          previewUrl: URL.createObjectURL(file),
        })),
      ];
    });
  }

  function removeAttachment(url: string) {
    setAttachments((prev) => {
      const target = prev.find((a) => a.previewUrl === url);
      if (target) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((a) => a.previewUrl !== url);
    });
  }

  async function send(text: string) {
    const trimmed = text.trim();
    if (busy || (!trimmed && attachments.length === 0)) return;

    const outgoing = attachments;
    setAttachments([]);
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";

    const userMsg: Message = {
      id: nextId++,
      role: "user",
      content: trimmed,
      imageUrls: outgoing.map((a) => a.previewUrl),
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsThinking(true);

    // Text-only history keeps the payload small (images already made their point).
    const history = messages
      .filter((m) => m.content)
      .map((m) => ({ role: m.role, content: m.content }));

    const form = new FormData();
    form.append("message", trimmed);
    form.append("history", JSON.stringify(history));
    for (const a of outgoing) form.append("images", a.file, a.file.name);

    const assistantId = nextId++;
    try {
      const res = await fetch("/api/chat", { method: "POST", body: form });
      if (!res.ok || !res.body) {
        throw new Error((await res.text()) || `Request failed (${res.status})`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      setIsThinking(false);
      setIsStreaming(true);
      setMessages((prev) => [
        ...prev,
        { id: assistantId, role: "assistant", content: "" },
      ]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const delta = decoder.decode(value, { stream: true });
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId ? { ...m, content: m.content + delta } : m,
          ),
        );
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev.filter((m) => m.id !== assistantId),
        {
          id: nextId++,
          role: "assistant",
          content: `⚠ ${err instanceof Error ? err.message : "Something went wrong — try again."}`,
        },
      ]);
    } finally {
      setIsThinking(false);
      setIsStreaming(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void send(input);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(input);
    }
  }

  const empty = messages.length === 0;

  return (
    <div className="flex h-dvh flex-col bg-cream">
      {/* ---------- Sticky header ---------- */}
      <header className="pt-safe sticky top-0 z-20 border-b border-cream-deep bg-cream/90 backdrop-blur-md">
        <div className="mx-auto flex max-w-2xl items-center gap-3 px-4 py-3">
          <div className="flex size-10 items-center justify-center rounded-full bg-gradient-to-br from-rose to-rose-deep shadow-sm">
            <Heart className="size-5 fill-white text-white" />
          </div>
          <div className="min-w-0">
            <h1 className="truncate text-[17px] font-semibold leading-tight">
              The Sabrina Show AI
            </h1>
            <p className="text-[13px] leading-tight text-ink-muted">
              {busy ? "typing…" : "here for you"}
            </p>
          </div>
        </div>
      </header>

      {/* ---------- Scrollable chat area ---------- */}
      <div ref={scrollRef} className="chat-scroll flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-2xl flex-col gap-3 px-4 pb-6 pt-4">
          {empty ? (
            <EmptyState onPick={(prompt) => void send(prompt)} />
          ) : (
            messages.map((m) => <Bubble key={m.id} msg={m} />)
          )}
          {isThinking && <TypingIndicator />}
        </div>
      </div>

      {/* ---------- Bottom input bar ---------- */}
      <form
        onSubmit={onSubmit}
        className="pb-safe sticky bottom-0 z-20 border-t border-cream-deep bg-cream/90 backdrop-blur-md"
      >
        <div className="mx-auto max-w-2xl px-3 pt-2">
          {/* Attachment thumbnails */}
          {attachments.length > 0 && (
            <div className="chat-scroll mb-2 flex gap-2 overflow-x-auto pb-1">
              {attachments.map((a) => (
                <div key={a.previewUrl} className="relative shrink-0">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={a.previewUrl}
                    alt="screenshot preview"
                    className="size-16 rounded-xl border border-cream-deep object-cover"
                  />
                  <button
                    type="button"
                    aria-label="Remove screenshot"
                    onClick={() => removeAttachment(a.previewUrl)}
                    className="absolute -right-1.5 -top-1.5 flex size-5 items-center justify-center rounded-full bg-ink text-white shadow"
                  >
                    <X className="size-3" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="mb-2 flex items-end gap-2">
            {/* Attach: iOS shows Camera / Photo Library / Choose File */}
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              hidden
              onChange={(e) => {
                addFiles(e.target.files);
                e.target.value = "";
              }}
            />
            <button
              type="button"
              aria-label="Attach screenshots"
              onClick={() => fileInputRef.current?.click()}
              disabled={attachments.length >= MAX_IMAGES}
              className="mb-0.5 flex size-9 shrink-0 items-center justify-center rounded-full bg-cream-deep text-ink-muted transition active:scale-90 disabled:opacity-40"
            >
              <ImagePlus className="size-5" />
            </button>

            <textarea
              ref={textareaRef}
              value={input}
              rows={1}
              placeholder="Ask Sabrina anything…"
              enterKeyHint="send"
              onChange={(e) => {
                setInput(e.target.value);
                autoGrow();
              }}
              onKeyDown={onKeyDown}
              className="max-h-32 flex-1 resize-none rounded-3xl border border-cream-deep bg-white px-4 py-2.5 leading-snug outline-none placeholder:text-ink-muted focus:border-rose/50"
            />

            <button
              type="submit"
              aria-label="Send"
              disabled={busy || (!input.trim() && attachments.length === 0)}
              className="mb-0.5 flex size-9 shrink-0 items-center justify-center rounded-full bg-rose text-white shadow-sm transition active:scale-90 disabled:opacity-40"
            >
              <ArrowUp className="size-5" strokeWidth={2.5} />
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

/* ------------------------------------------------------------------ */

function Bubble({ msg }: { msg: Message }) {
  const isUser = msg.role === "user";
  return (
    <div
      className={`animate-bubble-in flex ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`max-w-[85%] ${isUser ? "items-end" : "items-start"} flex flex-col gap-1.5`}
      >
        {msg.imageUrls && msg.imageUrls.length > 0 && (
          <div className="flex max-w-full flex-wrap justify-end gap-1.5">
            {msg.imageUrls.map((url) => (
              /* eslint-disable-next-line @next/next/no-img-element */
              <img
                key={url}
                src={url}
                alt="attached screenshot"
                className="max-h-40 rounded-2xl border border-cream-deep object-cover"
              />
            ))}
          </div>
        )}
        {msg.content && (
          <div
            className={
              isUser
                ? "rounded-3xl rounded-br-lg bg-gradient-to-br from-rose to-rose-deep px-4 py-2.5 text-white shadow-sm"
                : "rounded-3xl rounded-bl-lg border border-cream-deep bg-white px-4 py-2.5 shadow-sm"
            }
          >
            <p className="whitespace-pre-wrap text-[15px] leading-relaxed">
              {msg.content}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="animate-bubble-in flex justify-start">
      <div className="flex items-center gap-1.5 rounded-3xl rounded-bl-lg border border-cream-deep bg-white px-4 py-3.5 shadow-sm">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="animate-typing-dot size-2 rounded-full bg-ink-muted"
            style={{ animationDelay: `${i * 0.15}s` }}
          />
        ))}
      </div>
    </div>
  );
}

function EmptyState({ onPick }: { onPick: (prompt: string) => void }) {
  return (
    <div className="flex flex-col items-center px-2 pt-10 text-center">
      <div className="flex size-20 items-center justify-center rounded-full bg-gradient-to-br from-rose to-rose-deep shadow-lg shadow-rose/25">
        <Heart className="size-10 fill-white text-white" />
      </div>
      <h2 className="mt-5 text-[22px] font-semibold">Hey, you made it. 💗</h2>
      <p className="mt-2 max-w-xs text-[15px] leading-relaxed text-ink-muted">
        Whatever's spiraling in your head right now — let's slow it down and
        look at it together. No judgment, no BS.
      </p>

      <div className="mt-8 flex w-full max-w-sm flex-col gap-3">
        {STARTERS.map(({ icon: Icon, title, subtitle, prompt }) => (
          <button
            key={title}
            onClick={() => onPick(prompt)}
            className="flex items-center gap-3 rounded-2xl border border-cream-deep bg-white p-4 text-left shadow-sm transition active:scale-[0.98]"
          >
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-rose-soft text-rose">
              <Icon className="size-5" />
            </div>
            <div className="min-w-0">
              <p className="text-[15px] font-medium leading-tight">{title}</p>
              <p className="mt-0.5 text-[13px] leading-tight text-ink-muted">
                {subtitle}
              </p>
            </div>
          </button>
        ))}
      </div>

      <p className="mt-8 text-[12px] text-ink-muted">
        Coaching-style advice, not therapy · in crisis call 988 (US)
      </p>
    </div>
  );
}
