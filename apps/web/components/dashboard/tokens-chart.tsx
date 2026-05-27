"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { HourlyTokenResponse } from "@/lib/api";
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Legend,
} from "recharts";

interface Props {
  data: HourlyTokenResponse | null;
}

export function TokensChart({ data }: Props) {
  const rows = (data?.hours ?? []).map((r) => ({
    hour: r.hour
      ? new Date(r.hour).toLocaleString(undefined, {
          month: "short",
          day: "numeric",
          hour: "2-digit",
        })
      : "",
    prompt: r.prompt,
    completion: r.completion,
  }));
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>Tokens over time (7 days, hourly)</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows}>
              <XAxis dataKey="hour" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 11 }} width={60} tickFormatter={(v: number) => v.toLocaleString()} />
              <Tooltip contentStyle={{ fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line type="monotone" dataKey="prompt" stroke="#2563eb" dot={false} name="Prompt" />
              <Line type="monotone" dataKey="completion" stroke="#16a34a" dot={false} name="Completion" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
