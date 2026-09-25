/**
 * Mirrors the Pydantic schemas in `backend/app/schemas/`. Keep the two in
 * step — these are the only place the API contract is written down on this
 * side, so a drift here is a silent runtime failure rather than a build error.
 */

export interface Category {
  slug: string;
  name: string;
  icon: string;
  accent: string;
  description: string;
  card_count?: number;
}

export interface ExplanationLevel {
  level: number;
  label: string;
  body: string;
}

export interface KeyTerm {
  term: string;
  plain_definition: string;
}

export interface Misconception {
  myth: string;
  reality: string;
}

export interface Diagram {
  title: string;
  kind: "mermaid" | "steps";
  content: string;
  caption: string;
}

export interface NextStep {
  label: string;
  reason: string;
}

export interface HistoricalBackground {
  origin: string;
  motivation: string;
  evolution: string;
}

export interface Contradiction {
  claim: string;
  conflict: string;
  resolution: string;
}

export interface Source {
  title: string;
  url: string;
  publisher: string;
  kind: string;
  reliability: number;
  excerpt: string;
}

export interface CardSummary {
  id: string;
  slug: string;
  title: string;
  one_sentence_answer: string;
  summary: string;
  category: Category | null;
  tags: string[];
  difficulty: "beginner" | "intermediate" | "advanced";
  reading_minutes: number;
  confidence: number;
  curiosity_score: number;
  save_count: number;
  view_count: number;
}

export interface RelatedCard extends CardSummary {
  relation: string;
  reason: string;
}

/**
 * The one picture a card may carry. Null on most cards, and that is the
 * designed state rather than missing data — see `backend/app/ingestion/images.py`.
 * `url` is always a Curio path, never the upstream host.
 */
export interface CardImage {
  url: string;
  alt: string;
  caption: string;
  credit: string;
  license: string;
  license_url: string;
  source_url: string;
  provider: string;
  /** "question" when the asker attached it, "evidence" when a cited source did. */
  origin: string;
  width: number;
  height: number;
}

export interface CardDetail extends CardSummary {
  levels: ExplanationLevel[];
  image: CardImage | null;
  key_terms: KeyTerm[];
  misconceptions: Misconception[];
  why_it_matters: string;
  historical_background: HistoricalBackground;
  diagrams: Diagram[];
  next_steps: NextStep[];
  contradictions: Contradiction[];
  confidence_reason: string;
  sources: Source[];
  related: RelatedCard[];
  origin: string;
  asked_at: AskedAt[];
  verified_at: string | null;
  updated_at: string | null;
}

/** Where a question was observed being asked. Empty for the curated corpus. */
export interface AskedAt {
  source_name: string;
  source_url: string;
  raw_text: string;
  occurrences: number;
  engagement: number;
  first_seen_at: string | null;
}

export interface Shelf {
  key: string;
  title: string;
  subtitle: string;
  cards: CardSummary[];
}

/**
 * The two lenses over the corpus. "interesting" is curiosity for its own sake;
 * "useful" is the subset whose answers change what a reader does.
 */
export type FeedMode = "interesting" | "useful";

export interface DiscoveryFeed {
  shelves: Shelf[];
  generated_at: string;
  mode: FeedMode;
}

export interface SearchResult extends CardSummary {
  matched_by: string[];
  score: number;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
  suggestions: string[];
  semantic: boolean;
}

export interface DiscoveredQuestion {
  id: string;
  raw_text: string;
  source_name: string;
  source_url: string;
  occurrences: number;
  engagement: number;
  first_seen_at: string | null;
  last_seen_at: string | null;
  status: "pending" | "published" | "rejected";
  card_slug: string | null;
  rejected_reason: string;
}

export interface DiscoveryQueue {
  total: number;
  pending: number;
  published: number;
  rejected: number;
  repeated: number;
  sources: { name: string; count: number }[];
  items: DiscoveredQuestion[];
  llm_enabled: boolean;
}

export interface GraphNode {
  id: string;
  slug: string;
  label: string;
  kind: string;
  category: string;
  depth: number;
  confidence: number;
  reading_minutes: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  relation: string;
  weight: number;
  reason: string;
}

export interface GraphData {
  root: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Profile {
  key: string;
  display_name: string;
  interests: Record<string, number>;
  preferred_level: number;
  serendipity: number;
  streak_days: number;
  longest_streak: number;
  last_active_on: string | null;
  notify_daily: boolean;
  notify_hour_utc: number;
  notify_weekly_digest: boolean;
}

export interface Stats {
  cards_read: number;
  cards_saved: number;
  cards_completed: number;
  concepts_explored: number;
  connections_followed: number;
  minutes_learning: number;
  streak_days: number;
  longest_streak: number;
  discoveries_this_week: number;
  top_categories: { slug: string; affinity: number }[];
}

export interface Reexplanation {
  mode: string;
  label: string;
  body: string;
  generated: boolean;
  tried: string[];
}

export interface AiStatus {
  llm_enabled: boolean;
  model: string | null;
  features: {
    reexplain: boolean;
    reexplain_generative: boolean;
    semantic_search: boolean;
    synthesis: boolean;
    ingestion: boolean;
  };
}

export type InteractionKind =
  | "view"
  | "save"
  | "unsave"
  | "complete"
  | "level_reached"
  | "asked_again"
  | "dismissed";
