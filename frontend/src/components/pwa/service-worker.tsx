"use client";

import { useEffect } from "react";

/**
 * Registers the service worker and applies updates without trapping the
 * reader on a stale bundle.
 *
 * Updates activate on the next navigation rather than reloading underneath
 * someone mid-paragraph — an unannounced reload in a reading app is worse
 * than being one version behind for a few minutes.
 */
export function ServiceWorkerRegistrar() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    if (process.env.NODE_ENV === "development") return;

    let registration: ServiceWorkerRegistration | undefined;

    const register = async () => {
      try {
        registration = await navigator.serviceWorker.register("/sw.js", {
          scope: "/",
        });

        registration.addEventListener("updatefound", () => {
          const installing = registration?.installing;
          if (!installing) return;
          installing.addEventListener("statechange", () => {
            if (
              installing.state === "installed" &&
              navigator.serviceWorker.controller
            ) {
              installing.postMessage({ type: "SKIP_WAITING" });
            }
          });
        });

        // Check for a new worker when the reader returns to the tab.
        document.addEventListener("visibilitychange", () => {
          if (document.visibilityState === "visible") {
            registration?.update().catch(() => {});
          }
        });
      } catch {
        // A failed registration only costs offline support; the app still works.
      }
    };

    register();
  }, []);

  return null;
}
