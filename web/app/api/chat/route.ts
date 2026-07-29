import Anthropic from "@anthropic-ai/sdk";
import { SABRINA_SYSTEM_PROMPT } from "@/lib/prompt";

export const runtime = "nodejs"; // buffer image uploads; edge has stricter limits
export const maxDuration = 60;

// claude-3-5-sonnet was retired Oct 2025 — claude-sonnet-5 is its replacement.
const MODEL = process.env.ANTHROPIC_MODEL ?? "claude-sonnet-5";
const MAX_IMAGES = 10;
const MAX_TOKENS = 1024;

const IMAGE_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
]);

type HistoryMessage = { role: "user" | "assistant"; content: string };

/**
 * POST /api/chat
 * Receives FormData:
 *   - message: string (may be empty when only screenshots are sent)
 *   - history: JSON string of prior {role, content} text messages
 *   - images:  up to 10 image Files (iPhone camera or camera roll)
 * Streams back plain-text chunks of Sabrina's reply.
 */
export async function POST(req: Request) {
  const form = await req.formData();
  const message = ((form.get("message") as string) ?? "").trim();
  const images = (form.getAll("images") as File[]).filter((f) =>
    IMAGE_TYPES.has(f.type),
  );

  let history: HistoryMessage[] = [];
  try {
    history = JSON.parse((form.get("history") as string) ?? "[]");
  } catch {
    history = [];
  }

  if (!message && images.length === 0) {
    return new Response("Send a question, screenshots, or both.", {
      status: 400,
    });
  }
  if (images.length > MAX_IMAGES) {
    return new Response(`Max ${MAX_IMAGES} screenshots per message.`, {
      status: 400,
    });
  }

  // --- Build the user content: numbered screenshots first, then the text ---
  const content: Anthropic.ContentBlockParam[] = [];
  for (let i = 0; i < images.length; i++) {
    if (images.length > 1) {
      content.push({
        type: "text",
        text: `Screenshot ${i + 1} of ${images.length}:`,
      });
    }
    const bytes = Buffer.from(await images[i].arrayBuffer());
    content.push({
      type: "image",
      source: {
        type: "base64",
        media_type: images[i].type as
          | "image/png"
          | "image/jpeg"
          | "image/gif"
          | "image/webp",
        data: bytes.toString("base64"),
      },
    });
  }
  content.push({
    type: "text",
    text:
      message ||
      "Here are screenshots of a conversation I'm in. What's really going on here, and what should I do?",
  });

  const messages: Anthropic.MessageParam[] = [
    ...history.map((m) => ({ role: m.role, content: m.content })),
    { role: "user" as const, content },
  ];

  // --- No API key? Stream a mock reply so the UI is fully testable. ---
  if (!process.env.ANTHROPIC_API_KEY) {
    return mockStream(
      "Okay, real talk? I can't actually read this yet — the server is missing " +
        "its ANTHROPIC_API_KEY, so this is a demo reply. But notice what you " +
        "did: you reached out for clarity instead of spiraling alone. That's " +
        "the regulated move. Add the key in .env.local and ask me again. 💗",
    );
  }

  // --- Real call: stream Sabrina's reply token-by-token ---
  const client = new Anthropic(); // reads ANTHROPIC_API_KEY
  const encoder = new TextEncoder();

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      try {
        const anthropicStream = client.messages.stream({
          model: MODEL,
          max_tokens: MAX_TOKENS,
          system: [
            {
              type: "text",
              text: SABRINA_SYSTEM_PROMPT,
              // Stable persona prefix — cheap on repeat requests.
              cache_control: { type: "ephemeral" },
            },
          ],
          messages,
        });

        anthropicStream.on("text", (delta) => {
          controller.enqueue(encoder.encode(delta));
        });

        const final = await anthropicStream.finalMessage();
        if (final.stop_reason === "refusal") {
          controller.enqueue(
            encoder.encode(
              "I can't help with that one — if you're dealing with a safety " +
                "issue, please reach out to a professional or a crisis line " +
                "(988 in the US).",
            ),
          );
        }
        controller.close();
      } catch (err) {
        const msg =
          err instanceof Anthropic.APIError
            ? `The advice line hit a snag (${err.status ?? "network"}). Try again in a moment.`
            : "The advice line hit a snag. Try again in a moment.";
        controller.enqueue(encoder.encode(msg));
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

/** Word-by-word mock stream so the typing UI can be exercised without a key. */
function mockStream(text: string): Response {
  const encoder = new TextEncoder();
  const words = text.split(" ");
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      for (const [i, word] of words.entries()) {
        controller.enqueue(encoder.encode(i === 0 ? word : ` ${word}`));
        await new Promise((r) => setTimeout(r, 40));
      }
      controller.close();
    },
  });
  return new Response(stream, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}
