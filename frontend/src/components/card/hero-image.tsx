import type { CardImage } from "@/lib/types";

/**
 * The picture between the question and the explanation.
 *
 * Most cards render nothing here, which is the point: an image survives to
 * this component only if the synthesis model judged that seeing it teaches
 * something the prose cannot. So the layout is built for a picture that is
 * carrying weight — full measure, above the levels, captioned — rather than
 * for a decorative strip that has to stay out of the way.
 *
 * A plain <img> rather than next/image. The source is Curio's own proxy at a
 * path the service worker already caches, so the optimiser would add a second
 * cache and a second set of failure modes to bytes that are already the right
 * size and already offline-available.
 */
export function HeroImage({ image }: { image: CardImage | null }) {
  if (!image?.url) return null;

  const fromAsker = image.origin === "question";

  return (
    <figure className="mt-8">
      <div className="overflow-hidden rounded-[--radius-card] border border-border bg-surface-2">
        <img
          src={image.url}
          alt={image.alt || image.caption || ""}
          // Known ahead of time for most images, and passing them is what stops
          // the page reflowing around the picture as it loads.
          width={image.width || undefined}
          height={image.height || undefined}
          // Eager: this sits above the fold on the card it belongs to, so
          // deferring it only guarantees the reader watches it arrive late.
          loading="eager"
          className="block max-h-[26rem] w-full bg-surface-2 object-contain"
        />
      </div>

      <figcaption className="mt-3 space-y-1.5 text-[12px] leading-relaxed text-text-muted">
        {image.caption && <p className="text-text-secondary">{image.caption}</p>}

        <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
          {/* Which of the two this is changes what the reader is looking at:
              the photograph somebody attached to the question, or a picture of
              the subject from a source. Saying so costs one clause. */}
          <span>{fromAsker ? "Posted with the question" : "From the sources"}</span>

          {image.credit && (
            <>
              <span aria-hidden>·</span>
              <span>{image.credit}</span>
            </>
          )}

          {image.license && (
            <>
              <span aria-hidden>·</span>
              {image.license_url ? (
                <a
                  href={image.license_url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="underline decoration-border underline-offset-2 hover:text-text"
                >
                  {image.license}
                </a>
              ) : (
                <span>{image.license}</span>
              )}
            </>
          )}

          {image.source_url && (
            <>
              <span aria-hidden>·</span>
              <a
                href={image.source_url}
                target="_blank"
                rel="noreferrer noopener"
                className="underline decoration-border underline-offset-2 hover:text-text"
              >
                {fromAsker ? "original post" : "source"}
              </a>
            </>
          )}
        </p>
      </figcaption>
    </figure>
  );
}
