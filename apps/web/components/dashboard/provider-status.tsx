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
          <p className="text-sm text-gray-500">No providers configured.</p>
        )}
        <ul className="space-y-2">
          {providers.map((p) => (
            <li
              key={p.provider}
              className="flex items-center justify-between rounded-md border border-gray-100 px-3 py-2 dark:border-gray-800"
            >
              <div className="flex items-center gap-3">
                <span className={`inline-block h-3 w-3 rounded-full ${DOT_CLASS[p.status]}`} />
                <div>
                  <div className="text-sm font-medium">{p.provider}</div>
                  <div className="text-xs text-gray-500">
                    {p.model_used ?? "—"} · {p.status}
                  </div>
                </div>
              </div>
              <div className="text-right text-xs text-gray-500">
                <div>{p.latency_ms != null ? `${p.latency_ms}ms` : "—"}</div>
                <div>{relativeSince(p.checked_at)}</div>
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
