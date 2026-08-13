import type {
  AiStatus,
  CardDetail,
  CardSummary,
  Category,
  DiscoveryFeed,
  DiscoveryQueue,
  FeedMode,
  GraphData,
  Profile,
  Reexplanation,
  SearchResponse,
  Shelf,
  Stats,
} from "./types";

/**
 * Server components talk to the API container directly; the browser goes
 * through the Next.js rewrite so everything stays same-origin (see
 * next.config.ts for why that matters to the service worker).
 */
const SERVER_BASE = process.env.API_URL ?? "http://localhost:8000";
const isServer = typeof window === "undefined";

export const PROFILE_HEADER = "X-Curio-Profile";
export const PROFILE_STORAGE_KEY = "curio.profile";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function url(path: string): string {
  return isServer ? `${SERVER_BASE}${path}` : path;
}

export function readProfileKey(): string | null {
  if (isServer) return null;
  try {
    return window.localStorage.getItem(PROFILE_STORAGE_KEY);
  } catch {
    // Private browsing modes can throw on localStorage access. The app is
    // fully usable without a profile, so this is not worth surfacing.
    return null;
  }
}

export function writeProfileKey(key: string): void {
  if (isServer) return;
  try {
    window.localStorage.setItem(PROFILE_STORAGE_KEY, key);
  } catch {
    /* ignore */
  }
}

interface RequestOptions extends RequestInit {
  /** Skip Next.js caching for reader-specific data. */
  fresh?: boolean;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { fresh, ...init } = options;
  const headers = new Headers(init.headers);

  const profileKey = readProfileKey();
  if (profileKey) headers.set(PROFILE_HEADER, profileKey);
  if (init.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }

  const response = await fetch(url(path), {
    ...init,
    headers,
    cache: fresh ? "no-store" : init.cache,
    next: fresh ? undefined : init.next,
  });

  // The server mints a profile key on first contact and echoes it back.
  const returnedKey = response.headers.get(PROFILE_HEADER);
  if (returnedKey && returnedKey !== profileKey) writeProfileKey(returnedKey);

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

// --- Discovery -------------------------------------------------------------

export const getFeed = (perShelf = 8, mode: FeedMode = "interesting") =>
  request<DiscoveryFeed>(
    `/api/v1/discovery/feed?per_shelf=${perShelf}&mode=${mode}`,
    { next: { revalidate: 120 } },
  );

export const getShelf = (key: string, limit = 24, mode: FeedMode = "interesting") =>
  request<Shelf>(`/api/v1/discovery/shelf/${key}?limit=${limit}&mode=${mode}`, {
    next: { revalidate: 120 },
  });

export const getDiscoveryQueue = (status = "all", limit = 120, offset = 0) =>
  request<DiscoveryQueue>(
    `/api/v1/discovery/questions?status=${status}&limit=${limit}&offset=${offset}`,
    { next: { revalidate: 60 } },
  );

export const getRandomCard = (mode: FeedMode = "interesting") =>
  request<CardSummary>(`/api/v1/discovery/random?mode=${mode}`, { fresh: true });

// --- Cards -----------------------------------------------------------------

export const getCard = (slug: string) =>
  request<CardDetail>(`/api/v1/cards/${slug}`, { next: { revalidate: 60 } });

export const getCardGraph = (slug: string, depth = 2) =>
  request<GraphData>(`/api/v1/cards/${slug}/graph?depth=${depth}`, {
    next: { revalidate: 300 },
  });

export const listCards = (params: Record<string, string | number> = {}) => {
  const query = new URLSearchParams(
    Object.entries(params).map(([k, v]) => [k, String(v)]),
  );
  return request<CardSummary[]>(`/api/v1/cards?${query}`, {
    next: { revalidate: 120 },
  });
};

export const getCategories = () =>
  request<Category[]>("/api/v1/categories", { next: { revalidate: 600 } });

// --- Search ----------------------------------------------------------------

export const search = (query: string, category?: string) => {
  const params = new URLSearchParams({ q: query });
  if (category) params.set("category", category);
  return request<SearchResponse>(`/api/v1/search?${params}`, { fresh: true });
};

export const suggest = (query: string) =>
  request<string[]>(`/api/v1/search/suggest?q=${encodeURIComponent(query)}`, {
    fresh: true,
  });

// --- AI --------------------------------------------------------------------

export const getAiStatus = () =>
  request<AiStatus>("/api/v1/ai/status", { next: { revalidate: 300 } });

export const reexplain = (
  slug: string,
  body: { tried: string[]; last_response?: string; mode?: string },
) =>
  request<Reexplanation>(`/api/v1/ai/cards/${slug}/reexplain`, {
    method: "POST",
    body: JSON.stringify(body),
    fresh: true,
  });

export const requestSynthesis = (question: string) =>
  request<{ status: string; slug: string }>("/api/v1/ai/synthesize", {
    method: "POST",
    body: JSON.stringify({ question, background: true }),
    fresh: true,
  });

// --- Reader ----------------------------------------------------------------

export const getProfile = () => request<Profile>("/api/v1/me", { fresh: true });

export const updateProfile = (patch: Partial<Profile>) =>
  request<Profile>("/api/v1/me", {
    method: "PATCH",
    body: JSON.stringify(patch),
    fresh: true,
  });

export const recordInteraction = (body: {
  card_id: string;
  kind: string;
  level?: number;
  seconds?: number;
}) =>
  request<void>("/api/v1/me/interactions", {
    method: "POST",
    body: JSON.stringify(body),
    fresh: true,
  });

export const getSaved = () =>
  request<CardSummary[]>("/api/v1/me/saved", { fresh: true });

export const getStats = () => request<Stats>("/api/v1/me/stats", { fresh: true });

export const getRecommendations = (limit = 12) =>
  request<CardSummary[]>(`/api/v1/me/recommendations?limit=${limit}`, {
    fresh: true,
  });

// --- Push ------------------------------------------------------------------

export const getPushKey = () =>
  request<{ public_key: string; enabled: boolean }>("/api/v1/me/push/key", {
    fresh: true,
  });

export const subscribePush = (subscription: PushSubscriptionJSON) =>
  request<{ status: string }>("/api/v1/me/push/subscribe", {
    method: "POST",
    body: JSON.stringify({
      endpoint: subscription.endpoint,
      keys: subscription.keys,
      user_agent: navigator.userAgent,
    }),
    fresh: true,
  });

export const unsubscribePush = (endpoint: string) =>
  request<void>(
    `/api/v1/me/push/subscribe?endpoint=${encodeURIComponent(endpoint)}`,
    { method: "DELETE", fresh: true },
  );

export const sendTestPush = () =>
  request<{ delivered: number; title: string; body: string }>(
    "/api/v1/me/push/test",
    { method: "POST", fresh: true },
  );
