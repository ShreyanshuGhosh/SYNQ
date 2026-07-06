"use client";

import { Card, CardHeader, CardTitle, CardTitleNote, CardContent } from "@/components/ui/card";
import type { HourlyTokenResponse } from "@/lib/api";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface Props {
  data: HourlyTokenResponse | null;
}

const GEMINI = "#6ea8ff";
const MISTRAL = "#57c99b";
const GRID = "#1a2230";
const AXIS = "#5b6577";

export function TokensChart({ data }: Props) {
  const rows = (data?.hours ?? []).map((r) => ({
    hour: r.hour
      ? new Date(r.hour).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit" })
      : "",
    prompt: r.prompt,
    completion: r.completion,
  }));
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>
          Tokens over time
          <CardTitleNote>7 days · hourly</CardTitleNote>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-64 font-mono-data">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows}>
              <CartesianGrid stroke={GRID} strokeDasharray="3 4" vertical={false} />
              <XAxis
                dataKey="hour"
                tick={{ fontSize: 10, fill: AXIS }}
                interval="preserveStartEnd"
                axisLine={{ stroke: GRID }}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 10, fill: AXIS }}
                width={54}
                tickFormatter={(v: number) => v.toLocaleString()}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                contentStyle={{
                  fontSize: 12,
                  background: "#151b26",
                  border: "1px solid #2b3648",
                  borderRadius: 8,
                  color: "#e7eaf0",
                }}
              />
              <Line type="monotone" dataKey="prompt" stroke={GEMINI} strokeWidth={2} dot={false} name="Prompt" />
              <Line type="monotone" dataKey="completion" stroke={MISTRAL} strokeWidth={2} dot={false} name="Completion" />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-3.5 flex gap-4 font-mono-data text-[11.5px] text-dim">
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: GEMINI }} />
            prompt tokens
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: MISTRAL }} />
            completion tokens
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
