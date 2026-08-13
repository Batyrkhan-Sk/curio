"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Button } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/icon";
import { useIsClient } from "@/hooks/use-client";
import { isTelegram } from "@/lib/telegram";

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

const DISMISSED_KEY = "curio.install-dismissed";
const READS_KEY = "curio.reads";

/**
 * The install invitation.
 *
 * Deliberately not shown on first visit. It appears only after the reader has
 * opened three cards, because asking someone to install an app they have not
 * yet found useful is the pattern the brief's "no manipulative mechanics" rule
 * is about. Dismissal is remembered for good.
 *
 * iOS never fires `beforeinstallprompt`, so Safari gets explicit instructions
 * instead — and it matters, because on iOS notifications only work once the
 * app has been added to the home screen.
 */
export function InstallPrompt() {
  const isClient = useIsClient();
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);
  const [dismissed, setDismissed] = useState(false);

  // Eligibility is a pure read of things that cannot change while the page is
  // open — already installed, already dismissed, not enough read yet. Deriving
  // it in render avoids an effect whose only job is to copy it into state.
  const eligible = isClient && !dismissed && isEligibleToPrompt();

  // iOS Safari never fires `beforeinstallprompt`, so it gets instructions
  // rather than a button. Everywhere else waits for the real event.
  const iosHint = eligible && isIosSafari();

  useEffect(() => {
    if (!eligible || iosHint) return;

    const onPrompt = (event: Event) => {
      event.preventDefault();
      setDeferred(event as BeforeInstallPromptEvent);
    };

    window.addEventListener("beforeinstallprompt", onPrompt);
    return () => window.removeEventListener("beforeinstallprompt", onPrompt);
  }, [eligible, iosHint]);

  const showIosHint = iosHint;
  const visible = eligible && (iosHint || deferred !== null);

  function dismiss() {
    localStorage.setItem(DISMISSED_KEY, "1");
    setDismissed(true);
  }

  async function install() {
    if (!deferred) return;
    await deferred.prompt();
    await deferred.userChoice;
    localStorage.setItem(DISMISSED_KEY, "1");
    setDismissed(true);
  }

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 20 }}
          transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
          className="fixed inset-x-4 bottom-20 z-50 mx-auto max-w-sm rounded-2xl border border-border bg-surface p-4 shadow-[--shadow-lift] md:bottom-6 md:left-auto md:right-6 md:mx-0"
          role="dialog"
          aria-label="Install Curio"
        >
          <div className="flex items-start gap-3">
            <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent-text">
              <Icon name="Download" className="size-4" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-[14px] font-semibold text-text">
                Keep Curio on your home screen
              </p>
              {showIosHint ? (
                <p className="mt-1 text-[13px] leading-relaxed text-text-secondary">
                  Tap <Icon name="Share" className="inline size-3.5 align-[-2px]" />{" "}
                  Share, then <strong className="font-medium">Add to Home Screen</strong>.
                  Notifications need this step on iPhone.
                </p>
              ) : (
                <p className="mt-1 text-[13px] leading-relaxed text-text-secondary">
                  Read offline, and get one gentle notification a day at most.
                </p>
              )}

              <div className="mt-3 flex gap-2">
                {!showIosHint && (
                  <Button size="sm" variant="primary" onClick={install}>
                    Install
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={dismiss}>
                  {showIosHint ? "Got it" : "Not now"}
                </Button>
              </div>
            </div>
            <button
              onClick={dismiss}
              aria-label="Dismiss"
              className="-mr-1 -mt-1 grid size-7 place-items-center rounded-lg text-text-faint hover:bg-surface-2 hover:text-text"
            >
              <Icon name="X" className="size-3.5" />
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function isEligibleToPrompt(): boolean {
  try {
    if (localStorage.getItem(DISMISSED_KEY)) return false;
    // Inside Telegram there is nothing to install — the Mini App *is* the
    // installed form, and the bot is already on the reader's home screen.
    if (isTelegram()) return false;
    const standalone =
      window.matchMedia("(display-mode: standalone)").matches ||
      (window.navigator as { standalone?: boolean }).standalone === true;
    if (standalone) return false;
    return Number(localStorage.getItem(READS_KEY) ?? "0") >= 3;
  } catch {
    return false;
  }
}

function isIosSafari(): boolean {
  const ua = navigator.userAgent;
  return (
    /iphone|ipad|ipod/i.test(ua) &&
    /^((?!chrome|android|crios|fxios).)*safari/i.test(ua)
  );
}

/** Called by the card page so the prompt can wait until Curio has proved useful. */
export function countRead() {
  try {
    const reads = Number(localStorage.getItem(READS_KEY) ?? "0");
    localStorage.setItem(READS_KEY, String(reads + 1));
  } catch {
    /* ignore */
  }
}
