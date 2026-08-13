import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { getRandomCard } from "@/lib/api";
import { MODE_COOKIE, resolveMode } from "@/lib/mode";

// Always fresh — the whole point is that it differs every time.
export const dynamic = "force-dynamic";

type Props = { searchParams: Promise<{ mode?: string }> };

export default async function RandomPage({ searchParams }: Props) {
  const { mode: requested } = await searchParams;
  const remembered = (await cookies()).get(MODE_COOKIE)?.value;
  const mode = resolveMode(requested ?? remembered);

  // redirect() signals by throwing, so it has to sit outside the try/catch —
  // otherwise the catch swallows the redirect and sends everyone home instead.
  let slug: string | null = null;
  try {
    slug = (await getRandomCard(mode)).slug;
  } catch {
    slug = null;
  }

  redirect(slug ? `/q/${slug}` : "/");
}
