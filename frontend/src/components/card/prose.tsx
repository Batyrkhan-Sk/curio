import { paragraphs, renderInline } from "@/lib/utils";
import { cn } from "@/lib/utils";

/**
 * Renders the plain prose the pipeline emits. Not a markdown renderer on
 * purpose — the prompts forbid headings and lists inside explanation bodies,
 * so the only markup that can appear is **bold**, and parsing more than that
 * would silently invite the model to start using it.
 */
export function Prose({
  text,
  className,
}: {
  text: string;
  className?: string;
}) {
  const blocks = paragraphs(text);

  return (
    <div className={cn("prose-curio", className)}>
      {blocks.map((block, i) => (
        <p key={i}>
          {renderInline(block).map((chunk, j) =>
            chunk.bold ? <strong key={j}>{chunk.text}</strong> : <span key={j}>{chunk.text}</span>,
          )}
        </p>
      ))}
    </div>
  );
}
