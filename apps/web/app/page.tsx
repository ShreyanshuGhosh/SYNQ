import Link from "next/link";
import { SignedIn, SignedOut } from "@clerk/nextjs";
import { Layers, Shuffle, DollarSign, Zap, Activity, BarChart2 } from "lucide-react";
import { SynqLogo } from "@/components/synq-logo";

const features = [
  {
    icon: Layers,
    title: "Cross-provider continuity",
    desc: "Keep the same thread alive across Gemini, Mistral, and Groq — no copy-paste, no restart.",
  },
  {
    icon: Shuffle,
    title: "Automatic fallback",
    desc: "If a model is rate-limited or down, SYNQ silently re-routes to the next provider in your chain.",
  },
  {
    icon: DollarSign,
    title: "Cost-aware routing",
    desc: "Short prompts go to the cheapest capable model. You set the rules — SYNQ does the math.",
  },
  {
    icon: Zap,
    title: "Switch mid-conversation",
    desc: "Need bigger context or faster latency? Swap models on the fly without losing a beat.",
  },
  {
    icon: Activity,
    title: "Per-message trace",
    desc: "Every turn shows the provider, model, tokens, and decision behind it.",
  },
  {
    icon: BarChart2,
    title: "Personal observability",
    desc: "A dashboard for spend, fallbacks, and provider health — built for you, not for an org.",
  },
];

const steps = [
  {
    title: "Start chatting on any model",
    desc: "Pick Gemini, Mistral, or Groq — or let SYNQ choose by cost. Just talk.",
  },
  {
    title: "A model runs out — or you switch",
    desc: "Quota hit, latency spike, or you just want a different brain. Either trigger works.",
  },
  {
    title: "SYNQ continues, seamlessly",
    desc: "The next provider picks up with full context. The conversation never resets.",
  },
];

export default function Home() {
  return (
    <div className="min-h-screen bg-[#090d1a] text-white">
      {/* ── Navbar ── */}
      <nav className="fixed inset-x-0 top-0 z-50 border-b border-white/[0.06] bg-[#090d1a]/90 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <SynqLogo size="text-lg" />
          <div className="hidden items-center gap-8 text-sm text-slate-400 md:flex">
            <a href="#features" className="transition-colors hover:text-white">Features</a>
            <a href="#how-it-works" className="transition-colors hover:text-white">How it works</a>
            <Link href="/dashboard" className="transition-colors hover:text-white">Dashboard</Link>
          </div>
          <SignedOut>
            <Link
              href="/sign-in"
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-500"
            >
              Open chat →
            </Link>
          </SignedOut>
          <SignedIn>
            <Link
              href="/chat"
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-500"
            >
              Open chat →
            </Link>
          </SignedIn>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section className="relative flex min-h-screen flex-col items-center justify-center pt-16 text-center">
        {/* Grid overlay */}
        <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(59,130,246,0.05)_1px,transparent_1px),linear-gradient(90deg,rgba(59,130,246,0.05)_1px,transparent_1px)] bg-[size:64px_64px]" />
        {/* Radial glow */}
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_80%_50%_at_50%_-10%,rgba(59,130,246,0.12),transparent)]" />

        <div className="relative z-10 flex flex-col items-center gap-7 px-6">
          {/* Live badge */}
          <div className="flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-4 py-1.5 text-sm text-slate-300">
            <span className="h-1.5 w-1.5 rounded-full bg-green-400" />
            Live across Gemini · Mistral · Groq
          </div>

          {/* Heading */}
          <h1 className="max-w-3xl text-6xl font-bold leading-[1.05] tracking-tight text-white lg:text-7xl">
            Never Start Over.
            <br />
            Stay in{" "}
            <span className="inline-flex items-baseline">
              <span>SYN</span>
              <svg viewBox="0 4 40 40" className="inline-block h-[0.88em] w-auto align-baseline" fill="none" aria-hidden="true">
                <path d="M 25.9 12.3 A 14 14 0 1 1 18.8 11.1" stroke="#3b82f6" strokeWidth="6.5" strokeLinecap="butt" />
                <polygon points="23,11 15,15 15,7" fill="#3b82f6" />
              </svg>
              <span>.</span>
            </span>
          </h1>

          {/* Subtitle */}
          <p className="max-w-xl text-base leading-relaxed text-slate-400">
            Continue any AI conversation across providers. When one model runs out — or you just
            want to switch — SYNQ keeps the thread going on another, with the full context carried
            over.
          </p>

          {/* CTAs */}
          <div className="flex flex-wrap items-center justify-center gap-3">
            <SignedIn>
              <Link
                href="/chat"
                className="flex items-center gap-2 rounded-lg bg-blue-600 px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-blue-500"
              >
                Open chat →
              </Link>
              <Link
                href="/dashboard"
                className="flex items-center gap-2 rounded-lg border border-white/20 px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-white/[0.06]"
              >
                View dashboard
              </Link>
            </SignedIn>
            <SignedOut>
              <Link
                href="/sign-up"
                className="flex items-center gap-2 rounded-lg bg-blue-600 px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-blue-500"
              >
                Open chat →
              </Link>
              <Link
                href="/sign-in"
                className="flex items-center gap-2 rounded-lg border border-white/20 px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-white/[0.06]"
              >
                View dashboard
              </Link>
            </SignedOut>
          </div>
        </div>
      </section>

      {/* ── Provider bar ── */}
      <div className="border-y border-white/[0.06] bg-[#0d1120] py-5">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-center gap-10 px-6 text-sm text-slate-300">
          <span className="text-[11px] uppercase tracking-[0.15em] text-slate-500">Works across</span>
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-blue-400" />
            Gemini
          </div>
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-purple-400" />
            Mistral
          </div>
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-red-400" />
            Groq
          </div>
        </div>
      </div>

      {/* ── Context carries over ── */}
      <section className="px-6 py-24">
        <div className="mx-auto max-w-4xl">
          <p className="mb-4 text-center text-[11px] uppercase tracking-[0.15em] text-blue-500">
            One conversation, many models
          </p>
          <h2 className="mb-14 text-center text-4xl font-bold text-white">
            Context carries over. Automatically.
          </h2>
          <div className="rounded-2xl border border-white/[0.07] bg-[#0d1526] p-10">
            <div className="flex items-center justify-between">
              {/* Gemini */}
              <div className="flex flex-col items-center gap-3">
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-blue-500/20 text-sm font-bold text-blue-400">
                  GE
                </div>
                <p className="font-semibold text-white">Gemini</p>
                <p className="text-xs text-slate-500">Start</p>
              </div>
              <div className="mx-4 flex-1 border-t border-dashed border-white/20" />
              {/* Groq */}
              <div className="flex flex-col items-center gap-3">
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-red-500/20 text-sm font-bold text-red-400">
                  GR
                </div>
                <p className="font-semibold text-white">Groq</p>
                <p className="text-xs text-slate-500">Fallback</p>
              </div>
              <div className="mx-4 flex-1 border-t border-dashed border-white/20" />
              {/* Mistral */}
              <div className="flex flex-col items-center gap-3">
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-purple-500/20 text-sm font-bold text-purple-400">
                  MI
                </div>
                <p className="font-semibold text-white">Mistral</p>
                <p className="text-xs text-slate-500">Continue</p>
              </div>
            </div>
            <p className="mt-8 flex items-center justify-center gap-2 text-xs text-slate-400">
              <svg className="h-4 w-4 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                />
              </svg>
              Full conversation context handed off at each step
            </p>
          </div>
        </div>
      </section>

      {/* ── Features ── */}
      <section id="features" className="px-6 py-24">
        <div className="mx-auto max-w-6xl">
          <p className="mb-3 text-[11px] uppercase tracking-[0.15em] text-blue-500">Features</p>
          <h2 className="mb-3 text-4xl font-bold text-white">
            Built for people who actually live in chat.
          </h2>
          <p className="mb-16 text-slate-400">
            A thin layer over the providers you already use — with the orchestration you wish they
            had.
          </p>
          <div className="overflow-hidden rounded-2xl border border-white/[0.07]">
            <div className="grid grid-cols-1 gap-px bg-white/[0.06] md:grid-cols-3">
              {features.map((f, i) => {
                const Icon = f.icon;
                return (
                  <div key={i} className="bg-[#0d1526] p-8">
                    <div className="mb-5 flex h-10 w-10 items-center justify-center rounded-lg bg-blue-500/10">
                      <Icon className="h-5 w-5 text-blue-500" />
                    </div>
                    <h3 className="mb-2 font-semibold text-white">{f.title}</h3>
                    <p className="text-sm leading-relaxed text-slate-400">{f.desc}</p>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </section>

      {/* ── How it works ── */}
      <section id="how-it-works" className="px-6 py-24">
        <div className="mx-auto max-w-6xl">
          <p className="mb-4 text-center text-[11px] uppercase tracking-[0.15em] text-blue-500">
            How it works
          </p>
          <h2 className="mb-16 text-center text-4xl font-bold text-white">
            Three steps. Zero restarts.
          </h2>
          <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
            {steps.map((s, i) => (
              <div key={i} className="rounded-2xl border border-white/[0.07] bg-[#0d1526] p-8">
                <div className="mb-5 flex h-8 w-8 items-center justify-center rounded-full border border-blue-500/30 text-xs font-bold text-blue-500">
                  {String(i + 1).padStart(2, "0")}
                </div>
                <h3 className="mb-2 font-semibold text-white">{s.title}</h3>
                <p className="text-sm leading-relaxed text-slate-400">{s.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Observability ── */}
      <section className="px-6 py-24">
        <div className="mx-auto grid max-w-6xl grid-cols-1 items-center gap-16 lg:grid-cols-2">
          <div>
            <p className="mb-3 text-[11px] uppercase tracking-[0.15em] text-blue-500">
              Observability
            </p>
            <h2 className="mb-6 text-4xl font-bold leading-tight text-white">
              See every turn, fallback, and cost in one place.
            </h2>
            <p className="mb-8 leading-relaxed text-slate-400">
              A personal dashboard for the way you actually use AI. Track spend by provider, watch
              fallbacks happen live, and keep an eye on what&apos;s working — and what isn&apos;t.
            </p>
            <SignedIn>
              <Link
                href="/dashboard"
                className="inline-flex items-center gap-2 rounded-lg border border-white/20 px-5 py-3 text-sm font-medium text-white transition-colors hover:bg-white/[0.06]"
              >
                View dashboard →
              </Link>
            </SignedIn>
            <SignedOut>
              <Link
                href="/sign-up"
                className="inline-flex items-center gap-2 rounded-lg border border-white/20 px-5 py-3 text-sm font-medium text-white transition-colors hover:bg-white/[0.06]"
              >
                View dashboard →
              </Link>
            </SignedOut>
          </div>

          {/* Mock dashboard preview */}
          <div className="rounded-2xl border border-white/[0.07] bg-[#0d1526] p-6">
            <div className="mb-4 flex items-center justify-between">
              <span className="font-semibold text-white">Today</span>
              <div className="flex items-center gap-1.5 text-xs text-green-400">
                <span className="h-1.5 w-1.5 rounded-full bg-green-400" />
                Live
              </div>
            </div>
            <div className="mb-4 grid grid-cols-3 gap-3">
              <div className="rounded-lg border border-white/[0.07] bg-[#111b30] p-3">
                <p className="text-[10px] uppercase tracking-wide text-slate-500">Est. Cost</p>
                <p className="mt-1 text-xl font-bold text-green-400">$1.24</p>
              </div>
              <div className="rounded-lg border border-white/[0.07] bg-[#111b30] p-3">
                <p className="text-[10px] uppercase tracking-wide text-slate-500">Turns</p>
                <p className="mt-1 text-xl font-bold text-white">147</p>
              </div>
              <div className="rounded-lg border border-white/[0.07] bg-[#111b30] p-3">
                <p className="text-[10px] uppercase tracking-wide text-slate-500">Fallbacks</p>
                <p className="mt-1 text-xl font-bold text-white">3</p>
              </div>
            </div>
            <div className="rounded-lg border border-white/[0.07] bg-[#111b30] p-4">
              <div className="mb-3 flex items-center justify-between text-sm">
                <span className="text-white">Spend by provider</span>
                <span className="text-xs text-slate-500">This month</span>
              </div>
              <div className="flex items-center gap-6">
                {/* Donut chart */}
                <svg className="h-20 w-20 shrink-0" viewBox="0 0 100 100">
                  <circle
                    cx="50" cy="50" r="35"
                    fill="none" stroke="#1e2d45" strokeWidth="20"
                  />
                  <circle
                    cx="50" cy="50" r="35"
                    fill="none" stroke="#3b82f6" strokeWidth="20"
                    strokeDasharray="114 106" strokeDashoffset="0"
                    transform="rotate(-90 50 50)"
                  />
                  <circle
                    cx="50" cy="50" r="35"
                    fill="none" stroke="#8b5cf6" strokeWidth="20"
                    strokeDasharray="68 152" strokeDashoffset="-114"
                    transform="rotate(-90 50 50)"
                  />
                  <circle
                    cx="50" cy="50" r="35"
                    fill="none" stroke="#ef4444" strokeWidth="20"
                    strokeDasharray="38 182" strokeDashoffset="-182"
                    transform="rotate(-90 50 50)"
                  />
                </svg>
                <div className="flex flex-col gap-2 text-xs text-slate-300">
                  <div className="flex items-center gap-2">
                    <span className="h-2 w-2 shrink-0 rounded-full bg-blue-400" />
                    <span>Gemini</span>
                    <span className="ml-3 text-slate-500">52%</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="h-2 w-2 shrink-0 rounded-full bg-purple-400" />
                    <span>Mistral</span>
                    <span className="ml-3 text-slate-500">31%</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="h-2 w-2 shrink-0 rounded-full bg-red-400" />
                    <span>Groq</span>
                    <span className="ml-5 text-slate-500">17%</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="border-t border-white/[0.06] px-6 py-8">
        <div className="mx-auto flex max-w-7xl items-center justify-between text-xs text-slate-500">
          <SynqLogo size="text-sm" />
          <span>Cross-agent AI continuity</span>
        </div>
      </footer>
    </div>
  );
}
