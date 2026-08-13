import Link from "next/link";
import type { CardSummary } from "@/lib/types";
import { Badge, Card } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/icon";
import { categoryAccent, cn, formatMinutes } from "@/lib/utils";

/**
 * The unit of the whole product. The question is the headline and gets the
 * serif face; the one-sentence answer sits directly beneath it, because a
 * reader should be able to get the gist without opening anything.
 */
export function QuestionCard({
  card,
  size = "md",
  className,
}: {
  card: CardSummary;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const accent = categoryAccent(card.category?.accent);

  return (
    <Link href={`/q/${card.slug}`} className={cn("group block", className)}>
      <Card
        hover
        className={cn(
          "flex h-full flex-col",
          size === "sm" && "p-4",
          size === "md" && "p-5",
          size === "lg" && "p-6",
        )}
      >
        {card.category && (
          <div className="mb-3 flex items-center gap-2">
            <span
              className="grid size-6 shrink-0 place-items-center rounded-md"
              style={{ background: `${accent}1f`, color: accent }}
            >
              <Icon name={card.category.icon} className="size-3.5" />
            </span>
            <span className="text-[11px] font-medium uppercase tracking-[0.1em] text-text-faint">
              {card.category.name}
            </span>
          </div>
        )}

        <h3
          className={cn(
            "font-serif font-medium leading-snug tracking-[-0.01em] text-text",
            size === "sm" && "text-[15px]",
            size === "md" && "text-[17px]",
            size === "lg" && "text-xl",
          )}
        >
          {card.title}
        </h3>

        <p
          className={cn(
            "mt-2 flex-1 leading-relaxed text-text-secondary",
            size === "sm" ? "line-clamp-2 text-[13px]" : "line-clamp-3 text-sm",
          )}
        >
          {card.one_sentence_answer}
        </p>

        <div className="mt-4 flex items-center gap-3 text-[11px] text-text-faint">
          <span className="inline-flex items-center gap-1">
            <Icon name="Clock" className="size-3" />
            {formatMinutes(card.reading_minutes)}
          </span>
          {card.difficulty !== "beginner" && (
            <Badge tone="outline" className="capitalize">
              {card.difficulty}
            </Badge>
          )}
          {card.save_count > 0 && (
            <span className="inline-flex items-center gap-1">
              <Icon name="Bookmark" className="size-3" />
              {card.save_count}
            </span>
          )}
          <Icon
            name="ArrowUpRight"
            className="ml-auto size-3.5 text-text-faint transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-text-secondary"
          />
        </div>
      </Card>
    </Link>
  );
}

/** A denser variant for lists, search results, and the saved page. */
export function QuestionRow({ card }: { card: CardSummary }) {
  const accent = categoryAccent(card.category?.accent);

  return (
    <Link href={`/q/${card.slug}`} className="group block">
      <div className="flex items-start gap-4 rounded-xl px-3 py-3.5 transition-colors hover:bg-surface-2">
        <span
          className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-lg"
          style={{ background: `${accent}1a`, color: accent }}
        >
          <Icon name={card.category?.icon ?? "Sparkles"} className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-serif text-[16px] font-medium leading-snug text-text">
            {card.title}
          </h3>
          <p className="mt-1 line-clamp-2 text-[13px] leading-relaxed text-text-secondary">
            {card.one_sentence_answer}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-text-faint">
            {card.category && <span>{card.category.name}</span>}
            <span>{formatMinutes(card.reading_minutes)}</span>
          </div>
        </div>
        <Icon
          name="ChevronRight"
          className="mt-3 size-4 shrink-0 text-text-faint transition-transform group-hover:translate-x-0.5"
        />
      </div>
    </Link>
  );
}
