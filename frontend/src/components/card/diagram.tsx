"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { Diagram } from "@/lib/types";
import { Icon } from "@/components/ui/icon";

/**
 * Mermaid is imported dynamically and only when a diagram is actually on the
 * page — it is a large dependency and most routes never need it.
 *
 * Theme is resolved from the live CSS custom properties rather than hardcoded,
 * so a diagram matches whichever theme the reader is in and follows them when
 * they switch.
 */
export function DiagramBlock({ diagram }: { diagram: Diagram }) {
  if (diagram.kind === "steps") return <StepsDiagram diagram={diagram} />;
  return <MermaidDiagram diagram={diagram} />;
}

function StepsDiagram({ diagram }: { diagram: Diagram }) {
  const steps = diagram.content
    .split("\n")
    .map((line) => line.replace(/^\s*\d+[.)]\s*/, "").trim())
    .filter(Boolean);

  return (
    <figure className="my-7">
      <figcaption className="mb-3 text-[13px] font-medium text-text">
        {diagram.title}
      </figcaption>
      <ol className="space-y-2.5">
        {steps.map((step, i) => (
          <li key={i} className="flex gap-3">
            <span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-full bg-surface-2 text-[11px] font-semibold text-text-muted">
              {i + 1}
            </span>
            <span className="text-[15px] leading-relaxed text-text-secondary">{step}</span>
          </li>
        ))}
      </ol>
      {diagram.caption && (
        <p className="mt-3 text-[13px] italic text-text-muted">{diagram.caption}</p>
      )}
    </figure>
  );
}

function MermaidDiagram({ diagram }: { diagram: Diagram }) {
  const id = useId().replace(/:/g, "");
  const containerRef = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");

  useEffect(() => {
    let cancelled = false;

    async function render() {
      try {
        const mermaid = (await import("mermaid")).default;
        const styles = getComputedStyle(document.documentElement);
        const token = (name: string, fallback: string) =>
          styles.getPropertyValue(name).trim() || fallback;

        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          fontFamily: token("--font-sans", "system-ui"),
          themeVariables: {
            background: "transparent",
            primaryColor: token("--color-surface-2", "#f4f2f0"),
            primaryTextColor: token("--color-text", "#1a1917"),
            primaryBorderColor: token("--color-border-strong", "#d2ccc6"),
            lineColor: token("--color-text-faint", "#a8a29b"),
            secondaryColor: token("--color-surface-3", "#eae7e4"),
            tertiaryColor: token("--color-surface", "#ffffff"),
            fontSize: "14px",
          },
        });

        const { svg } = await mermaid.render(`m-${id}`, diagram.content);
        if (cancelled || !containerRef.current) return;
        containerRef.current.innerHTML = svg;
        setState("ready");
      } catch {
        // A malformed diagram from the model must not take the page down.
        if (!cancelled) setState("failed");
      }
    }

    render();
    return () => {
      cancelled = true;
    };
    // Re-render on theme change so colours follow the toggle.
  }, [diagram.content, id]);

  if (state === "failed") {
    return (
      <figure className="my-7 rounded-[--radius-card] border border-dashed border-border p-5">
        <figcaption className="mb-2 flex items-center gap-2 text-[13px] font-medium text-text">
          <Icon name="ImageOff" className="size-3.5 text-text-faint" />
          {diagram.title}
        </figcaption>
        <p className="text-[13px] text-text-muted">
          This diagram could not be drawn. {diagram.caption}
        </p>
      </figure>
    );
  }

  return (
    <figure className="my-7">
      <figcaption className="mb-3 text-[13px] font-medium text-text">
        {diagram.title}
      </figcaption>
      <div className="overflow-x-auto rounded-[--radius-card] border border-border bg-surface-2/50 p-5">
        <div
          ref={containerRef}
          className="mx-auto flex min-h-[80px] w-fit items-center justify-center [&_svg]:h-auto [&_svg]:max-w-full"
        />
      </div>
      {diagram.caption && (
        <p className="mt-3 text-[13px] italic text-text-muted">{diagram.caption}</p>
      )}
    </figure>
  );
}
