"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/icon";
import {
  getPushKey,
  sendTestPush,
  subscribePush,
  unsubscribePush,
  updateProfile,
} from "@/lib/api";
import {
  notifyPermissionChanged,
  useIsClient,
  useNotificationPermission,
} from "@/hooks/use-client";

/**
 * Notification opt-in.
 *
 * Permission is only ever requested from an explicit button press — never on
 * page load. A browser permission prompt the reader did not ask for is the
 * fastest way to get permanently blocked, and the brief is explicit that
 * notifications should encourage learning rather than pursue engagement.
 */
export function NotificationSettings({
  initialHour = 17,
  initialEnabled = true,
}: {
  initialHour?: number;
  initialEnabled?: boolean;
}) {
  const isClient = useIsClient();
  // Feature detection is deterministic, so it belongs in render rather than in
  // an effect that would schedule a second pass just to record the answer.
  const supported =
    isClient &&
    "Notification" in window &&
    "serviceWorker" in navigator &&
    "PushManager" in window;

  const permission = useNotificationPermission();
  const [pushRegistered, setPushRegistered] = useState(false);
  // Two independent switches: this browser having a push subscription, and the
  // reader wanting a daily card at all. Someone can keep the subscription but
  // turn the daily off, so the profile flag seeds the UI to avoid a flash of
  // the wrong button before the async subscription check resolves.
  const [dailyEnabled, setDailyEnabled] = useState(initialEnabled);
  const [serverEnabled, setServerEnabled] = useState(true);

  const subscribed = pushRegistered && dailyEnabled;
  const [hour, setHour] = useState(initialHour);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!supported) return;
    // Both of these resolve asynchronously, so the state updates land in a
    // callback rather than synchronously in the effect body.
    getPushKey()
      .then((key) => setServerEnabled(key.enabled))
      .catch(() => setServerEnabled(false));

    navigator.serviceWorker.ready
      .then((registration) => registration.pushManager.getSubscription())
      .then((subscription) => setPushRegistered(subscription !== null))
      .catch(() => {});
  }, [supported]);

  async function enable() {
    setBusy(true);
    setMessage(null);
    try {
      const result = await Notification.requestPermission();
      notifyPermissionChanged();
      if (result !== "granted") {
        setMessage("Notifications stay off. You can change this in browser settings.");
        return;
      }

      const { public_key, enabled } = await getPushKey();
      if (!enabled || !public_key) {
        setMessage(
          "The server has no VAPID keys configured, so push cannot be delivered yet.",
        );
        return;
      }

      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(public_key),
      });

      await subscribePush(subscription.toJSON() as PushSubscriptionJSON);
      await updateProfile({ notify_daily: true, notify_hour_utc: hour });
      setPushRegistered(true);
      setDailyEnabled(true);
      setMessage("Done. At most one notification a day.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Could not enable notifications.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function disable() {
    setBusy(true);
    try {
      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.getSubscription();
      if (subscription) {
        await unsubscribePush(subscription.endpoint).catch(() => {});
        await subscription.unsubscribe();
      }
      await updateProfile({ notify_daily: false });
      setPushRegistered(false);
      setDailyEnabled(false);
      setMessage(null);
    } finally {
      setBusy(false);
    }
  }

  async function changeHour(next: number) {
    setHour(next);
    await updateProfile({ notify_hour_utc: next }).catch(() => {});
  }

  async function test() {
    setBusy(true);
    try {
      const result = await sendTestPush();
      setMessage(
        result.delivered
          ? "Sent — it should arrive in a moment."
          : "Nothing was delivered. Check that this device is subscribed.",
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not send.");
    } finally {
      setBusy(false);
    }
  }

  if (!supported) {
    return (
      <p className="text-[13px] leading-relaxed text-text-muted">
        This browser cannot receive push notifications. On iPhone, add Curio to
        your home screen first — Safari only allows notifications for installed
        web apps.
      </p>
    );
  }

  return (
    <div>
      <p className="text-[13px] leading-relaxed text-text-secondary">
        One notification a day at most, and only when there is something worth
        telling you about. No streak warnings, no nudges to come back.
      </p>

      {permission === "denied" && (
        <p className="mt-3 flex items-start gap-2 text-[13px] text-caution">
          <Icon name="TriangleAlert" className="mt-0.5 size-3.5 shrink-0" />
          Notifications are blocked for this site in your browser settings.
        </p>
      )}

      {!serverEnabled && (
        <p className="mt-3 flex items-start gap-2 text-[13px] text-text-muted">
          <Icon name="Info" className="mt-0.5 size-3.5 shrink-0" />
          Push is not configured on the server. Generate VAPID keys with{" "}
          <code className="rounded bg-surface-2 px-1 font-mono text-[11px]">
            docker compose run --rm api python -m app.cli vapid
          </code>
        </p>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {subscribed ? (
          <>
            <Button variant="outline" size="sm" onClick={disable} disabled={busy}>
              <Icon name="BellOff" className="size-4" />
              Turn off
            </Button>
            <Button variant="ghost" size="sm" onClick={test} disabled={busy}>
              Send a test
            </Button>
          </>
        ) : (
          <Button
            variant="primary"
            size="sm"
            onClick={enable}
            disabled={busy || permission === "denied" || !serverEnabled}
          >
            <Icon name="Bell" className="size-4" />
            Turn on daily curiosity
          </Button>
        )}

        <label className="ml-auto flex items-center gap-2 text-[12px] text-text-muted">
          Deliver around
          <select
            value={hour}
            onChange={(event) => changeHour(Number(event.target.value))}
            className="rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-text"
          >
            {Array.from({ length: 24 }, (_, h) => (
              <option key={h} value={h}>
                {String(h).padStart(2, "0")}:00 UTC
              </option>
            ))}
          </select>
        </label>
      </div>

      {message && <p className="mt-3 text-[12px] text-text-muted">{message}</p>}
    </div>
  );
}

/**
 * VAPID keys arrive as URL-safe base64; PushManager wants raw bytes.
 */
function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const normalised = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(normalised);
  // Backed by an explicit ArrayBuffer: PushManager's BufferSource will not
  // accept the ArrayBufferLike-parameterised default.
  const output = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) output[i] = raw.charCodeAt(i);
  return output;
}
