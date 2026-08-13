import Link from "next/link";
import { getCategories } from "@/lib/api";
import { Card, EmptyState } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/icon";
import { categoryAccent, pluralize } from "@/lib/utils";

export const revalidate = 600;

export const metadata = {
  title: "Categories",
  description: "Browse curiosity by subject.",
};

export default async function CategoriesPage() {
  let categories;
  try {
    categories = await getCategories();
  } catch {
    return (
      <div className="mx-auto max-w-6xl px-5 py-8 sm:px-8">
        <EmptyState title="Can't reach the library right now" />
      </div>
    );
  }

  // Categories with nothing in them are noise, but keeping them visible as a
  // dimmed "coming soon" row is honest about what the platform intends to cover.
  const stocked = categories.filter((c) => (c.card_count ?? 0) > 0);
  const empty = categories.filter((c) => !(c.card_count ?? 0));

  return (
    <div className="mx-auto max-w-6xl px-5 py-8 sm:px-8">
      <header className="mb-8">
        <h1 className="font-serif text-2xl font-medium tracking-[-0.01em]">
          Browse by subject
        </h1>
        <p className="mt-1.5 max-w-2xl text-sm text-text-secondary">
          The categories are a convenience, not the structure. Most interesting
          questions belong to several at once — the graph is the truer map.
        </p>
      </header>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {stocked.map((category) => {
          const accent = categoryAccent(category.accent);
          return (
            <Link key={category.slug} href={`/categories/${category.slug}`}>
              <Card hover className="group h-full p-5">
                <div className="flex items-start gap-4">
                  <span
                    className="grid size-10 shrink-0 place-items-center rounded-xl"
                    style={{ background: `${accent}1a`, color: accent }}
                  >
                    <Icon name={category.icon} className="size-5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <h2 className="font-medium tracking-tight">{category.name}</h2>
                    <p className="mt-1 text-[13px] leading-relaxed text-text-secondary">
                      {category.description}
                    </p>
                    <p className="mt-2 text-[11px] text-text-faint">
                      {pluralize(category.card_count ?? 0, "question")}
                    </p>
                  </div>
                </div>
              </Card>
            </Link>
          );
        })}
      </div>

      {empty.length > 0 && (
        <section className="mt-10">
          <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-text-faint">
            Not covered yet
          </div>
          <div className="flex flex-wrap gap-2">
            {empty.map((category) => (
              <span
                key={category.slug}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-[12px] text-text-faint"
              >
                <Icon name={category.icon} className="size-3.5" />
                {category.name}
              </span>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
