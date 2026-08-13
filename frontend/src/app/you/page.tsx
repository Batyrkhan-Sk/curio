"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { CardSummary, Profile, Stats } from "@/lib/types";
import { QuestionCard } from "@/components/discovery/question-card";
import { NotificationSettings } from "@/components/pwa/notification-settings";
import { Card, SectionLabel, Skeleton } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/icon";
import { getProfile, getRecommendations, getStats, updateProfile } from "@/lib/api";
import { pluralize } from "@/lib/utils";

export default function YouPage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [picks, setPicks] = useState<CardSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      getProfile().catch(() => null),
      getStats().catch(() => null),
      getRecommendations(6).catch(() => []),
    ]).then(([p, s, r]) => {
      setProfile(p);
      setStats(s);
      setPicks(r);
      setLoading(false);
    });
  }, []);

  async function setSerendipity(value: number) {
    if (!profile) return;
    setProfile({ ...profile, serendipity: value });
    const updated = await updateProfile({ serendipity: value }).catch(() => null);
    if (updated) setProfile(updated);
    getRecommendations(6).then(setPicks).catch(() => {});
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-3xl space-y-4 px-5 py-8 sm:px-8">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-5 py-8 sm:px-8">
      <header className="mb-8">
        <h1 className="font-serif text-2xl font-medium tracking-[-0.01em]">
          Your curiosity
        </h1>
        <p className="mt-1.5 text-sm text-text-secondary">
          No account, no password. This device holds a random key that Curio
          uses to remember what you&rsquo;ve read.
        </p>
      </header>

      {stats && <StatGrid stats={stats} />}

      {picks.length > 0 && (
        <section className="mt-10">
          <SectionLabel className="mb-4">Picked up from what you&rsquo;ve read</SectionLabel>
          <div className="grid gap-4 sm:grid-cols-2">
            {picks.slice(0, 4).map((card) => (
              <QuestionCard key={card.id} card={card} size="sm" />
            ))}
          </div>
        </section>
      )}

      {profile && (
        <section className="mt-10">
          <SectionLabel className="mb-4">How much to surprise you</SectionLabel>
          <Card className="p-5">
            <p className="text-[13px] leading-relaxed text-text-secondary">
              A fixed share of what Curio shows you is deliberately drawn from
              subjects you have never touched. You can raise it, but not turn it
              off — an interest model that only ever confirms itself stops being
              useful within a week.
            </p>
            <div className="mt-4 flex items-center gap-4">
              <input
                type="range"
                min={15}
                max={80}
                step={5}
                value={Math.round(profile.serendipity * 100)}
                onChange={(event) =>
                  setSerendipity(Number(event.target.value) / 100)
                }
                className="h-1.5 flex-1 cursor-pointer appearance-none rounded-full bg-surface-3 accent-[--color-accent]"
                aria-label="Share of unfamiliar subjects"
              />
              <span className="w-28 shrink-0 text-right text-[13px] tabular-nums text-text-muted">
                {Math.round(profile.serendipity * 100)}% unfamiliar
              </span>
            </div>
          </Card>
        </section>
      )}

      {profile && Object.keys(profile.interests).length > 0 && (
        <section className="mt-10">
          <SectionLabel className="mb-4">What Curio thinks you like</SectionLabel>
          <div className="space-y-2">
            {Object.entries(profile.interests)
              .sort(([, a], [, b]) => b - a)
              .slice(0, 6)
              .map(([slug, affinity]) => (
                <div key={slug} className="flex items-center gap-3">
                  <Link
                    href={`/categories/${slug}`}
                    className="w-32 shrink-0 truncate text-[13px] capitalize text-text-secondary hover:text-text"
                  >
                    {slug.replace(/-/g, " ")}
                  </Link>
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
                    <div
                      className="h-full rounded-full bg-accent transition-[width] duration-500"
                      style={{ width: `${Math.min(100, affinity * 100)}%` }}
                    />
                  </div>
                </div>
              ))}
          </div>
        </section>
      )}

      <section className="mt-10">
        <SectionLabel className="mb-4">Notifications</SectionLabel>
        <Card className="p-5">
          <NotificationSettings
            initialHour={profile?.notify_hour_utc ?? 17}
            initialEnabled={profile?.notify_daily ?? true}
          />
        </Card>
      </section>

      {profile && (
        <section className="mt-10">
          <SectionLabel className="mb-4">Sync to another device</SectionLabel>
          <Card className="p-5">
            <p className="text-[13px] leading-relaxed text-text-secondary">
              Paste this key into Curio on another device to carry your history
              across. Treat it like a password — anyone with it sees what
              you&rsquo;ve read.
            </p>
            <code className="mt-3 block overflow-x-auto rounded-lg bg-surface-2 px-3 py-2 font-mono text-[12px] text-text-muted">
              {profile.key}
            </code>
          </Card>
        </section>
      )}
    </div>
  );
}

function StatGrid({ stats }: { stats: Stats }) {
  // Counts of real learning, not points. Nothing here can be farmed by
  // opening pages and closing them.
  const tiles = [
    { label: "Questions read", value: stats.cards_read, icon: "BookOpen" },
    { label: "Understood", value: stats.cards_completed, icon: "CircleCheck" },
    { label: "Concepts met", value: stats.concepts_explored, icon: "Waypoints" },
    { label: "Minutes learning", value: stats.minutes_learning, icon: "Clock" },
  ];

  return (
    <>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {tiles.map((tile) => (
          <Card key={tile.label} className="p-4">
            <Icon name={tile.icon} className="size-4 text-text-faint" />
            <p className="mt-3 text-2xl font-medium tabular-nums tracking-tight">
              {tile.value}
            </p>
            <p className="mt-0.5 text-[11px] text-text-muted">{tile.label}</p>
          </Card>
        ))}
      </div>

      {stats.streak_days > 1 && (
        <p className="mt-3 flex items-center gap-2 text-[13px] text-text-muted">
          <Icon name="Flame" className="size-3.5 text-accent" />
          {pluralize(stats.streak_days, "day")} in a row
          {stats.longest_streak > stats.streak_days &&
            ` · longest ${stats.longest_streak}`}
        </p>
      )}
    </>
  );
}
