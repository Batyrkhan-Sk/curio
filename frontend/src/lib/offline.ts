"use client";

import Dexie, { type EntityTable } from "dexie";
import type { CardDetail, CardSummary } from "./types";

/**
 * Offline storage for saved cards.
 *
 * The service worker caches shell and API responses opportunistically, but a
 * card the reader deliberately saved must be guaranteed available with no
 * network — so those go in IndexedDB as full records rather than relying on
 * cache eviction policy.
 */

interface StoredCard {
  id: string;
  slug: string;
  savedAt: number;
  card: CardDetail;
}

const db = new Dexie("curio") as Dexie & {
  cards: EntityTable<StoredCard, "id">;
};

db.version(1).stores({
  cards: "id, slug, savedAt",
});

export async function saveOffline(card: CardDetail): Promise<void> {
  await db.cards.put({
    id: card.id,
    slug: card.slug,
    savedAt: Date.now(),
    card,
  });
}

export async function removeOffline(id: string): Promise<void> {
  await db.cards.delete(id);
}

export async function isOffline(id: string): Promise<boolean> {
  return (await db.cards.get(id)) !== undefined;
}

export async function readOffline(slug: string): Promise<CardDetail | null> {
  const record = await db.cards.where("slug").equals(slug).first();
  return record?.card ?? null;
}

export async function listOffline(): Promise<CardSummary[]> {
  const records = await db.cards.orderBy("savedAt").reverse().toArray();
  return records.map((record) => record.card);
}

export async function offlineCount(): Promise<number> {
  return db.cards.count();
}
