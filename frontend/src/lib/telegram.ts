/**
 * The slice of the Telegram Mini App SDK this app actually uses.
 *
 * Typed by hand rather than pulled from a package: the official types ship as
 * a whole framework, and what is needed here is a webview lifecycle, a theme,
 * and a back button.
 */

export interface TelegramWebApp {
  /** Signed launch payload. Empty in an ordinary browser — this is the check
   *  for "are we actually inside Telegram". */
  initData: string;
  initDataUnsafe?: {
    user?: {
      id: number;
      first_name?: string;
      last_name?: string;
      username?: string;
      language_code?: string;
    };
    start_param?: string;
  };
  version: string;
  platform: string;
  colorScheme: "light" | "dark";
  themeParams?: Record<string, string>;
  isExpanded: boolean;
  viewportStableHeight?: number;
  safeAreaInset?: { top: number; bottom: number; left: number; right: number };

  ready: () => void;
  expand: () => void;
  close: () => void;
  onEvent: (event: string, handler: () => void) => void;
  offEvent: (event: string, handler: () => void) => void;
  /** 7.7+. Without it, a downward scroll near the top closes the app — which
   *  in a reading app is the single most disruptive thing that can happen. */
  disableVerticalSwipes?: () => void;
  BackButton?: {
    isVisible: boolean;
    show: () => void;
    hide: () => void;
    onClick: (handler: () => void) => void;
    offClick: (handler: () => void) => void;
  };
  HapticFeedback?: {
    impactOccurred: (style: "light" | "medium" | "heavy") => void;
    selectionChanged: () => void;
  };
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

export const TELEGRAM_SDK_URL = "https://telegram.org/js/telegram-web-app.js";

/** The live WebApp object, or null when this is a normal browser tab. */
export function telegramWebApp(): TelegramWebApp | null {
  if (typeof window === "undefined") return null;
  const app = window.Telegram?.WebApp;
  // `initData` is empty when the SDK is present but the page was not launched
  // from Telegram — loading the script does not mean we are inside the client.
  return app && app.initData ? app : null;
}

export function isTelegram(): boolean {
  return telegramWebApp() !== null;
}

export interface MiniAppSession {
  profile_key: string;
  display_name: string;
  telegram_id: number;
  username: string;
  streak_days: number;
  preferred_level: number;
}
