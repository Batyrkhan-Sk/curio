"use client";

import * as Lucide from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Icons arrive as names from the API (category records carry an icon slug),
 * so lookup has to be dynamic. Unknown names fall back rather than crashing a
 * page over a typo in a seed file.
 */
export type IconName = keyof typeof Lucide;

export function Icon({
  name,
  className,
  strokeWidth = 1.75,
}: {
  name: string;
  className?: string;
  strokeWidth?: number;
}) {
  const Component = (Lucide as Record<string, unknown>)[name] as
    | React.ComponentType<{ className?: string; strokeWidth?: number }>
    | undefined;

  const Resolved = Component ?? Lucide.Sparkles;
  return <Resolved className={cn("size-4", className)} strokeWidth={strokeWidth} />;
}
