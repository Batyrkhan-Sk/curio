"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Icon } from "@/components/ui/icon";
import { ThemeToggle } from "./theme-toggle";
import { CommandMenu } from "./command-menu";
import { InstallPrompt } from "@/components/pwa/install-prompt";
import { OfflineBanner } from "@/components/pwa/offline-banner";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Discover", icon: "Compass" },
  { href: "/categories", label: "Categories", icon: "LayoutGrid" },
  { href: "/graph", label: "Graph", icon: "Waypoints" },
  { href: "/incoming", label: "Incoming", icon: "Inbox" },
  { href: "/saved", label: "Saved", icon: "Bookmark" },
  { href: "/you", label: "You", icon: "CircleUser" },
] as const;

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [commandOpen, setCommandOpen] = useState(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setCommandOpen((open) => !open);
      }
      // Bare "/" is the convention readers expect from a text-heavy site.
      if (
        event.key === "/" &&
        !["INPUT", "TEXTAREA"].includes((event.target as HTMLElement)?.tagName)
      ) {
        event.preventDefault();
        setCommandOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <div className="flex min-h-dvh flex-col">
      <OfflineBanner />

      <header className="sticky top-0 z-40 border-b border-border bg-canvas/85 backdrop-blur-xl">
        {/* Three tracks: the logo and the actions each take an equal share of
            the leftover width, which parks the nav dead centre regardless of
            how wide either side happens to be. */}
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-2 px-5 sm:px-8">
          <div className="flex flex-1 items-center">
            <Link href="/" className="flex items-center gap-2">
              <span className="grid size-7 place-items-center rounded-lg bg-accent-soft text-accent-text">
                <Icon name="Sparkle" className="size-4" />
              </span>
              <span className="font-serif text-[17px] font-semibold tracking-[-0.01em]">
                Curio
              </span>
            </Link>
          </div>

          <nav className="hidden items-center gap-0.5 md:flex">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-[13px] font-medium transition-colors",
                  isActive(item.href)
                    ? "bg-surface-2 text-text"
                    : "text-text-muted hover:bg-surface-2 hover:text-text",
                )}
              >
                {item.label}
              </Link>
            ))}
          </nav>

          <div className="flex flex-1 items-center justify-end gap-1.5">
            <button
              onClick={() => setCommandOpen(true)}
              className="flex h-9 items-center gap-2 rounded-lg border border-border px-3 text-[13px] text-text-muted transition-colors hover:border-border-strong hover:text-text"
              aria-label="Search"
            >
              <Icon name="Search" className="size-3.5" />
              <span className="hidden sm:inline">Search</span>
              <kbd className="ml-2 hidden rounded border border-border bg-surface-2 px-1.5 py-0.5 font-sans text-[10px] text-text-faint sm:inline">
                ⌘K
              </kbd>
            </button>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="flex-1 pb-24 md:pb-12">{children}</main>

      {/* Bottom navigation is the installed-app affordance; on desktop the
          header nav does the same job. */}
      <nav className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-canvas/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl md:hidden">
        <div className="flex items-stretch">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex flex-1 flex-col items-center gap-0.5 py-2.5 text-[10px] font-medium transition-colors",
                isActive(item.href) ? "text-accent" : "text-text-faint",
              )}
            >
              <Icon name={item.icon} className="size-5" />
              {item.label}
            </Link>
          ))}
        </div>
      </nav>

      <footer className="hidden border-t border-border px-5 py-8 sm:px-8 md:block">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 text-[12px] text-text-faint">
          <p>
            Curio indexes questions, not pages. Every card is synthesised from
            multiple sources and shows its confidence.
          </p>
          <Link href="/about" className="hover:text-text-secondary">
            How this works
          </Link>
        </div>
      </footer>

      {/* Unmounted rather than hidden: closing it should forget the query,
          and letting React discard the state is cleaner than resetting it. */}
      {commandOpen && <CommandMenu onClose={() => setCommandOpen(false)} />}
      <InstallPrompt />
    </div>
  );
}
