"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { ProviderShareResponse } from "@/lib/api";
import {
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

const COLORS = ["#2563eb", "#9333ea", "#dc2626", "#16a34a", "#ea580c", "#0891b2"];

interface Props {
  data: ProviderShareResponse | null;
  onSelectProvider: (provider: string | null) => void;
  selectedProvider: string | null;
}

export function ProviderDonut({ data, onSelectProvider, selectedProvider }: Props) {
  const rows = data?.providers ?? [];
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>Spend by provider (this month)</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={rows}
                dataKey="cost_usd"
                nameKey="provider"
                innerRadius={50}
                outerRadius={85}
                paddingAngle={2}
                onClick={(slice) => {
                  if (!slice) return;
                  const p = (slice as { name?: string }).name ?? null;
                  onSelectProvider(selectedProvider === p ? null : p);
                }}
              >
                {rows.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} cursor="pointer" />
                ))}
              </Pie>
              <Tooltip
                formatter={(value: number, name: string, raw) => {
                  const pct = (raw && (raw as { payload?: { pct?: number } }).payload?.pct) ?? 0;
                  return [`$${value.toFixed(4)} (${pct}%)`, name];
                }}
                contentStyle={{ fontSize: 12 }}
              />
              <Legend
                formatter={(_value, _entry, index) => {
                  const row = rows[index];
                  if (!row) return "";
                  return `${row.provider} · $${row.cost_usd.toFixed(2)} · ${row.pct}%`;
                }}
                wrapperStyle={{ fontSize: 11 }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
        {selectedProvider && (
          <p className="mt-1 text-[11px] text-slate-500">
            Filtering Panel B by {selectedProvider} — click slice again to clear.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
