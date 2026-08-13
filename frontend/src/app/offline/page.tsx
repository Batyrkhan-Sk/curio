import Link from "next/link";
import { Icon } from "@/components/ui/icon";

export const metadata = { title: "Offline" };

export default function OfflinePage() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center px-5 py-24 text-center">
      <span className="grid size-12 place-items-center rounded-2xl bg-surface-2 text-text-muted">
        <Icon name="WifiOff" className="size-5" />
      </span>
      <h1 className="mt-5 font-serif text-xl font-medium">You&rsquo;re offline</h1>
      <p className="mt-2 text-sm leading-relaxed text-text-secondary">
        This page hasn&rsquo;t been downloaded. Anything you saved is still
        readable, and so is anything you&rsquo;ve already opened.
      </p>
      <Link
        href="/saved"
        className="mt-6 inline-flex h-10 items-center gap-2 rounded-xl bg-text px-4 text-sm font-medium text-canvas"
      >
        <Icon name="Bookmark" className="size-4" />
        Open saved cards
      </Link>
    </div>
  );
}
