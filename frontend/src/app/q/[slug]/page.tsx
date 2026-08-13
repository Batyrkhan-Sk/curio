import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { getCard } from "@/lib/api";
import { ApiError } from "@/lib/api";
import { LevelReader } from "@/components/card/level-reader";
import { CardActions, ReadingTracker } from "@/components/card/card-actions";
import {
  Contradictions,
  History,
  Misconceptions,
  NextSteps,
  QuestionOrigin,
  Sources,
  WhyItMatters,
} from "@/components/card/sections";
import { Glossary } from "@/components/card/glossary";
import { QuestionCard } from "@/components/discovery/question-card";
import { Badge, SectionLabel } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/icon";
import { categoryAccent, formatMinutes } from "@/lib/utils";

export const revalidate = 60;

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  try {
    const card = await getCard(slug);
    return {
      title: card.title,
      description: card.one_sentence_answer,
      openGraph: {
        title: card.title,
        description: card.one_sentence_answer,
        type: "article",
      },
    };
  } catch {
    return { title: "Question not found" };
  }
}

export default async function CardPage({ params }: Props) {
  const { slug } = await params;

  let card;
  try {
    card = await getCard(slug);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  const accent = categoryAccent(card.category?.accent);

  return (
    <article className="mx-auto max-w-6xl px-5 py-8 sm:px-8">
      <ReadingTracker cardId={card.id} />

      <nav className="mb-6 flex items-center gap-2 text-[12px] text-text-muted">
        <Link href="/" className="hover:text-text">
          Discover
        </Link>
        <Icon name="ChevronRight" className="size-3 text-text-faint" />
        {card.category && (
          <Link
            href={`/categories/${card.category.slug}`}
            className="hover:text-text"
          >
            {card.category.name}
          </Link>
        )}
      </nav>

      {/* Two columns from large screens up: the explanation reads at a
          comfortable measure on the left, while the rail beside the title
          holds what a reader checks rather than reads — the sources, and the
          card's own vocabulary behind a button. Below lg it all stacks. */}
      <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_17rem] lg:items-start lg:gap-12">
        <div className="min-w-0">
          <header>
            <h1 className="font-serif text-[30px] font-medium leading-[1.18] tracking-[-0.02em] text-text sm:text-[38px]">
              {card.title}
            </h1>

            {/* The one-sentence answer is set apart deliberately: a reader who
            reads nothing else should still leave knowing the answer. */}
            <p
              className="mt-5 border-l-2 pl-5 text-[19px] leading-relaxed text-text"
              style={{ borderColor: accent }}
            >
              {card.one_sentence_answer}
            </p>

            <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2 text-[12px] text-text-muted">
              <span className="inline-flex items-center gap-1.5">
                <Icon name="Clock" className="size-3.5" />
                {formatMinutes(card.reading_minutes)}
              </span>
              {card.origin === "ingested" && (
                <Badge tone="outline">Discovered from public discussion</Badge>
              )}
            </div>

            <div className="mt-5">
              <CardActions card={card} />
            </div>
          </header>

          <hr className="my-9 border-t border-border" />

          <LevelReader card={card} />

          <Misconceptions card={card} />
          <WhyItMatters card={card} />
          <History card={card} />
          <Contradictions card={card} />
          <NextSteps card={card} />
          <QuestionOrigin card={card} />
        </div>

        <aside className="mt-12 space-y-6 lg:sticky lg:top-6 lg:mt-0">
          <Sources card={card} />
          <Glossary card={card} />
        </aside>
      </div>

      {card.related.length > 0 && (
        <section className="mt-14">
          <div className="mb-4 flex items-baseline justify-between gap-4">
            <SectionLabel>Where curiosity goes next</SectionLabel>
            <Link
              href={`/graph?from=${card.slug}`}
              className="inline-flex items-center gap-1 text-[12px] font-medium text-text-muted hover:text-text"
            >
              <Icon name="Waypoints" className="size-3.5" />
              See the map
            </Link>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {card.related.slice(0, 4).map((related) => (
              <div key={related.id}>
                <QuestionCard card={related} size="sm" />
                {related.reason && (
                  <p className="mt-1.5 px-1 text-[11px] text-text-faint">
                    {related.reason}
                  </p>
                )}
              </div>
            ))}
          </div>
        </section>
      )}
    </article>
  );
}
