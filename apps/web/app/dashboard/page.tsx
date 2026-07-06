"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import {
  dash,
  type DailyCostResponse,
  type FallbackResponse,
  type FlagsResponse,
  type HourlyTokenResponse,
  type LimitsResponse,
  type ProviderHealth,
  type ProviderShareResponse,
  type RouterChainResponse,
  type StatsToday,
} from "@/lib/api";
import { ProviderDot } from "@/components/provider-dot";
import { StatRow } from "@/components/dashboard/stat-row";
import { DailyCostChart } from "@/components/dashboard/daily-cost-chart";
import { ProviderDonut } from "@/components/dashboard/provider-donut";
import { ProviderStatus } from "@/components/dashboard/provider-status";
import { FallbacksTable } from "@/components/dashboard/fallbacks-table";
import { TokensChart } from "@/components/dashboard/tokens-chart";
import { FlagsPanel } from "@/components/dashboard/flags-panel";

export default function DashboardPage() {
  const { getToken, isSignedIn } = useAuth();
  const tokenRef = useRef(getToken);
  tokenRef.current = getToken;
  const t = useCallback(() => tokenRef.current(), []);

  const [stats, setStats] = useState<StatsToday | null>(null);
  const [limits, setLimits] = useState<LimitsResponse | null>(null);
  const [chain, setChain] = useState<RouterChainResponse | null>(null);
  const [daily, setDaily] = useState<DailyCostResponse | null>(null);
  const [providers, setProviders] = useState<ProviderShareResponse | null>(null);
  const [health, setHealth] = useState<ProviderHealth[]>([]);
  const [fallbacks, setFallbacks] = useState<FallbackResponse | null>(null);
  const [tokens, setTokens] = useState<HourlyTokenResponse | null>(null);
  const [flags, setFlags] = useState<FlagsResponse | null>(null);
  const [providerFilter, setProviderFilter] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, l, c, d, p, h, fb, tk, fl] = await Promise.all([
        dash.statsToday(t),
        dash.limits(t),
        dash.routerChain(t),
        dash.daily(t, 30),
        dash.providersMonth(t),
        dash.health(t),
        dash.fallbacks(t, 20),
        dash.tokens(t, 168),
        dash.flags(t),
      ]);
      setStats(s);
      setLimits(l);
      setChain(c);
      setDaily(d);
      setProviders(p);
      setHealth(h.providers);
      setFallbacks(fb);
      setTokens(tk);
      setFlags(fl);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [t]);

  // Initial load.
  useEffect(() => {
    if (!isSignedIn) return;
    refreshAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSignedIn]);

  // Auto-refresh provider health every 30s (Panel D only).
  useEffect(() => {
    if (!isSignedIn) return;
    const id = setInterval(async () => {
      try {
        const h = await dash.health(t);
        setHealth(h.providers);
      } catch {
        /* ignore — next tick will retry */
      }
    }, 30_000);
    return () => clearInterval(id);
  }, [isSignedIn, t]);

  if (!isSignedIn) return null;

  return (
    <div className="mx-auto max-w-[1160px] space-y-3.5 px-4 py-6 md:px-7">
      <header className="flex items-start justify-between gap-5">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight text-ink">Dashboard</h1>
          <p className="mt-1 max-w-[70ch] text-[13.5px] text-dim">
            Personal observability. Costs are estimated from public list prices —
            free-tier providers don&apos;t bill, so this is the &quot;what would I pay on the paid tier&quot; view.
          </p>
        </div>
        <button
          onClick={refreshAll}
          disabled={loading}
          className="flex shrink-0 items-center gap-2 whitespace-nowrap rounded-lg border border-line-2 bg-panel px-4 py-2 text-[13px] font-medium text-ink transition-colors hover:border-teal hover:text-teal disabled:opacity-50"
        >
          {loading ? "Refreshing…" : "↻ Refresh"}
        </button>
      </header>

      {limits?.soft_warning_active && (
        <div className="rounded-lg border border-amber/20 bg-amber/10 px-4 py-2 font-mono-data text-xs text-amber">
          Soft daily limit exceeded (${limits.today_usd_estimate.toFixed(4)} / ${limits.daily_soft_limit_usd.toFixed(2)}). This is a warning only — requests still go through.
        </div>
      )}
      {limits?.hard_limit_blocked && (
        <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-2 font-mono-data text-xs text-red-300">
          HARD daily limit reached — chat is blocked until tomorrow or until you raise HARD_DAILY_LIMIT_USD.
        </div>
      )}
      {error && (
        <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-2 font-mono-data text-xs text-red-300">
          {error}
        </div>
      )}

      {chain && (
        <div className="flex flex-wrap items-center gap-3.5 rounded-[10px] border border-line bg-panel px-4 py-3 font-mono-data text-xs">
          <span className="text-[10.5px] uppercase tracking-[0.08em] text-faint">Fallback chain</span>
          {chain.chain.map((c, i) => (
            <span key={i} className="flex items-center gap-3.5">
              <span className="flex items-center gap-1.5 rounded-full border border-line-2 bg-bg2 px-3 py-1">
                <ProviderDot provider={c.provider} />
                {c.model}
              </span>
              {i < chain.chain.length - 1 && <span className="text-faint">→</span>}
            </span>
          ))}
          {chain.cost_aware_routing && (
            <span className="ml-auto rounded-full border border-amber/25 bg-amber/10 px-3 py-1 text-[11px] text-amber">
              cost-aware on · &lt;{chain.cost_aware_prompt_threshold} prompt tok
            </span>
          )}
        </div>
      )}

      {/* Panel A — full width */}
      <StatRow stats={stats} limits={limits} />

      {/* Row 2: 60% / 40% */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <DailyCostChart data={daily} providerFilter={providerFilter} />
        </div>
        <div className="lg:col-span-2">
          <ProviderDonut
            data={providers}
            selectedProvider={providerFilter}
            onSelectProvider={setProviderFilter}
          />
        </div>
      </div>

      {/* Row 3: 40% / 60% */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <div className="lg:col-span-2">
          <ProviderStatus providers={health} />
        </div>
        <div className="lg:col-span-3">
          <FallbacksTable data={fallbacks} />
        </div>
      </div>

      {/* Panel F — full width */}
      <TokensChart data={tokens} />

      {/* Panel G — Feature flags (Phase 6) */}
      <FlagsPanel data={flags} />
    </div>
  );
}
