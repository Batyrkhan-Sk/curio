import { notFound } from "next/navigation";
import { getCategories, listCards } from "@/lib/api";
import { QuestionCard } from "@/components/discovery/question-card";
import { EmptyState } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/icon";
import { categoryAccent } from "@/lib/utils";

export const revalidate = 300;

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props) {
  const { slug } = await params;
  const categories = await getCategories().catch(() => []);
  const category = categories.find((c) => c.slug === slug);
  return {
    title: category?.name ?? "Category",
    description: category?.description,
  };
}

export default async function CategoryPage({ params }: Props) {
  const { slug } = await params;

  const [categories, cards] = await Promise.all([
    getCategories().catch(() => []),
    listCards({ category: slug, limit: 48 }).catch(() => []),
  ]);

  const category = categories.find((c) => c.slug === slug);
  if (!category) notFound();

  const accent = categoryAccent(category.accent);

  return (
    <div className="mx-auto max-w-6xl px-5 py-8 sm:px-8">
      <header className="mb-8 flex items-start gap-4">
        <span
          className="grid size-12 shrink-0 place-items-center rounded-2xl"
          style={{ background: `${accent}1a`, color: accent }}
        >
          <Icon name={category.icon} className="size-6" />
        </span>
        <div>
          <h1 className="font-serif text-2xl font-medium tracking-[-0.01em]">
            {category.name}
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-text-secondary">
            {category.description}
          </p>
        </div>
      </header>

      {cards.length ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {cards.map((card) => (
            <QuestionCard key={card.id} card={card} />
          ))}
        </div>
      ) : (
        <EmptyState
          title={`Nothing in ${category.name} yet`}
          description="This subject is on the map but not yet stocked."
        />
      )}
    </div>
  );
}
