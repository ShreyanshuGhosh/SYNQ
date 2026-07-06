"use client";

import { Card, CardHeader, CardTitle, CardTitleNote, CardContent } from "@/components/ui/card";
import type { ProviderHealth } from "@/lib/api";
import { providerTextClass } from "@/lib/provider-identity";

const STATUS_DOT: Record<ProviderHealth["status"], string> = {
  healthy: "bg-brand-green shadow-[0_0_0_3px_rgba(63,185,112,0.18)]",
  half_open: "bg-amber shadow-[0_0_0_3px_rgba(245,166,35,0.18)]",
  degraded: "bg-red-400 shadow-[0_0_0_3px_rgba(248,113,113,0.18)]",
  unhealthy: "bg-red-400 shadow-[0_0_0_3px_rgba(248,113,113,0.18)]",
  unknown: "bg-faint animate-pulse",
};

const STATUS_LABEL: Record<ProviderHealth["status"], string> = {
  healthy: "healthy",
  half_open: "recovering",
  degraded: "degraded",
  unhealthy: "unhealthy",
  unknown: "checking…",
};

function historyTickClass(status: string | null | undefined): string {
  if (status === "healthy") return "bg-brand-green";
  if (status === "half_open") return "bg-amber";
  if (status === "unhealthy" || status === "degraded") return "bg-red-400";
  return "bg-faint opacity-40"; // no probe yet — designed "pending" state, not a gray "unknown"
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
        <CardTitle>
          Provider status
          <CardTitleNote>live · refreshes 30s</CardTitleNote>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {providers.length === 0 && (
          <p className="font-mono-data text-xs text-faint">No providers configured.</p>
        )}
        <ul>
          {providers.map((p, idx) => {
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
                className={`flex items-center gap-3 py-3.5 ${idx < providers.length - 1 ? "border-b border-line" : ""}`}
              >
                <span className={`h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[p.status]}`} />
                <span className={`w-[70px] shrink-0 text-[13.5px] font-semibold ${providerTextClass(p.provider)}`}>
                  {p.provider}
                </span>
                <span className="flex-1 truncate font-mono-data text-[11px] text-faint">
                  {p.model_used ?? "—"} · {STATUS_LABEL[p.status]}
                </span>
                <span className="flex items-center gap-[3px]" title="Last 5 probe results (newest on the left)">
                  {padded.map((h, i) => (
                    <span key={i} className={`h-3.5 w-1 rounded-sm ${historyTickClass(h.status)}`} />
                  ))}
                </span>
                <span className="w-[92px] shrink-0 text-right font-mono-data text-xs text-dim">
                  {p.latency_ms != null ? `${p.latency_ms}ms` : relativeSince(p.checked_at)}
                </span>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}
