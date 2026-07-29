# Sabrina Show AI — iOS-feel web app (PWA)

Mobile-first Next.js chat app for the Sabrina Zohar advice bot: iMessage-style
bubbles, screenshot attachments from the iPhone camera roll, streamed replies,
and full-screen "Add to Home Screen" support.

## Run it

```bash
cd web
npm install
cat > .env.local <<'ENV'
ANTHROPIC_API_KEY=sk-ant-...   # optional — mock replies without it
ACCESS_PASSWORD=pick-something # optional — no lock screen when unset
ENV
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

## Password gate

Set **`ACCESS_PASSWORD`** in the deployment's environment (Vercel → Settings →
Environment Variables) and the app shows an iOS-style lock screen until the
right password is entered. How it works:

- The password is kept in `localStorage`, so Home-Screen (PWA) launches stay
  unlocked — you type it once per device.
- Every `/api/chat` call carries the password in an `x-access-password` header
  and the server verifies it (constant-time compare) before touching the
  Anthropic API — a wrong/missing password is a hard `401`, so strangers can't
  spend your key even by calling the API directly.
- Rotate the password any time: stale devices get a 401 on their next message
  and drop back to the lock screen automatically.
- Unset `ACCESS_PASSWORD` and the gate disappears (handy for local dev).

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
