/**
 * Base primitives, written in the shadcn/ui idiom — same composition model and
 * variant API, hand-rolled against the Curio tokens so there is no generated
 * code to keep in sync and no CLI step in the build.
 */

import * as React from "react";
import { cn } from "@/lib/utils";

// --- Card ------------------------------------------------------------------

export function Card({
  className,
  hover = false,
  ...props
}: React.ComponentProps<"div"> & { hover?: boolean }) {
  return (
    <div
      className={cn(
        "rounded-[--radius-card] border border-border bg-surface shadow-[--shadow-card]",
        hover &&
          "transition-[box-shadow,transform,border-color] duration-200 ease-[--ease-out-soft] hover:-translate-y-0.5 hover:border-border-strong hover:shadow-[--shadow-lift]",
        className,
      )}
      {...props}
    />
  );
}

// --- Badge -----------------------------------------------------------------

const badgeTones = {
  neutral: "bg-surface-2 text-text-muted",
  accent: "bg-accent-soft text-accent-text",
  positive: "bg-positive/10 text-positive",
  caution: "bg-caution/10 text-caution",
  critical: "bg-critical/10 text-critical",
  outline: "border border-border text-text-muted",
} as const;

export function Badge({
  className,
  tone = "neutral",
  ...props
}: React.ComponentProps<"span"> & { tone?: keyof typeof badgeTones }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium leading-5",
        badgeTones[tone],
        className,
      )}
      {...props}
    />
  );
}

// --- Button ----------------------------------------------------------------

const buttonVariants = {
  primary:
    "bg-text text-canvas hover:opacity-90 active:opacity-80 disabled:opacity-40",
  secondary:
    "bg-surface-2 text-text hover:bg-surface-3 active:bg-surface-3 disabled:opacity-40",
  outline:
    "border border-border bg-transparent text-text hover:border-border-strong hover:bg-surface-2 disabled:opacity-40",
  ghost: "bg-transparent text-text-secondary hover:bg-surface-2 hover:text-text disabled:opacity-40",
  accent:
    "bg-accent-soft text-accent-text hover:brightness-[0.97] active:brightness-95 disabled:opacity-40",
} as const;

const buttonSizes = {
  sm: "h-8 px-3 text-[13px] gap-1.5 rounded-lg",
  md: "h-10 px-4 text-sm gap-2 rounded-xl",
  lg: "h-12 px-5 text-[15px] gap-2 rounded-xl",
  icon: "size-9 rounded-lg justify-center",
} as const;

export function Button({
  className,
  variant = "secondary",
  size = "md",
  ...props
}: React.ComponentProps<"button"> & {
  variant?: keyof typeof buttonVariants;
  size?: keyof typeof buttonSizes;
}) {
  return (
    <button
      className={cn(
        "inline-flex select-none items-center font-medium transition-[background-color,opacity,border-color,filter] duration-150 disabled:pointer-events-none",
        buttonVariants[variant],
        buttonSizes[size],
        className,
      )}
      {...props}
    />
  );
}

// --- Section header --------------------------------------------------------

export function SectionLabel({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "text-[11px] font-semibold uppercase tracking-[0.12em] text-text-faint",
        className,
      )}
      {...props}
    />
  );
}

// --- Skeleton --------------------------------------------------------------

export function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn("animate-pulse rounded-lg bg-surface-2", className)}
      aria-hidden
      {...props}
    />
  );
}

// --- Empty state -----------------------------------------------------------

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-[--radius-card] border border-dashed border-border px-6 py-14 text-center">
      <p className="text-sm font-medium text-text">{title}</p>
      {description && (
        <p className="mt-1.5 max-w-sm text-[13px] leading-relaxed text-text-muted">
          {description}
        </p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

// --- Divider ---------------------------------------------------------------

export function Divider({ className, ...props }: React.ComponentProps<"hr">) {
  return <hr className={cn("border-t border-border", className)} {...props} />;
}
