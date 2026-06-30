"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { ProviderHealth } from "@/lib/api";

const DOT_CLASS: Record<ProviderHealth["status"], string> = {
  healthy: "bg-emerald-500",
  half_open: "bg-amber-500",
  degraded: "bg-red-500",
  unhealthy: "bg-red-500",
  unknown: "bg-gray-400",
};

function historyDotClass(status: string | null | undefined): string {
  if (status === "healthy") return "bg-emerald-500";
  if (status === "half_open") return "bg-amber-500";
  if (status === "unhealthy" || status === "degraded") return "bg-red-500";
  return "bg-gray-400";
}

function relativeSince(checkedAt: number | null): string {
  if (!checkedAt) return "no data";
  const ms = Date.now() - checkedAt * 1000;
  if (ms < 0) return "now";
  if (ms < 60_000) return `${Math.round(ms / 1000)}s ago`;
  if (ms < 3_600_000) return `${Math.round(ms / 60_000)}m ago`;
  return `${Math.round(ms / 3_600_000)}h ago`;
}

interface Props {
  providers: ProviderHealth[];
}

export function ProviderStatus({ providers }: Props) {
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>Provider status (live, refreshes every 30s)</CardTitle>
      </CardHeader>
      <CardContent>
        {providers.length === 0 && (
          <p className="text-sm text-slate-500">No providers configured.</p>
        )}
        <ul className="space-y-2">
          {providers.map((p) => {
            // Newest first from the API; pad with grey dots so every row
            // always shows exactly 5 slots — easier to spot a pattern.
            const history = (p.history ?? []).slice(0, 5);
            const padded = [
              ...history,
              ...Array.from({ length: Math.max(0, 5 - history.length) }, () => ({
                status: null,
                latency_ms: null,
                checked_at: null,
              })),
            ];
            return (
              <li
                key={p.provider}
                className="flex items-center justify-between rounded-lg border border-white/[0.07] bg-[#111b30] px-3 py-2"
              >
                <div className="flex items-center gap-3">
                  <span className={`inline-block h-3 w-3 rounded-full ${DOT_CLASS[p.status]}`} />
                  <div>
                    <div className="text-sm font-medium text-white">{p.provider}</div>
                    <div className="text-xs text-slate-500">
                      {p.model_used ?? "—"} · {p.status}
                    </div>
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <div
                    className="flex items-center gap-1"
                    title="Last 5 probe results (newest on the left)"
                  >
                    {padded.map((h, i) => (
                      <span
                        key={i}
                        className={`inline-block h-1.5 w-1.5 rounded-full ${historyDotClass(h.status)}`}
                      />
                    ))}
                  </div>
                  <div className="text-right text-xs text-slate-500">
                    <span>{p.latency_ms != null ? `${p.latency_ms}ms` : "—"}</span>
                    <span className="ml-2">{relativeSince(p.checked_at)}</span>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}
