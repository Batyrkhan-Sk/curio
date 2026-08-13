import Link from "next/link";
import { getAiStatus } from "@/lib/api";
import { Card, SectionLabel } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/icon";

export const revalidate = 300;

export const metadata = {
  title: "How this works",
  description: "Where Curio's cards come from, and how far to trust them.",
};

export default async function AboutPage() {
  const status = await getAiStatus().catch(() => null);

  return (
    <div className="mx-auto max-w-2xl px-5 py-10 sm:px-8">
      <h1 className="font-serif text-2xl font-medium tracking-[-0.01em]">
        How this works
      </h1>

      <div className="prose-curio mt-6">
        <p>
          Google indexes web pages. Wikipedia organises knowledge by topic.
          Curio organises it by the questions people keep asking — because the
          question is usually the part you actually have, and the page is the
          part you have to go and find.
        </p>
        <p>
          Cards are not written by hand and they are not copied from anywhere.
          A pipeline watches public discussion for questions that keep
          resurfacing, merges the different phrasings of the same curiosity into
          one, gathers evidence from several independent sources, and writes an
          explanation that starts from plain intuition and goes down five levels
          to expert detail. A second pass checks the draft against the same
          evidence and scores how well supported it is.
        </p>
        <p>
          That score is shown on every card, and it is not decorative. Below a
          threshold, a card is never published at all. Where sources genuinely
          disagree, the card says so rather than picking a side quietly.
        </p>
        <p>
          Most of what gets collected never becomes anything. You can see the
          discards for yourself on{" "}
          <Link href="/incoming" className="text-accent-text underline">
            the incoming queue
          </Link>{" "}
          — every question the platform has found, where it came from, and
          whether it was rejected and why.
        </p>
      </div>

      <section className="mt-10">
        <SectionLabel className="mb-4">The one unbreakable rule</SectionLabel>
        <Card className="p-5">
          <p className="text-[15px] leading-relaxed text-text-secondary">
            No card may use a term it has not already explained. Every
            explanation is checked for it, and a violation costs the card
            confidence. It is the difference between an answer you can read and
            an answer you have to go and research first.
          </p>
        </Card>
      </section>

      <section className="mt-10">
        <SectionLabel className="mb-4">What is running right now</SectionLabel>
        <Card className="divide-y divide-border p-0">
          <StatusRow
            label="Browsing, search, graph, saves, offline"
            on
            detail="Always available"
          />
          <StatusRow
            label="Search by meaning as well as words"
            on={status?.features.semantic_search ?? false}
            detail={
              status?.features.semantic_search
                ? "Embeddings active"
                : "Needs an AI key — keyword search still works"
            }
          />
          <StatusRow
            label="Fresh explanations when one doesn't land"
            on={status?.features.reexplain_generative ?? false}
            detail={
              status?.features.reexplain_generative
                ? "Generated on demand"
                : "Falls back to the card's other levels"
            }
          />
          <StatusRow
            label="Discovering and writing new cards"
            on={status?.features.synthesis ?? false}
            detail={
              status?.features.synthesis
                ? `Model: ${status?.model}`
                : "Needs an AI key — the curated corpus is served instead"
            }
          />
        </Card>
      </section>

      <section className="mt-10">
        <SectionLabel className="mb-4">What Curio knows about you</SectionLabel>
        <div className="prose-curio">
          <p>
            There is no account and no password. Your browser generates a random
            key and keeps it locally; the server uses it to remember which cards
            you have read so it can suggest what follows. Nothing is linked to
            an email, and you can see and copy the key on{" "}
            <Link href="/you" className="text-accent-text underline">
              your page
            </Link>
            .
          </p>
          <p>
            A fixed share of every recommendation is drawn from subjects you
            have never touched, and it cannot be turned off. A system that only
            ever shows you more of what you already clicked stops being worth
            opening.
          </p>
        </div>
      </section>
    </div>
  );
}

function StatusRow({
  label,
  on,
  detail,
}: {
  label: string;
  on: boolean;
  detail: string;
}) {
  return (
    <div className="flex items-start gap-3 px-5 py-3.5">
      <Icon
        name={on ? "CircleCheck" : "CircleDashed"}
        className={on ? "mt-0.5 size-4 text-positive" : "mt-0.5 size-4 text-text-faint"}
      />
      <div className="min-w-0 flex-1">
        <p className="text-[14px] text-text">{label}</p>
        <p className="text-[12px] text-text-muted">{detail}</p>
      </div>
    </div>
  );
}
