"use client";

import Script from "next/script";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTheme } from "next-themes";
import { readProfileKey, writeProfileKey } from "@/lib/api";
import {
  TELEGRAM_SDK_URL,
  telegramWebApp,
  type MiniAppSession,
} from "@/lib/telegram";

/**
 * Makes the ordinary web app behave when it is opened inside Telegram.
 *
 * Four jobs, none of which the reading UI should have to know about:
 *
 * 1. **Identity.** The webview arrives with a signed `initData` blob. It is
 *    exchanged once for the reader's Curio profile key, so a card saved in a
 *    chat message is already saved here — same reader, two surfaces.
 * 2. **Theme.** Telegram has its own light/dark switch, and an app that
 *    ignores it looks broken next to every other Mini App.
 * 3. **Navigation.** Telegram's own back button replaces the browser's, which
 *    the webview does not show.
 * 4. **Gestures.** A vertical swipe closes a Mini App by default. In something
 *    you scroll through to read, that is a trapdoor.
 *
 * Outside Telegram every one of these is a no-op: the SDK script still loads
 * but `initData` is empty, `telegramWebApp()` returns null, and the component
 * renders nothing.
 */
export function TelegramBridge() {
  const [sdkReady, setSdkReady] = useState(false);
  const { setTheme } = useTheme();
  const router = useRouter();
  const pathname = usePathname();
  // The exchange is once per page load, not once per navigation, and React
  // strict mode mounts effects twice in development.
  const authenticated = useRef(false);

  const authenticate = useCallback(
    async (initData: string) => {
      if (authenticated.current) return;
      authenticated.current = true;

      try {
        const response = await fetch("/api/v1/telegram/auth", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            init_data: initData,
            // Hand over whatever anonymous profile this browser already had.
            // The server adopts it on first sign-in, so a reader who used the
            // web app before opening it in Telegram keeps their history
            // instead of silently starting again.
            profile_key: readProfileKey(),
          }),
        });

        if (!response.ok) {
          // A failed exchange is not fatal: the app keeps working as an
          // anonymous reader, which is exactly what it does on the web.
          console.warn("Telegram sign-in failed:", response.status);
          return;
        }

        const session: MiniAppSession = await response.json();
        if (session.profile_key && session.profile_key !== readProfileKey()) {
          writeProfileKey(session.profile_key);
          // Anything already fetched belongs to the previous identity.
          router.refresh();
        }
      } catch (error) {
        console.warn("Telegram sign-in failed:", error);
      }
    },
    [router],
  );

  useEffect(() => {
    if (!sdkReady) return;
    const app = telegramWebApp();
    if (!app) return;

    app.ready();
    app.expand();
    app.disableVerticalSwipes?.();

    // Lets CSS reserve room for Telegram's chrome without guessing at the
    // platform from the user agent.
    document.documentElement.dataset.telegram = app.platform || "1";

    const applyTheme = () => setTheme(app.colorScheme === "dark" ? "dark" : "light");
    applyTheme();
    app.onEvent("themeChanged", applyTheme);

    void authenticate(app.initData);

    return () => app.offEvent("themeChanged", applyTheme);
  }, [sdkReady, setTheme, authenticate]);

  // Telegram's back button, wired to the router. The webview has no browser
  // chrome, so without this the only way out of a card is closing the app.
  useEffect(() => {
    if (!sdkReady) return;
    const back = telegramWebApp()?.BackButton;
    if (!back) return;

    const onClick = () => router.back();

    if (pathname === "/") {
      back.hide();
    } else {
      back.show();
      back.onClick(onClick);
    }

    return () => {
      back.offClick(onClick);
    };
  }, [sdkReady, pathname, router]);

  return (
    <Script
      src={TELEGRAM_SDK_URL}
      strategy="afterInteractive"
      onReady={() => setSdkReady(true)}
    />
  );
}
