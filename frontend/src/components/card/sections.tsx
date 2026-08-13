import type { CardDetail } from "@/lib/types";
import { Prose } from "./prose";
import { Badge, Card, SectionLabel } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/icon";

/**
 * Everything below the explanation levels. Each of these is a distinct
 * commitment from the brief — misconceptions, why it matters, history,
 * sources, confidence — and each is rendered as its own quiet block rather
 * than being flattened into one long article.
 */

export function Misconceptions({ card }: { card: CardDetail }) {
  if (!card.misconceptions.length) return null;

  return (
    <section className="mt-12">
      <SectionLabel className="mb-4">What people get wrong</SectionLabel>
      <div className="space-y-3">
        {card.misconceptions.map((item, i) => (
          <Card key={i} className="overflow-hidden p-0">
            <div className="flex gap-3 border-b border-border bg-surface-2/50 px-5 py-3">
              <Icon name="X" className="mt-0.5 size-4 shrink-0 text-critical" />
              <p className="text-[14px] font-medium leading-relaxed text-text">
                {item.myth}
              </p>
            </div>
            <div className="flex gap-3 px-5 py-3.5">
              <Icon name="Check" className="mt-0.5 size-4 shrink-0 text-positive" />
              <p className="text-[14px] leading-relaxed text-text-secondary">
                {item.reality}
              </p>
            </div>
          </Card>
        ))}
      </div>
    </section>
  );
}

export function WhyItMatters({ card }: { card: CardDetail }) {
  if (!card.why_it_matters) return null;

  return (
    <section className="mt-12">
      <SectionLabel className="mb-4">Why it matters</SectionLabel>
      <div className="border-l-2 border-accent pl-5">
        <Prose text={card.why_it_matters} />
      </div>
    </section>
  );
}

export function History({ card }: { card: CardDetail }) {
  const { origin, motivation, evolution } = card.historical_background ?? {};
  const entries = [
    { label: "Who worked it out", body: origin, icon: "User" },
    { label: "What problem forced it", body: motivation, icon: "Target" },
    { label: "How it changed since", body: evolution, icon: "GitBranch" },
  ].filter((entry) => entry.body);

  if (!entries.length) return null;

  return (
    <section className="mt-12">
      <SectionLabel className="mb-4">Where this came from</SectionLabel>
      <div className="space-y-5">
        {entries.map((entry) => (
          <div key={entry.label} className="flex gap-4">
            <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg bg-surface-2 text-text-muted">
              <Icon name={entry.icon} className="size-3.5" />
            </span>
            <div className="min-w-0">
              <p className="text-[12px] font-medium uppercase tracking-[0.08em] text-text-faint">
                {entry.label}
              </p>
              <p className="mt-1 text-[15px] leading-relaxed text-text-secondary">
                {entry.body}
              </p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export function Contradictions({ card }: { card: CardDetail }) {
  if (!card.contradictions?.length) return null;

  return (
    <section className="mt-12">
      <SectionLabel className="mb-4">Where sources disagree</SectionLabel>
      <div className="space-y-3">
        {card.contradictions.map((item, i) => (
          <Card key={i} className="p-5">
            <p className="text-[14px] font-medium text-text">{item.claim}</p>
            <p className="mt-2 text-[13px] leading-relaxed text-text-secondary">
              {item.conflict}
            </p>
            {item.resolution && (
              <p className="mt-2 text-[13px] leading-relaxed text-text-muted">
                <span className="font-medium text-text-secondary">
                  Most defensible reading:{" "}
                </span>
                {item.resolution}
              </p>
            )}
          </Card>
        ))}
      </div>
    </section>
  );
}

const SOURCE_ICONS: Record<string, string> = {
  wikipedia: "BookOpen",
  paper: "FileText",
  gov: "Landmark",
  docs: "FileCode",
  book: "Book",
  forum: "MessagesSquare",
  video: "Play",
  blog: "PenLine",
  web: "Globe",
};

/**
 * Sources, sized for the rail beside the title.
 *
 * Moved out of the article flow deliberately: the references are what make a
 * claim checkable, so they should be visible while the explanation is being
 * read rather than waiting at the bottom for readers who scroll that far.
 */
export function Sources({ card }: { card: CardDetail }) {
  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <SectionLabel>Sources</SectionLabel>
        <Badge tone="outline">
          {Math.round(card.confidence * 100)}% confidence
        </Badge>
      </div>

      {card.confidence_reason && (
        <p className="mb-3 text-[12px] leading-relaxed text-text-muted">
          {card.confidence_reason}
        </p>
      )}

      {card.sources.length ? (
        <ul className="space-y-0.5">
          {card.sources.map((source, i) => (
            <li key={i}>
              <a
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                className="group flex items-start gap-2.5 rounded-lg px-2 py-2 transition-colors hover:bg-surface-2"
              >
                <span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-md bg-surface-2 text-text-muted">
                  <Icon
                    name={SOURCE_ICONS[source.kind] ?? "Globe"}
                    className="size-3"
                  />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[13px] font-medium leading-snug text-text">
                    {source.title}
                  </span>
                  <span className="mt-0.5 block text-[11px] text-text-faint">
                    {source.publisher || new URL(source.url).hostname} ·{" "}
                    {Math.round(source.reliability * 100)}% reliability
                  </span>
                </span>
              </a>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[12px] text-text-muted">
          This card was written without external references, which is why its
          confidence is capped.
        </p>
      )}
    </section>
  );
}

/** "hackernews" → "Hacker News", "reddit:askscience" → "Reddit · r/askscience". */
function sourceLabel(name: string): string {
  const [platform, board] = name.split(":");
  if (platform === "reddit") return board ? `Reddit · r/${board}` : "Reddit";
  if (platform === "stackexchange") {
    if (board === "stackoverflow") return "Stack Overflow";
    return board ? `Stack Exchange · ${board}` : "Stack Exchange";
  }
  if (platform === "hackernews") return "Hacker News";
  return platform || name;
}

/**
 * Where the question came from.
 *
 * The whole premise of the platform is indexing questions people actually
 * ask, so a card should be able to show its receipts: which forum, which
 * thread, how many separate places it turned up. Curated cards say plainly
 * that they were written rather than found — claiming a source they do not
 * have would be worse than admitting there isn't one.
 */
export function QuestionOrigin({ card }: { card: CardDetail }) {
  const asked = card.asked_at ?? [];

  if (!asked.length) {
    return (
      <section className="mt-12">
        <SectionLabel className="mb-3">Where this question came from</SectionLabel>
        <p className="text-[13px] leading-relaxed text-text-muted">
          Written for Curio rather than collected from a forum — it is part of
          the curated corpus that ships with the platform. The references it
          draws on are listed under Sources.
        </p>
      </section>
    );
  }

  const totalSightings = asked.reduce((sum, a) => sum + (a.occurrences || 1), 0);

  return (
    <section className="mt-12">
      <SectionLabel className="mb-3">Where this question came from</SectionLabel>
      <p className="mb-4 text-[13px] leading-relaxed text-text-muted">
        Collected from public discussion — asked {totalSightings}{" "}
        {totalSightings === 1 ? "time" : "times"} across{" "}
        {asked.length === 1 ? "one place" : `${asked.length} places`}.
      </p>
      <ul className="space-y-1">
        {asked.map((item, i) => (
          <li key={i}>
            <a
              href={item.source_url || undefined}
              target="_blank"
              rel="noopener noreferrer"
              className="group flex items-start gap-3 rounded-lg px-3 py-2.5 transition-colors hover:bg-surface-2"
            >
              <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-md bg-surface-2 text-text-muted">
                <Icon name="MessagesSquare" className="size-3.5" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[14px] font-medium leading-snug text-text">
                  {sourceLabel(item.source_name)}
                </span>
                {item.raw_text && (
                  <span className="mt-0.5 block text-[12px] leading-snug text-text-faint">
                    “{item.raw_text}”
                  </span>
                )}
              </span>
              {item.source_url && (
                <Icon
                  name="ExternalLink"
                  className="mt-1 size-3.5 shrink-0 text-text-faint transition-colors group-hover:text-text-secondary"
                />
              )}
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function NextSteps({ card }: { card: CardDetail }) {
  if (!card.next_steps?.length) return null;

  return (
    <section className="mt-12">
      <SectionLabel className="mb-4">Where to go next</SectionLabel>
      <div className="space-y-3">
        {card.next_steps.map((step, i) => (
          <div key={i} className="flex gap-3">
            <Icon name="ArrowRight" className="mt-1 size-4 shrink-0 text-accent" />
            <div>
              <p className="text-[14px] font-medium text-text">{step.label}</p>
              {step.reason && (
                <p className="mt-0.5 text-[13px] leading-relaxed text-text-muted">
                  {step.reason}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
