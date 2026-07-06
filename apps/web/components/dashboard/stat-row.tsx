"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { LimitsResponse, StatsToday } from "@/lib/api";

interface Props {
  stats: StatsToday | null;
  limits: LimitsResponse | null;
}

function costColorClass(today: number, softLimit: number, blocked: boolean): string {
  if (blocked) return "text-red-400";
  if (softLimit > 0 && today > softLimit) return "text-red-400";
  if (softLimit > 0 && today > softLimit / 2) return "text-amber";
  return "text-brand-green";
}

function StatCard({
  label,
  value,
  valueClass,
  foot,
  children,
}: {
  label: string;
  value: string | number;
  valueClass?: string;
  foot?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="pb-0">
        <CardTitle className="font-sans text-xs font-medium text-dim">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className={`font-mono-data text-[26px] font-semibold ${valueClass ?? "text-ink"}`}>{value}</div>
        {children}
        {foot && <div className="mt-2 font-mono-data text-[11.5px] text-faint">{foot}</div>}
      </CardContent>
    </Card>
  );
}

export function StatRow({ stats, limits }: Props) {
  const today = stats?.today_cost_usd ?? 0;
  const softLimit = limits?.daily_soft_limit_usd ?? stats?.daily_soft_limit_usd ?? 0;
  const blocked = limits?.hard_limit_blocked ?? false;
  const colorClass = costColorClass(today, softLimit, blocked);
  const meterPct = softLimit > 0 ? Math.min(100, (today / softLimit) * 100) : 0;

  return (
    <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
      <StatCard
        label="Today (est. cost)"
        value={`$${today.toFixed(4)}`}
        valueClass={colorClass}
        foot={
          <>
            soft limit ${softLimit.toFixed(2)}
            {limits?.hard_daily_limit_usd != null && <> · hard limit ${limits.hard_daily_limit_usd.toFixed(2)}</>}
          </>
        }
      >
        {softLimit > 0 && (
          <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-line">
            <div
              className={`h-full rounded-full ${blocked || today > softLimit ? "bg-red-400" : "bg-brand-green"}`}
              style={{ width: `${meterPct}%` }}
            />
          </div>
        )}
      </StatCard>

      <StatCard label="Turns today" value={stats?.turns_today ?? 0} />

      <StatCard
        label="Fallbacks today"
        value={stats?.fallbacks_today ?? 0}
        foot="provider switched automatically"
      />

      <StatCard label="Manual switches" value={stats?.manual_switches_today ?? 0} foot="you picked a different model" />
    </div>
  );
}
