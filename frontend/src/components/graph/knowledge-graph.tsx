"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { GraphData, GraphNode } from "@/lib/types";
import { Icon } from "@/components/ui/icon";

/**
 * A force-directed map of connected questions.
 *
 * Hand-rolled rather than pulled from a library: the simulation is about
 * forty lines, and the alternatives all want to own the DOM, which fights
 * with keeping the nodes as real focusable links. Accessibility matters here —
 * the same data is exposed as a plain list below the canvas so the graph is
 * navigable without a pointer.
 */

interface Simulated extends GraphNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
}

const REPULSION = 5200;
const SPRING = 0.012;
const DAMPING = 0.86;
const CENTRE_PULL = 0.006;

export function KnowledgeGraph({
  data,
  rootSlug,
}: {
  data: GraphData;
  rootSlug?: string;
}) {
  const router = useRouter();
  const svgRef = useRef<SVGSVGElement>(null);
  const [nodes, setNodes] = useState<Simulated[]>([]);
  const [hovered, setHovered] = useState<string | null>(null);
  const frame = useRef<number>(0);

  const size = { width: 900, height: 560 };

  const initial = useMemo<Simulated[]>(() => {
    // Seed positions on concentric rings by depth so the layout starts close
    // to its solution — a random start takes far longer to settle and looks
    // chaotic while it does.
    const byDepth = new Map<number, number>();
    return data.nodes.map((node) => {
      const index = byDepth.get(node.depth) ?? 0;
      byDepth.set(node.depth, index + 1);
      const count = data.nodes.filter((n) => n.depth === node.depth).length;
      const angle = (index / Math.max(count, 1)) * Math.PI * 2;
      const radius = node.depth * 150;
      return {
        ...node,
        x: size.width / 2 + Math.cos(angle) * radius,
        y: size.height / 2 + Math.sin(angle) * radius,
        vx: 0,
        vy: 0,
      };
    });
  }, [data.nodes, size.width, size.height]);

  useEffect(() => {
    let current = initial.map((n) => ({ ...n }));
    let ticks = 0;

    const step = () => {
      // Repulsion between every pair keeps labels from overlapping.
      for (let i = 0; i < current.length; i++) {
        for (let j = i + 1; j < current.length; j++) {
          const a = current[i];
          const b = current[j];
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const distanceSq = Math.max(dx * dx + dy * dy, 400);
          const force = REPULSION / distanceSq;
          const distance = Math.sqrt(distanceSq);
          const fx = (dx / distance) * force;
          const fy = (dy / distance) * force;
          a.vx -= fx;
          a.vy -= fy;
          b.vx += fx;
          b.vy += fy;
        }
      }

      // Springs pull connected questions together, weighted by how strong the
      // relationship is.
      const index = new Map(current.map((n) => [n.id, n]));
      for (const edge of data.edges) {
        const a = index.get(edge.source);
        const b = index.get(edge.target);
        if (!a || !b) continue;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const pull = SPRING * (edge.weight || 0.5);
        a.vx += dx * pull;
        a.vy += dy * pull;
        b.vx -= dx * pull;
        b.vy -= dy * pull;
      }

      for (const node of current) {
        node.vx += (size.width / 2 - node.x) * CENTRE_PULL;
        node.vy += (size.height / 2 - node.y) * CENTRE_PULL;
        node.vx *= DAMPING;
        node.vy *= DAMPING;
        node.x = Math.max(60, Math.min(size.width - 60, node.x + node.vx));
        node.y = Math.max(40, Math.min(size.height - 40, node.y + node.vy));
      }

      setNodes(current.map((n) => ({ ...n })));

      // Stop after the layout has settled rather than burning a rAF loop
      // forever behind a static picture.
      if (++ticks < 260) frame.current = requestAnimationFrame(step);
    };

    frame.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame.current);
  }, [initial, data.edges, size.width, size.height]);

  const index = new Map(nodes.map((n) => [n.id, n]));
  const connected = (id: string) =>
    hovered === null ||
    hovered === id ||
    data.edges.some(
      (e) =>
        (e.source === hovered && e.target === id) ||
        (e.target === hovered && e.source === id),
    );

  return (
    <div>
      <div className="overflow-x-auto rounded-[--radius-card] border border-border bg-surface">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${size.width} ${size.height}`}
          className="h-[420px] w-full min-w-[720px] sm:h-[560px]"
          role="img"
          aria-label={`Knowledge graph of ${data.nodes.length} connected questions`}
        >
          <g>
            {data.edges.map((edge, i) => {
              const a = index.get(edge.source);
              const b = index.get(edge.target);
              if (!a || !b) return null;
              const dim =
                hovered !== null && edge.source !== hovered && edge.target !== hovered;
              return (
                <line
                  key={i}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  stroke="var(--color-border-strong)"
                  strokeWidth={Math.max(1, edge.weight * 2)}
                  opacity={dim ? 0.15 : 0.55}
                  className="transition-opacity duration-200"
                />
              );
            })}
          </g>

          <g>
            {nodes.map((node) => {
              const isRoot = node.depth === 0;
              const dim = !connected(node.id);
              const radius = isRoot ? 9 : node.depth === 1 ? 6.5 : 5;

              return (
                <g
                  key={node.id}
                  transform={`translate(${node.x} ${node.y})`}
                  opacity={dim ? 0.28 : 1}
                  className="cursor-pointer transition-opacity duration-200"
                  onMouseEnter={() => setHovered(node.id)}
                  onMouseLeave={() => setHovered(null)}
                  onClick={() => router.push(`/q/${node.slug}`)}
                >
                  <circle
                    r={radius}
                    fill={isRoot ? "var(--color-accent)" : "var(--color-surface)"}
                    stroke={
                      isRoot ? "var(--color-accent)" : "var(--color-border-strong)"
                    }
                    strokeWidth={2}
                  />
                  <text
                    y={-radius - 8}
                    textAnchor="middle"
                    className="pointer-events-none select-none"
                    fill="var(--color-text-secondary)"
                    fontSize={isRoot ? 13 : 11.5}
                    fontWeight={isRoot ? 600 : 400}
                  >
                    {truncate(node.label, isRoot ? 44 : 34)}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>
      </div>

      <p className="mt-2 flex items-center gap-1.5 px-1 text-[11px] text-text-faint">
        <Icon name="MousePointerClick" className="size-3" />
        Hover to isolate a question&rsquo;s connections. Click to open it.
      </p>

      {/* Keyboard and screen-reader route to the same destinations. */}
      <ul className="mt-6 grid gap-1 sm:grid-cols-2">
        {data.nodes.map((node) => (
          <li key={node.id}>
            <a
              href={`/q/${node.slug}`}
              className="flex items-center gap-2 rounded-lg px-3 py-2 text-[13px] text-text-secondary transition-colors hover:bg-surface-2 hover:text-text"
              onMouseEnter={() => setHovered(node.id)}
              onMouseLeave={() => setHovered(null)}
            >
              <span
                className="size-1.5 shrink-0 rounded-full"
                style={{
                  background:
                    node.depth === 0
                      ? "var(--color-accent)"
                      : "var(--color-border-strong)",
                }}
              />
              <span className="truncate">{node.label}</span>
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`;
}
