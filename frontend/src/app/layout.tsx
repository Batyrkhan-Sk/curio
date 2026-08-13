import type { Metadata, Viewport } from "next";
import { ThemeProvider } from "next-themes";
import "./globals.css";
import { AppShell } from "@/components/shell/app-shell";
import { ServiceWorkerRegistrar } from "@/components/pwa/service-worker";
import { TelegramBridge } from "@/components/telegram/telegram-bridge";

export const metadata: Metadata = {
  title: {
    default: "Curio — humanity's collective curiosity",
    template: "%s · Curio",
  },
  description:
    "Discover and understand the questions people keep asking. Every answer starts from plain intuition and goes as deep as you want.",
  applicationName: "Curio",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "Curio",
    statusBarStyle: "default",
  },
  formatDetection: { telephone: false },
  openGraph: {
    type: "website",
    siteName: "Curio",
    title: "Curio — humanity's collective curiosity",
    description:
      "A place for the questions people keep asking, answered from first intuition to expert detail.",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fbfaf9" },
    { media: "(prefers-color-scheme: dark)", color: "#121110" },
  ],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-dvh bg-canvas font-sans text-text antialiased">
        <ThemeProvider
          attribute="data-theme"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <AppShell>{children}</AppShell>
          <ServiceWorkerRegistrar />
          <TelegramBridge />
        </ThemeProvider>
      </body>
    </html>
  );
}
