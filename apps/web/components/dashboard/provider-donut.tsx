"use client";

import { Card, CardHeader, CardTitle, CardTitleNote, CardContent } from "@/components/ui/card";
import type { ProviderShareResponse } from "@/lib/api";
import { providerDotClass } from "@/lib/provider-identity";

interface Props {
  data: ProviderShareResponse | null;
  onSelectProvider: (provider: string | null) => void;
  selectedProvider: string | null;
}

/**
 * Horizontal bars instead of a donut: this app's provider splits are
 * routinely skewed (97/3/0 is typical for a single fallback chain), and
 * lopsided slices are unreadable in a pie. Bars keep every share legible
 * regardless of magnitude.
 */
export function ProviderDonut({ data, onSelectProvider, selectedProvider }: Props) {
  const rows = data?.providers ?? [];
  const totalCost = rows.reduce((s, r) => s + r.cost_usd, 0);

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>
          Spend by provider
          <CardTitleNote>this month</CardTitleNote>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="py-8 font-mono-data text-xs text-faint">No spend recorded yet.</p>
        ) : (
          <div className="space-y-4 py-1">
            {rows.map((r) => {
              const isSelected = selectedProvider === r.provider;
              const barPct = Math.max(r.pct, r.pct > 0 ? 2 : 0);
              return (
                <button
                  key={r.provider}
                  onClick={() => onSelectProvider(isSelected ? null : r.provider)}
                  className={`flex w-full items-center gap-3 rounded-md px-1 py-0.5 text-left transition-colors ${
                    isSelected ? "bg-panel-2" : "hover:bg-panel-2/60"
                  }`}
                >
                  <span className="w-16 shrink-0 font-mono-data text-xs text-ink">{r.provider}</span>
                  <span className="h-3.5 flex-1 overflow-hidden rounded bg-line">
                    <span
                      className={`block h-full rounded ${providerDotClass(r.provider)}`}
                      style={{ width: `${barPct}%` }}
                    />
                  </span>
                  <span className="w-14 shrink-0 text-right font-mono-data text-xs text-ink">
                    {r.pct.toFixed(1)}%
                  </span>
                </button>
              );
            })}
          </div>
        )}
        <p className="mt-2 font-mono-data text-[11px] text-faint">
          total ${totalCost.toFixed(2)} · free-tier providers show cost at list price
        </p>
        {selectedProvider && (
          <p className="mt-1 font-mono-data text-[11px] text-faint">
            Filtering daily cost by {selectedProvider} — click again to clear.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
