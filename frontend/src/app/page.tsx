import Link from "next/link";
import { cookies } from "next/headers";
import { Suspense } from "react";
import { getFeed } from "@/lib/api";
import { MODE_COOKIE, resolveMode, withMode } from "@/lib/mode";
import type { FeedMode } from "@/lib/types";
import { Shelf } from "@/components/discovery/shelf";
import { ModeSwitch } from "@/components/discovery/mode-switch";
import { Icon } from "@/components/ui/icon";
import { EmptyState, Skeleton } from "@/components/ui/primitives";

type Props = { searchParams: Promise<{ mode?: string }> };

const COPY: Record<FeedMode, { heading: string; blurb: string }> = {
  interesting: {
    heading: "The questions people keep asking, properly answered.",
    blurb:
      "Not a search engine. Curio collects the curiosity that keeps resurfacing across the internet, checks it against real sources, and explains it from plain intuition down to expert detail.",
  },
  useful: {
    heading: "The answers worth knowing before you need them.",
    blurb:
      "The same explanations, narrowed to the ones with consequences — what to do about a pan fire, why a phishing email works, where the money actually goes. Read them on a quiet afternoon, not in an emergency.",
  },
};

export default async function HomePage({ searchParams }: Props) {
  const { mode: requested } = await searchParams;
  // The URL wins; the cookie is only consulted when the reader has not asked
  // for a mode in this navigation.
  const remembered = (await cookies()).get(MODE_COOKIE)?.value;
  const mode = resolveMode(requested ?? remembered);

  return (
    <div className="mx-auto max-w-6xl py-8">
      <Hero mode={mode} />
      <Suspense key={mode} fallback={<FeedSkeleton />}>
        <Feed mode={mode} />
      </Suspense>
    </div>
  );
}

function Hero({ mode }: { mode: FeedMode }) {
  const copy = COPY[mode];
  return (
    <header className="mb-10 px-5 sm:px-8">
      <ModeSwitch mode={mode} />
      <h1 className="mt-5 max-w-2xl font-serif text-[28px] font-medium leading-[1.2] tracking-[-0.02em] text-text sm:text-[34px]">
        {copy.heading}
      </h1>
      <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-text-secondary">
        {copy.blurb}
      </p>
      <div className="mt-5 flex flex-wrap items-center gap-2">
        <Link
          href={withMode("/random", mode)}
          className="inline-flex h-10 items-center gap-2 rounded-xl bg-text px-4 text-sm font-medium text-canvas transition-opacity hover:opacity-90"
        >
          <Icon name="Shuffle" className="size-4" />
          {mode === "useful" ? "Something useful" : "Surprise me"}
        </Link>
        <Link
          href="/categories"
          className="inline-flex h-10 items-center gap-2 rounded-xl border border-border px-4 text-sm font-medium text-text transition-colors hover:border-border-strong hover:bg-surface-2"
        >
          Browse by subject
        </Link>
      </div>
    </header>
  );
}

async function Feed({ mode }: { mode: FeedMode }) {
  let feed;
  try {
    feed = await getFeed(8, mode);
  } catch {
    return (
      <div className="px-5 sm:px-8">
        <EmptyState
          title="Can't reach the library right now"
          description="The API isn't responding. If you're running this locally, check that the api container is up."
        />
      </div>
    );
  }

  if (!feed.shelves.length) {
    return (
      <div className="px-5 sm:px-8">
        <EmptyState
          title={mode === "useful" ? "Nothing practical yet" : "No cards yet"}
          description={
            mode === "useful"
              ? "The library has no cards with practical stakes so far. Switch to Interesting, or run a discovery pass to bring more in."
              : "Seed the curated corpus with: docker compose run --rm api python -m app.cli seed"
          }
        />
      </div>
    );
  }

  return (
    <div className="space-y-12">
      {feed.shelves.map((shelf, index) => (
        <Shelf key={shelf.key} shelf={shelf} index={index} mode={mode} />
      ))}
    </div>
  );
}

function FeedSkeleton() {
  return (
    <div className="space-y-12">
      {[0, 1, 2].map((row) => (
        <div key={row}>
          <div className="mb-4 px-5 sm:px-8">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="mt-2 h-3.5 w-72" />
          </div>
          <div className="flex gap-4 px-5 sm:px-8">
            {[0, 1, 2, 3].map((col) => (
              <Skeleton key={col} className="h-44 w-[280px] shrink-0 sm:w-[320px]" />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
