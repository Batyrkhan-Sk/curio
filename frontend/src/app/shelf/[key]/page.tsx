import { notFound } from "next/navigation";
import { getShelf } from "@/lib/api";
import { resolveMode } from "@/lib/mode";
import { QuestionCard } from "@/components/discovery/question-card";
import { EmptyState } from "@/components/ui/primitives";

export const revalidate = 120;

type Props = {
  params: Promise<{ key: string }>;
  searchParams: Promise<{ mode?: string }>;
};

export async function generateMetadata({ params }: Props) {
  const { key } = await params;
  try {
    const shelf = await getShelf(key, 1);
    return { title: shelf.title, description: shelf.subtitle };
  } catch {
    return { title: "Shelf" };
  }
}

export default async function ShelfPage({ params, searchParams }: Props) {
  const { key } = await params;
  // No cookie fallback here: a shelf link is usually shared or arrived at from
  // a feed that already spelled the mode out, and silently narrowing someone
  // else's link to a mode they never chose would be worse than the default.
  const mode = resolveMode((await searchParams).mode);

  let shelf;
  try {
    shelf = await getShelf(key, 48, mode);
  } catch {
    notFound();
  }

  return (
    <div className="mx-auto max-w-6xl px-5 py-8 sm:px-8">
      <header className="mb-7">
        <h1 className="font-serif text-2xl font-medium tracking-[-0.01em]">
          {shelf.title}
        </h1>
        {shelf.subtitle && (
          <p className="mt-1.5 max-w-2xl text-sm text-text-secondary">
            {shelf.subtitle}
          </p>
        )}
      </header>

      {shelf.cards.length ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {shelf.cards.map((card) => (
            <QuestionCard key={card.id} card={card} />
          ))}
        </div>
      ) : (
        <EmptyState
          title="Nothing on this shelf yet"
          description="Shelves fill as the corpus grows. Try another, or let something random find you."
        />
      )}
    </div>
  );
}
