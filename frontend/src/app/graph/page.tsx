import Link from "next/link";
import { getCardGraph, getRandomCard, listCards } from "@/lib/api";
import { KnowledgeGraph } from "@/components/graph/knowledge-graph";
import { EmptyState } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/icon";

export const revalidate = 300;

export const metadata = {
  title: "Knowledge graph",
  description: "How the questions connect to each other.",
};

type Props = { searchParams: Promise<{ from?: string; depth?: string }> };

export default async function GraphPage({ searchParams }: Props) {
  const { from, depth } = await searchParams;

  let rootSlug = from;
  if (!rootSlug) {
    // No anchor given — start from the most-asked question, which tends to sit
    // near the middle of the graph and gives the best first view.
    try {
      const cards = await listCards({ limit: 1, sort: "curiosity" });
      rootSlug = cards[0]?.slug;
    } catch {
      rootSlug = undefined;
    }
  }

  if (!rootSlug) {
    return (
      <div className="mx-auto max-w-5xl px-5 py-8 sm:px-8">
        <EmptyState
          title="Nothing to map yet"
          description="The graph is built from connections between cards, so it appears once there are cards to connect."
        />
      </div>
    );
  }

  const data = await getCardGraph(rootSlug, Number(depth) || 2);
  const root = data.nodes.find((n) => n.depth === 0);

  return (
    <div className="mx-auto max-w-5xl px-5 py-8 sm:px-8">
      <header className="mb-6">
        <h1 className="font-serif text-2xl font-medium tracking-[-0.01em]">
          How this connects
        </h1>
        <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-text-secondary">
          Questions are linked when they share an underlying concept or when one
          naturally leads to the other. Following the links is how a five-minute
          visit becomes an hour.
        </p>
        {root && (
          <p className="mt-3 inline-flex items-center gap-2 text-[13px] text-text-muted">
            <Icon name="Crosshair" className="size-3.5 text-accent" />
            Centred on{" "}
            <Link href={`/q/${root.slug}`} className="font-medium text-text hover:underline">
              {root.label}
            </Link>
          </p>
        )}
      </header>

      <KnowledgeGraph data={data} rootSlug={rootSlug} />

      <div className="mt-8 flex flex-wrap gap-2">
        <Link
          href={`/graph?from=${rootSlug}&depth=${Number(depth) === 3 ? 2 : 3}`}
          className="inline-flex h-9 items-center gap-2 rounded-lg border border-border px-3 text-[13px] font-medium transition-colors hover:border-border-strong hover:bg-surface-2"
        >
          <Icon name="Expand" className="size-3.5" />
          {Number(depth) === 3 ? "Show less" : "Reach further out"}
        </Link>
        <Link
          href="/random"
          className="inline-flex h-9 items-center gap-2 rounded-lg border border-border px-3 text-[13px] font-medium transition-colors hover:border-border-strong hover:bg-surface-2"
        >
          <Icon name="Shuffle" className="size-3.5" />
          Re-centre somewhere else
        </Link>
      </div>
    </div>
  );
}
