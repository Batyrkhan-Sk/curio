"use client";

import { useSyncExternalStore } from "react";

/**
 * Reading browser state on mount, without `setState` inside an effect.
 *
 * The obvious version of these — `useEffect(() => setMounted(true), [])` —
 * schedules a second render every time and React 19's lint rules reject it.
 * `useSyncExternalStore` is the sanctioned way to read something that lives
 * outside React, and it gives a server snapshot for free, which is exactly
 * what hydration needs.
 */

const noopSubscribe = () => () => {};

/** False during SSR and the first render, true thereafter. */
export function useIsClient(): boolean {
  return useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false,
  );
}

// Notification.permission changes only in response to our own request, so a
// manual notify after requestPermission() is enough to keep readers in step.
const permissionListeners = new Set<() => void>();

function subscribePermission(callback: () => void) {
  permissionListeners.add(callback);
  return () => permissionListeners.delete(callback);
}

function readPermission(): NotificationPermission {
  return typeof Notification === "undefined" ? "denied" : Notification.permission;
}

export function notifyPermissionChanged(): void {
  for (const listener of permissionListeners) listener();
}

export function useNotificationPermission(): NotificationPermission {
  return useSyncExternalStore(
    subscribePermission,
    readPermission,
    () => "default" as NotificationPermission,
  );
}

/** Tracks navigator.onLine as a real subscription rather than a mount effect. */
function subscribeOnline(callback: () => void) {
  window.addEventListener("online", callback);
  window.addEventListener("offline", callback);
  return () => {
    window.removeEventListener("online", callback);
    window.removeEventListener("offline", callback);
  };
}

export function useIsOnline(): boolean {
  return useSyncExternalStore(
    subscribeOnline,
    () => navigator.onLine,
    () => true,
  );
}
