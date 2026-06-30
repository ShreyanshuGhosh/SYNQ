"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { LimitsResponse, StatsToday } from "@/lib/api";

interface Props {
  stats: StatsToday | null;
  limits: LimitsResponse | null;
}

function costColorClass(today: number, softLimit: number, blocked: boolean): string {
  if (blocked) return "text-red-600 dark:text-red-400";
  if (softLimit > 0 && today > softLimit) return "text-red-600 dark:text-red-400";
  if (softLimit > 0 && today > softLimit / 2) return "text-amber-600 dark:text-amber-400";
  return "text-emerald-600 dark:text-emerald-400";
}

export function StatRow({ stats, limits }: Props) {
  const today = stats?.today_cost_usd ?? 0;
  const softLimit = limits?.daily_soft_limit_usd ?? stats?.daily_soft_limit_usd ?? 0;
  const blocked = limits?.hard_limit_blocked ?? false;
  const colorClass = costColorClass(today, softLimit, blocked);

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <Card>
        <CardHeader>
          <CardTitle>Today (est. cost)</CardTitle>
        </CardHeader>
        <CardContent>
          <div className={`text-3xl font-semibold ${colorClass}`}>
            ${today.toFixed(4)}
          </div>
          <div className="mt-1 text-xs text-slate-500">
            soft limit ${softLimit.toFixed(2)}
            {limits?.hard_daily_limit_usd != null && (
              <> · hard limit ${limits.hard_daily_limit_usd.toFixed(2)}</>
            )}
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Turns today</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-3xl font-semibold">{stats?.turns_today ?? 0}</div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Fallbacks today</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-3xl font-semibold">{stats?.fallbacks_today ?? 0}</div>
          <div className="mt-1 text-xs text-slate-500">
            provider switched automatically
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Manual switches</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-3xl font-semibold">{stats?.manual_switches_today ?? 0}</div>
        </CardContent>
      </Card>
    </div>
  );
}
