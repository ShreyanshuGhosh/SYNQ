"use client";

import { Card, CardHeader, CardTitle, CardTitleNote, CardContent } from "@/components/ui/card";
import type { DailyCostResponse } from "@/lib/api";
import {
  Bar,
  BarChart,
  CartesianGrid,
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

const RED = "#f87171";
const GEMINI = "#6ea8ff";
const TEAL = "#2fbfae";
const GRID = "#1a2230";
const AXIS = "#5b6577";

export function DailyCostChart({ data, providerFilter }: Props) {
  const rows = (data?.days ?? []).map((r) => ({
    day: r.day ? new Date(r.day).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "",
    cost_usd: r.cost_usd,
    total_tokens: r.total_tokens,
  }));
  const softLimit = data?.daily_soft_limit_usd ?? 0;
  const lastIndex = rows.length - 1;

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>
          Daily cost
          <CardTitleNote>
            30d · estimated{providerFilter ? ` · ${providerFilter} only*` : ""}
          </CardTitleNote>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-64 font-mono-data">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows}>
              <CartesianGrid stroke={GRID} strokeDasharray="3 4" vertical={false} />
              <XAxis dataKey="day" tick={{ fontSize: 10, fill: AXIS }} axisLine={{ stroke: GRID }} tickLine={false} />
              <YAxis
                tickFormatter={(v: number) => `$${v.toFixed(2)}`}
                tick={{ fontSize: 10, fill: AXIS }}
                width={54}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                formatter={(value: number, name: string) =>
                  name === "cost_usd"
                    ? [`$${value.toFixed(4)}`, "Cost"]
                    : [value.toLocaleString(), name === "total_tokens" ? "Tokens" : name]
                }
                contentStyle={{
                  fontSize: 12,
                  background: "#151b26",
                  border: "1px solid #2b3648",
                  borderRadius: 8,
                  color: "#e7eaf0",
                }}
                labelStyle={{ color: "#e7eaf0" }}
                cursor={{ fill: "rgba(255,255,255,0.03)" }}
              />
              <Bar dataKey="cost_usd" radius={[3, 3, 0, 0]}>
                {rows.map((r, i) => {
                  const overLimit = softLimit > 0 && r.cost_usd > softLimit;
                  const isToday = i === lastIndex;
                  const fill = overLimit ? RED : isToday ? TEAL : GEMINI;
                  return <Cell key={i} fill={fill} opacity={isToday ? 1 : 0.85} />;
                })}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-3.5 flex gap-4 font-mono-data text-[11.5px] text-dim">
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: GEMINI }} />
            previous days
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: TEAL }} />
            today
          </span>
          {softLimit > 0 && (
            <span className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: RED }} />
              over soft limit
            </span>
          )}
        </div>
        {providerFilter && (
          <p className="mt-2 font-mono-data text-[11px] text-faint">
            *Provider filter is client-side and approximate — bars currently show total cost.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
