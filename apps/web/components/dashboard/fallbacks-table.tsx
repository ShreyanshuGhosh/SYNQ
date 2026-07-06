"use client";

import { Card, CardHeader, CardTitle, CardTitleNote, CardContent } from "@/components/ui/card";
import type { FallbackResponse } from "@/lib/api";
import Link from "next/link";

function relativeTs(ts: string | null): string {
  if (!ts) return "—";
  const ms = Date.now() - new Date(ts).getTime();
  if (ms < 60_000) return `${Math.round(ms / 1000)}s ago`;
  if (ms < 3_600_000) return `${Math.round(ms / 60_000)}m ago`;
  if (ms < 86_400_000) return `${Math.round(ms / 3_600_000)}h ago`;
  return `${Math.round(ms / 86_400_000)}d ago`;
}

function timeOfDay(ts: string | null): string {
  if (!ts) return "—";
  return new Date(ts).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

interface Props {
  data: FallbackResponse | null;
}

export function FallbacksTable({ data }: Props) {
  const rows = data?.fallbacks ?? [];
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>
          Recent fallbacks
          <CardTitleNote>last 24h</CardTitleNote>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="font-mono-data text-xs text-faint">No fallbacks recorded — every turn stayed on its provider.</p>
        ) : (
          <div>
            {rows.map((r, i) => (
              <div
                key={i}
                className={`flex gap-3 py-3 text-[12.5px] ${i < rows.length - 1 ? "border-b border-line" : ""}`}
              >
                <span className="w-11 shrink-0 pt-0.5 font-mono-data text-[11px] text-faint" title={relativeTs(r.ts)}>
                  {timeOfDay(r.ts)}
                </span>
                <div className="min-w-0 flex-1">
                  <span className="font-semibold text-ink">{r.fallback_from ?? "—"}</span>
                  <span className="text-faint"> → </span>
                  <span className="font-semibold text-ink">{r.fallback_to ?? "—"}</span>
                  {r.conversation_id && (
                    <Link
                      href={`/chat/${r.conversation_id}`}
                      className="ml-2 font-mono-data text-[10.5px] text-teal hover:underline"
                    >
                      {r.conversation_id.slice(0, 8)}…
                    </Link>
                  )}
                  <div className="mt-0.5 font-mono-data text-[11.5px] text-dim">
                    {r.fallback_reason ?? "unknown"}
                    {r.latency_ms != null && ` · ${r.latency_ms}ms`}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
