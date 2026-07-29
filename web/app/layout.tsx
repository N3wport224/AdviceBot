import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "The Sabrina Show AI",
  description:
    "Dating & relationship advice in Sabrina Zohar's coaching style — no-BS, empathetic, nervous-system-regulated.",
  manifest: "/manifest.json",
  // iOS "Add to Home Screen" → full-screen standalone app, no Safari chrome.
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Sabrina AI",
  },
  icons: {
    icon: "/icons/icon-192.png",
    apple: "/icons/apple-touch-icon.png",
  },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false, // chat UI — pinch-zoom fights the native feel
  viewportFit: "cover", // lets us pad into the notch/home-indicator safe areas
  themeColor: "#faf6f1",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
