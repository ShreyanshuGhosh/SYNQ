"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { DailyCostResponse } from "@/lib/api";
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface Props {
  data: DailyCostResponse | null;
  providerFilter: string | null;
}

const RED = "#dc2626";
const GREEN = "#16a34a";

export function DailyCostChart({ data, providerFilter }: Props) {
  const rows = (data?.days ?? []).map((r) => ({
    day: r.day ? new Date(r.day).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "",
    cost_usd: r.cost_usd,
    total_tokens: r.total_tokens,
  }));
  const softLimit = data?.daily_soft_limit_usd ?? 0;

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>
          Daily cost (30d, estimated)
          {providerFilter ? <span className="ml-2 text-xs">— {providerFilter} only*</span> : null}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows}>
              <XAxis dataKey="day" tick={{ fontSize: 11 }} />
              <YAxis
                tickFormatter={(v: number) => `$${v.toFixed(2)}`}
                tick={{ fontSize: 11 }}
                width={50}
              />
              <Tooltip
                formatter={(value: number, name: string) =>
                  name === "cost_usd"
                    ? [`$${value.toFixed(4)}`, "Cost"]
                    : [value.toLocaleString(), name === "total_tokens" ? "Tokens" : name]
                }
                labelStyle={{ color: "#e2e8f0" }}
                contentStyle={{ fontSize: 12 }}
              />
              <Bar dataKey="cost_usd">
                {rows.map((r, i) => (
                  <Cell key={i} fill={softLimit > 0 && r.cost_usd > softLimit ? RED : GREEN} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        {providerFilter && (
          <p className="mt-2 text-[11px] text-slate-500">
            *Provider filter is client-side and approximate — bars currently show total cost.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
