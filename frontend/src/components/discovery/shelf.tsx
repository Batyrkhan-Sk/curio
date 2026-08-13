import Link from "next/link";
import type { FeedMode, Shelf as ShelfType } from "@/lib/types";
import { DEFAULT_MODE, withMode } from "@/lib/mode";
import { QuestionCard } from "./question-card";
import { Icon } from "@/components/ui/icon";

/**
 * A horizontally scrolling row of questions. Horizontal rather than a grid
 * because browsing curiosity should feel like flicking through a shelf, and
 * because it lets ten distinct framings of "what might interest you" coexist
 * on one page without any of them dominating.
 */
export function Shelf({
  shelf,
  index = 0,
  mode = DEFAULT_MODE,
}: {
  shelf: ShelfType;
  index?: number;
  mode?: FeedMode;
}) {
  if (!shelf.cards.length) return null;

  // "See all" has to carry the mode: the shared shelves ("five minutes",
  // "random") mean different sets under each lens, and dropping it would take
  // a reader out of the mode they chose without saying so.
  const seeAll = withMode(`/shelf/${shelf.key}`, mode);

  return (
    <section
      className="animate-rise"
      style={{ animationDelay: `${Math.min(index * 60, 300)}ms` }}
    >
      <div className="mb-3.5 flex items-end justify-between gap-4 px-5 sm:px-8">
        <div className="min-w-0">
          <h2 className="font-serif text-lg font-medium tracking-[-0.01em] text-text">
            {shelf.title}
          </h2>
          {shelf.subtitle && (
            <p className="mt-0.5 text-[13px] text-text-muted">{shelf.subtitle}</p>
          )}
        </div>
        <Link
          href={seeAll}
          className="group hidden shrink-0 items-center gap-1 text-[13px] font-medium text-text-muted transition-colors hover:text-text sm:inline-flex"
        >
          See all
          <Icon
            name="ArrowRight"
            className="size-3.5 transition-transform group-hover:translate-x-0.5"
          />
        </Link>
      </div>

      <div className="shelf-scroll scrollbar-none flex gap-4 overflow-x-auto px-5 pb-1 sm:px-8">
        {shelf.cards.map((card) => (
          <QuestionCard
            key={card.id}
            card={card}
            className="w-[280px] shrink-0 sm:w-[320px]"
          />
        ))}
        <Link
          href={seeAll}
          className="grid w-[120px] shrink-0 place-items-center rounded-[--radius-card] border border-dashed border-border text-[13px] text-text-muted transition-colors hover:border-border-strong hover:text-text"
        >
          <span className="flex flex-col items-center gap-1.5">
            <Icon name="ArrowRight" className="size-4" />
            See all
          </span>
        </Link>
      </div>
    </section>
  );
}
