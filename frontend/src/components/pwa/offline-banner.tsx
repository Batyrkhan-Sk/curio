"use client";

import { Icon } from "@/components/ui/icon";
import { useIsOnline } from "@/hooks/use-client";

/**
 * Tells the reader what still works rather than just that something is broken.
 * Saved cards are genuinely available offline, so the message points there.
 */
export function OfflineBanner() {
  const online = useIsOnline();
  if (online) return null;

  return (
    <div
      role="status"
      className="flex items-center justify-center gap-2 bg-caution/10 px-4 py-2 text-[12px] font-medium text-caution"
    >
      <Icon name="WifiOff" className="size-3.5" />
      You&rsquo;re offline. Saved cards and anything you&rsquo;ve already read
      are still available.
    </div>
  );
}
