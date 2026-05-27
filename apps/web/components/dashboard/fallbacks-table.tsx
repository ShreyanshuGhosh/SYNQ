"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { FallbackResponse } from "@/lib/api";
import Link from "next/link";

const REASON_BADGE: Record<string, string> = {
  rate_limit: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  overloaded: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  manual_switch: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  server: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
  transport: "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200",
};

function reasonClass(reason: string | null): string {
  if (!reason) return "bg-gray-100 text-gray-800";
  return REASON_BADGE[reason] ?? "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200";
}

function relativeTs(ts: string | null): string {
  if (!ts) return "—";
  const ms = Date.now() - new Date(ts).getTime();
  if (ms < 60_000) return `${Math.round(ms / 1000)}s ago`;
  if (ms < 3_600_000) return `${Math.round(ms / 60_000)}m ago`;
  if (ms < 86_400_000) return `${Math.round(ms / 3_600_000)}h ago`;
  return `${Math.round(ms / 86_400_000)}d ago`;
}

interface Props {
  data: FallbackResponse | null;
}

export function FallbacksTable({ data }: Props) {
  const rows = data?.fallbacks ?? [];
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>Recent fallbacks</CardTitle>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-gray-500">No fallbacks recorded. Nice.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-gray-200 text-left text-xs uppercase text-gray-500 dark:border-gray-800">
                <tr>
                  <th className="py-2">When</th>
                  <th className="py-2">From → To</th>
                  <th className="py-2">Reason</th>
                  <th className="py-2">Latency</th>
                  <th className="py-2">Conversation</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} className="border-b border-gray-100 dark:border-gray-900">
                    <td className="py-2 text-gray-600">{relativeTs(r.ts)}</td>
                    <td className="py-2">
                      <span className="font-mono text-xs">{r.fallback_from ?? "—"}</span>
                      <span className="mx-1 text-gray-400">→</span>
                      <span className="font-mono text-xs">{r.fallback_to ?? "—"}</span>
                    </td>
                    <td className="py-2">
                      <span
                        className={`rounded px-2 py-0.5 text-xs font-medium ${reasonClass(r.fallback_reason)}`}
                      >
                        {r.fallback_reason ?? "unknown"}
                      </span>
                    </td>
                    <td className="py-2 text-gray-600">
                      {r.latency_ms != null ? `${r.latency_ms}ms` : "—"}
                    </td>
                    <td className="py-2">
                      {r.conversation_id ? (
                        <Link
                          href={`/chat/${r.conversation_id}`}
                          className="font-mono text-xs text-blue-600 underline-offset-2 hover:underline"
                        >
                          {r.conversation_id.slice(0, 8)}…
                        </Link>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
