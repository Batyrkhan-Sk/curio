import Link from "next/link";
import { redirect } from "next/navigation";
import { getDiscoveryQueue } from "@/lib/api";
import { Badge, Card, EmptyState, SectionLabel } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/icon";

export const revalidate = 60;

export const metadata = {
  title: "Incoming curiosity",
  description:
    "The raw questions Curio has collected from public discussion, before any of them become cards.",
};

type Props = { searchParams: Promise<{ status?: string; page?: string }> };

const PAGE_SIZE = 120;

const FILTERS = [
  { key: "all", label: "Everything found" },
  { key: "pending", label: "Waiting on triage" },
  { key: "published", label: "Became a card" },
  { key: "rejected", label: "Rejected" },
] as const;

const SOURCE_LABELS: Record<string, string> = {
  hackernews: "Hacker News",
  reddit: "Reddit",
};

function sourceLabel(name: string): string {
  if (SOURCE_LABELS[name]) return SOURCE_LABELS[name];
  if (name.startsWith("stackexchange:")) {
    return `Stack Exchange · ${name.split(":")[1]}`;
  }
  return name;
}

export default async function IncomingPage({ searchParams }: Props) {
  const { status = "all", page: rawPage } = await searchParams;
  // The pool runs to four figures, so the list has to be paged. Without this
  // the page showed the first 120 and silently pretended the rest of what the
  // platform had collected did not exist.
  const page = Math.max(1, Number(rawPage) || 1);

  let queue;
  try {
    queue = await getDiscoveryQueue(status, PAGE_SIZE, (page - 1) * PAGE_SIZE);
  } catch {
    return (
      <div className="mx-auto max-w-4xl px-5 py-8 sm:px-8">
        <EmptyState title="Can't reach the pipeline right now" />
      </div>
    );
  }

  // How many questions the active filter matches, so the pager knows where the
  // list ends. The queue reports each bucket's size alongside the page itself.
  const matching =
    status === "pending"
      ? queue.pending
      : status === "published"
        ? queue.published
        : status === "rejected"
          ? queue.rejected
          : queue.total;
  const totalPages = Math.max(1, Math.ceil(matching / PAGE_SIZE));
  // A hand-typed page past the end would otherwise render "Page 99 of 10"
  // above an empty list, with a range running past the total.
  if (page > totalPages) {
    redirect(`/incoming?status=${status}&page=${totalPages}`);
  }
  const rangeFrom = matching ? (page - 1) * PAGE_SIZE + 1 : 0;
  const rangeTo = Math.min(page * PAGE_SIZE, matching);
  const hasNext = page < totalPages && queue.items.length > 0;

  return (
    <div className="mx-auto max-w-4xl px-5 py-8 sm:px-8">
      <header className="mb-7">
        <h1 className="font-serif text-2xl font-medium tracking-[-0.01em]">
          Incoming curiosity
        </h1>
        <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-text-secondary">
          Everything below was asked by a real person somewhere public. This is
          the raw input to the pipeline, before anything has been judged,
          verified, or written up — and most of it never will be. Showing it is
          the honest way to represent what indexing curiosity actually involves.
        </p>
      </header>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Questions found" value={queue.total} icon="Inbox" />
        <Stat label="Waiting on triage" value={queue.pending} icon="Hourglass" />
        <Stat label="Asked more than once" value={queue.repeated} icon="Repeat" />
        <Stat label="Became cards" value={queue.published} icon="FileText" />
      </div>

      {!queue.llm_enabled && (
        <div className="mt-5 flex items-start gap-3 rounded-[--radius-card] border border-border bg-surface-2/50 p-4">
          <Icon name="Info" className="mt-0.5 size-4 shrink-0 text-caution" />
          <div className="min-w-0">
            <p className="text-[13px] font-medium text-text">
              Nothing can leave this queue yet.
            </p>
            <p className="mt-1 text-[13px] leading-relaxed text-text-secondary">
              Collecting questions needs no AI. Deciding which of them deserve a
              permanent card, and then researching and writing one, does — so
              every item below is stuck at <em>waiting on triage</em> until{" "}
              <code className="rounded bg-surface-3 px-1 font-mono text-[11px]">
                GEMINI_API_KEY
              </code>{" "}
              is set. The scale is the point: {queue.total.toLocaleString()}{" "}
              found, and a good day&rsquo;s triage might keep three.
            </p>
          </div>
        </div>
      )}

      <div className="mt-6 flex flex-wrap gap-2">
        {FILTERS.map((filter) => (
          <Link
            key={filter.key}
            href={`/incoming?status=${filter.key}`}
            className={
              filter.key === status
                ? "rounded-lg bg-surface-2 px-3 py-1.5 text-[13px] font-medium text-text"
                : "rounded-lg px-3 py-1.5 text-[13px] font-medium text-text-muted transition-colors hover:bg-surface-2 hover:text-text"
            }
          >
            {filter.label}
          </Link>
        ))}
      </div>

      {queue.sources.length > 0 && (
        <section className="mt-8">
          <SectionLabel className="mb-3">Where it came from</SectionLabel>
          <div className="flex flex-wrap gap-2">
            {queue.sources.map((source) => (
              <span
                key={source.name}
                className="inline-flex items-center gap-2 rounded-lg border border-border px-2.5 py-1.5 text-[12px] text-text-secondary"
              >
                {sourceLabel(source.name)}
                <span className="tabular-nums text-text-faint">{source.count}</span>
              </span>
            ))}
          </div>
        </section>
      )}

      <section className="mt-8">
        <SectionLabel className="mb-3">
          Most repeated first
          {matching > 0 && (
            <span className="ml-2 font-normal normal-case tracking-normal text-text-faint">
              {rangeFrom.toLocaleString()}–{rangeTo.toLocaleString()} of{" "}
              {matching.toLocaleString()}
            </span>
          )}
        </SectionLabel>

        {queue.items.length ? (
          <ul className="divide-y divide-border">
            {queue.items.map((item) => (
              <li key={item.id} className="py-3.5">
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-[15px] leading-snug text-text">
                      {item.raw_text}
                    </p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-text-faint">
                      {item.source_url ? (
                        <a
                          href={item.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 hover:text-text-secondary"
                        >
                          {sourceLabel(item.source_name)}
                          <Icon name="ExternalLink" className="size-3" />
                        </a>
                      ) : (
                        <span>{sourceLabel(item.source_name)}</span>
                      )}
                      {item.occurrences > 1 && (
                        <span className="text-accent-text">
                          asked in {item.occurrences} places
                        </span>
                      )}
                      {item.engagement > 0 && (
                        <span>{item.engagement.toLocaleString()} points</span>
                      )}
                      {item.rejected_reason && (
                        <span className="italic">{item.rejected_reason}</span>
                      )}
                    </div>
                  </div>

                  {item.status === "published" && item.card_slug ? (
                    <Link href={`/q/${item.card_slug}`} className="shrink-0">
                      <Badge tone="positive">Read the card</Badge>
                    </Link>
                  ) : (
                    <Badge
                      tone={item.status === "rejected" ? "neutral" : "outline"}
                      className="shrink-0"
                    >
                      {item.status === "rejected" ? "rejected" : "waiting"}
                    </Badge>
                  )}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            title={page > 1 ? "Nothing on this page" : "Nothing here yet"}
            description={
              page > 1
                ? "You have reached the end of this list."
                : "Run a discovery pass with: docker compose run --rm api python -m app.cli ingest --discover-only"
            }
          />
        )}

        {(page > 1 || hasNext) && (
          <nav className="mt-7 flex items-center justify-between gap-3 border-t border-border pt-5">
            <PageLink
              href={`/incoming?status=${status}&page=${page - 1}`}
              disabled={page <= 1}
              icon="ArrowLeft"
            >
              Newer
            </PageLink>
            <span className="text-[13px] tabular-nums text-text-faint">
              Page {page} of {totalPages.toLocaleString()}
            </span>
            <PageLink
              href={`/incoming?status=${status}&page=${page + 1}`}
              disabled={!hasNext}
              icon="ArrowRight"
              trailing
            >
              Older
            </PageLink>
          </nav>
        )}
      </section>
    </div>
  );
}

function PageLink({
  href,
  disabled,
  icon,
  trailing = false,
  children,
}: {
  href: string;
  disabled: boolean;
  icon: string;
  trailing?: boolean;
  children: React.ReactNode;
}) {
  if (disabled) {
    return (
      <span className="inline-flex h-9 cursor-default items-center gap-1.5 rounded-lg px-3 text-[13px] font-medium text-text-faint">
        {!trailing && <Icon name={icon} className="size-3.5" />}
        {children}
        {trailing && <Icon name={icon} className="size-3.5" />}
      </span>
    );
  }
  return (
    <Link
      href={href}
      className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-border px-3 text-[13px] font-medium text-text transition-colors hover:border-border-strong hover:bg-surface-2"
    >
      {!trailing && <Icon name={icon} className="size-3.5" />}
      {children}
      {trailing && <Icon name={icon} className="size-3.5" />}
    </Link>
  );
}

function Stat({
  label,
  value,
  icon,
}: {
  label: string;
  value: number;
  icon: string;
}) {
  return (
    <Card className="p-4">
      <Icon name={icon} className="size-4 text-text-faint" />
      <p className="mt-3 text-2xl font-medium tabular-nums tracking-tight">
        {value.toLocaleString()}
      </p>
      <p className="mt-0.5 text-[11px] text-text-muted">{label}</p>
    </Card>
  );
}
