# Sabrina Show AI — iOS-feel web app (PWA)

Mobile-first Next.js chat app for the Sabrina Zohar advice bot: iMessage-style
bubbles, screenshot attachments from the iPhone camera roll, streamed replies,
and full-screen "Add to Home Screen" support.

## Run it

```bash
cd web
npm install
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env.local   # optional — mock replies without it
npm run dev
```

Open http://localhost:3000. Without an API key the `/api/chat` route streams a
clearly-labeled mock reply, so the whole UI is testable offline.

## Install on your iPhone

1. Deploy (Vercel is the one-click path: `npx vercel`, set `ANTHROPIC_API_KEY`
   in the project's environment variables) or run `npm run dev` on your Mac and
   open your computer's local IP on the phone.
2. Open the URL in **Safari** → tap **Share** → **Add to Home Screen**.
3. Launch from the icon: full-screen standalone app, no URL bar, safe-area
   aware around the notch and home indicator.

> ⚠️ Keep this deployment private (or add auth) — anyone with the URL can chat
> on your API key's dime.

## Layout

```
web/
├── app/
│   ├── layout.tsx        # PWA/iOS metadata (manifest, apple-web-app, viewport-fit)
│   ├── globals.css       # Tailwind v4 theme, safe-area utilities, animations
│   ├── page.tsx          # Chat UI: header, bubbles, starters, input bar
│   └── api/chat/route.ts # FormData in → Claude (or mock) streamed text out
├── lib/prompt.ts         # Sabrina persona system prompt (mirrors advisor/prompts.py)
└── public/
    ├── manifest.json     # standalone display, theme color, icons
    └── icons/            # 192/512 PWA icons + apple-touch-icon
```
