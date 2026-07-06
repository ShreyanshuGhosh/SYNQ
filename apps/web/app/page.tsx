import Link from "next/link";
import { SignedIn, SignedOut } from "@clerk/nextjs";
import { SynqLogo } from "@/components/synq-logo";

export default function Home() {
  return (
    <div className="bg-paper font-landing-body text-text-ink">
      {/* ── Nav ── */}
      <nav className="sticky top-0 z-50 border-b border-paper-line bg-paper/90 backdrop-blur-md">
        <div className="mx-auto flex h-[62px] max-w-[1060px] items-center justify-between px-6">
          <Link href="/" className="flex items-center gap-2">
            <SynqLogo variant="landing" size="text-lg" />
          </Link>
          <div className="flex items-center gap-6 text-sm">
            <a href="#demo" className="hidden font-medium text-ink-dim transition-colors hover:text-text-ink md:inline">
              Live demo
            </a>
            <a href="#why" className="hidden font-medium text-ink-dim transition-colors hover:text-text-ink md:inline">
              Why SYNQ
            </a>
            <a href="#traces" className="hidden font-medium text-ink-dim transition-colors hover:text-text-ink md:inline">
              Traces
            </a>
            <SignedOut>
              <Link
                href="/sign-in"
                className="rounded-full border-[1.5px] border-text-ink px-5 py-2 text-sm font-semibold text-text-ink transition-colors hover:bg-text-ink hover:text-paper"
              >
                Sign in
              </Link>
              <Link
                href="/sign-up"
                className="rounded-full bg-teal-landing px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-teal-landing-dark"
              >
                Start free
              </Link>
            </SignedOut>
            <SignedIn>
              <Link
                href="/chat"
                className="rounded-full bg-teal-landing px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-teal-landing-dark"
              >
                Open chat →
              </Link>
            </SignedIn>
          </div>
        </div>
      </nav>

      {/* ── Hero ── */}
      <header className="px-6 pb-10 pt-24 text-center">
        <h1 className="mx-auto max-w-[16ch] font-landing-display text-[clamp(38px,6vw,66px)] font-bold leading-[1.05] tracking-[-0.025em]">
          <span className="relative whitespace-nowrap text-ink-dim">
            Start a new chat.
            <span
              aria-hidden="true"
              className="absolute inset-x-[-2%] top-1/2 h-[3px] -rotate-[1.5deg] rounded bg-coral"
            />
          </span>
          <br />
          Keep the thread.
        </h1>
        <p className="mx-auto mt-6 max-w-[50ch] text-lg text-ink-dim">
          SYNQ is one continuous conversation that flows across Gemini, Mistral, and Groq —
          models change underneath, your context never does.
        </p>
        <div className="mt-8 flex justify-center gap-3">
          <SignedIn>
            <Link
              href="/chat"
              className="rounded-full bg-teal-landing px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-teal-landing-dark"
            >
              Open chat →
            </Link>
          </SignedIn>
          <SignedOut>
            <Link
              href="/sign-up"
              className="rounded-full bg-teal-landing px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-teal-landing-dark"
            >
              Start free
            </Link>
          </SignedOut>
          <a
            href="#demo"
            className="rounded-full border-[1.5px] border-text-ink px-6 py-3 text-sm font-semibold text-text-ink transition-colors hover:bg-text-ink hover:text-paper"
          >
            See how
          </a>
        </div>

        {/* Signature thread SVG — one conversation flowing through three providers */}
        <div className="mx-auto mt-[72px] max-w-[920px] px-3" aria-label="One conversation flowing through three providers">
          <svg viewBox="0 0 920 190" className="block h-auto w-full">
            <path
              d="M20 100 C 120 100, 150 60, 230 60 H 330 C 400 60, 420 130, 500 130 H 610 C 680 130, 700 85, 780 85 H 900"
              stroke="#0e7c74"
              strokeWidth="3"
              fill="none"
              strokeLinecap="round"
            />
            <path
              className="animate-thread-flow"
              d="M20 100 C 120 100, 150 60, 230 60 H 330 C 400 60, 420 130, 500 130 H 610 C 680 130, 700 85, 780 85 H 900"
              stroke="#0e7c74"
              strokeWidth="3"
              fill="none"
              strokeLinecap="round"
              strokeDasharray="10 14"
              opacity="0.5"
            />
            <rect x="200" y="38" width="140" height="44" rx="10" fill="#ffffff" stroke="#dfe3e0" strokeWidth="1.5" />
            <text x="270" y="57" textAnchor="middle" className="font-landing-mono text-[12px] font-medium" fill="#151a1e">gemini-2.0</text>
            <text x="270" y="72" textAnchor="middle" className="font-landing-mono text-[9.5px]" fill="#6a7480">turns 1–41</text>

            <rect x="470" y="108" width="150" height="44" rx="10" fill="#ffffff" stroke="#dfe3e0" strokeWidth="1.5" />
            <text x="545" y="127" textAnchor="middle" className="font-landing-mono text-[12px] font-medium" fill="#151a1e">mistral-large</text>
            <text x="545" y="142" textAnchor="middle" className="font-landing-mono text-[9.5px]" fill="#6a7480">turns 42–58</text>

            <rect x="750" y="63" width="140" height="44" rx="10" fill="#ffffff" stroke="#dfe3e0" strokeWidth="1.5" />
            <text x="820" y="82" textAnchor="middle" className="font-landing-mono text-[12px] font-medium" fill="#151a1e">groq-llama3</text>
            <text x="820" y="97" textAnchor="middle" className="font-landing-mono text-[9.5px]" fill="#6a7480">turn 59 →</text>

            <text x="400" y="100" className="font-landing-mono text-[10px] font-medium" fill="#e0543a">→ rate limit · auto handoff</text>
            <text x="655" y="112" className="font-landing-mono text-[10px] font-medium" fill="#e0543a">→ cheap task · routed</text>
          </svg>
          <p className="mt-4 text-center font-landing-mono text-[12.5px] text-ink-dim">
            one thread · three providers · <b className="font-medium text-teal-landing">context intact end-to-end</b>
          </p>
        </div>
      </header>

      {/* ── Terminal (dark card on light page) ── */}
      <section className="px-6 py-24" id="demo">
        <div className="mx-auto max-w-[1060px]">
          <div className="mx-auto mb-12 max-w-[56ch] text-center">
            <span className="mb-3 block font-landing-mono text-xs uppercase tracking-[0.14em] text-teal-landing">
              Live handoff
            </span>
            <h2 className="font-landing-display text-[clamp(26px,3.6vw,34px)] font-bold leading-[1.15] tracking-[-0.02em]">
              Watch a rate limit become a non-event.
            </h2>
            <p className="mt-3.5 text-base text-ink-dim">
              This is a real session. Gemini hits a 429 mid-answer — SYNQ hands the full thread
              to Mistral before the next keystroke.
            </p>
          </div>

          <div className="mx-auto max-w-[860px] overflow-hidden rounded-[14px] border border-[#232b3a] bg-[#151b26] shadow-[0_32px_80px_-32px_rgba(21,26,30,0.35)]">
            <div className="flex items-center gap-2 border-b border-[#232b3a] bg-[#0d1117] px-4 py-3">
              <span className="h-[11px] w-[11px] rounded-full bg-[#2a3345]" />
              <span className="h-[11px] w-[11px] rounded-full bg-[#2a3345]" />
              <span className="h-[11px] w-[11px] rounded-full bg-[#2a3345]" />
              <span className="ml-2 font-landing-mono text-[11.5px] text-[#8b95a7]">synq · session_8f2c</span>
            </div>
            <div className="space-y-3.5 px-6 py-5 font-landing-mono text-[13px] leading-relaxed text-[#e6e9ef]">
              <p><span className="text-[#8b95a7]">you    ▸ </span>walk me through sharding this postgres table</p>
              <p><span className="text-gemini">gemini ▸ </span>Sharding by tenant_id makes sense here. Start with a hash…</p>
              <p className="rounded-r-md border-l-2 border-amber bg-amber/10 px-3 py-1.5 text-xs leading-relaxed text-amber">
                ⚡ gemini-2.0 rate limited → handing off to mistral-large · context: 41 turns, 18.2k tokens · 240ms
              </p>
              <p><span className="text-mistral">mistral▸ </span>Continuing from the hash strategy above — for rebalancing you&apos;ll want…</p>
              <p><span className="text-[#8b95a7]">you    ▸ </span>quick one: cron syntax for every 15 min</p>
              <p className="text-[#8b95a7]">   ⏳ routed to groq-llama3 · trivial task · est. $0.0001</p>
              <p><span className="text-groq">groq   ▸ </span>*/15 * * * *</p>
              <p>
                <span className="text-[#8b95a7]">you    ▸ </span>
                <span className="animate-cursor-blink inline-block h-[15px] w-2 translate-y-0.5 bg-amber align-text-bottom" />
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── Claims ── */}
      <section className="px-6 pb-24" id="why">
        <div className="mx-auto grid max-w-[1060px] grid-cols-1 gap-5 md:grid-cols-[1.2fr_1fr_1fr]">
          <div className="rounded-2xl border border-teal-landing bg-teal-landing p-8 text-white">
            <span className="mb-4 block font-landing-mono text-xs tracking-[0.1em] text-white/85">CONTINUITY</span>
            <h3 className="mb-2.5 font-landing-display text-[21px] font-semibold tracking-[-0.01em]">
              The model changes. The conversation doesn&apos;t.
            </h3>
            <p className="text-[14.5px] text-white/85">
              Every handoff carries your full history forward — the next model reads the entire
              thread, not a lossy summary. No re-explaining, no copy-paste.
            </p>
          </div>
          <div className="rounded-2xl border border-paper-line bg-card p-8">
            <span className="mb-4 block font-landing-display text-[44px] font-bold tracking-[-0.02em]">&lt;300ms</span>
            <h3 className="mb-2.5 font-landing-display text-[21px] font-semibold tracking-[-0.01em]">Invisible fallback</h3>
            <p className="text-[14.5px] text-ink-dim">
              Rate limits and outages reroute mid-sentence. Most people never notice a provider
              went down.
            </p>
          </div>
          <div className="rounded-2xl border border-paper-line bg-card p-8">
            <span className="mb-4 block font-landing-display text-[44px] font-bold tracking-[-0.02em]">–38%</span>
            <h3 className="mb-2.5 font-landing-display text-[21px] font-semibold tracking-[-0.01em]">Routing that pays for itself</h3>
            <p className="text-[14.5px] text-ink-dim">
              Trivial prompts go to fast, cheap models automatically. Frontier models only when
              the task earns it.
            </p>
          </div>
        </div>
      </section>

      {/* ── Receipt ── */}
      <section className="border-y border-paper-line bg-card py-[88px]" id="traces">
        <div className="mx-auto grid max-w-[1060px] grid-cols-1 items-center gap-16 px-6 md:grid-cols-[1fr_400px]">
          <div>
            <h2 className="font-landing-display text-[clamp(26px,3.6vw,34px)] font-bold leading-[1.15] tracking-[-0.02em]">
              Every message comes with a receipt.
            </h2>
            <p className="mt-4 max-w-[44ch] text-base text-ink-dim">
              Provider, model, token count, and the reason behind every routing decision —
              attached to each message and rolled up in your dashboard. If SYNQ made a choice,
              you can see why.
            </p>
            <div className="mt-7">
              <SignedIn>
                <Link href="/dashboard" className="inline-block rounded-full bg-teal-landing px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-teal-landing-dark">
                  Open the dashboard
                </Link>
              </SignedIn>
              <SignedOut>
                <Link href="/sign-up" className="inline-block rounded-full bg-teal-landing px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-teal-landing-dark">
                  Open the dashboard
                </Link>
              </SignedOut>
            </div>
          </div>
          <div className="rounded-xl border border-paper-line bg-paper p-6 font-landing-mono text-[12.5px]">
            <div className="mb-3 flex justify-between border-b border-dashed border-paper-line pb-3 font-semibold">
              <span>TRACE · msg_2941</span><span>14:32:07</span>
            </div>
            <div className="flex justify-between py-1 text-ink-dim"><span>provider</span><b className="font-medium text-text-ink">mistral-large</b></div>
            <div className="flex justify-between py-1 text-ink-dim"><span>reason</span><b className="font-medium text-text-ink">fallback (gemini 429)</b></div>
            <div className="flex justify-between py-1 text-coral"><span>context handoff</span><span>18.2k tok · 240ms</span></div>
            <div className="flex justify-between py-1 text-ink-dim"><span>tokens in / out</span><b className="font-medium text-text-ink">1,204 / 358</b></div>
            <div className="flex justify-between py-1 text-ink-dim"><span>latency</span><b className="font-medium text-text-ink">1.9s</b></div>
            <div className="mt-3 flex justify-between border-t border-dashed border-paper-line pt-3 font-semibold">
              <span>message cost</span><span className="text-teal-landing">$0.0031</span>
            </div>
          </div>
        </div>
      </section>

      {/* ── CTA ── */}
      <div className="px-6 py-[100px] text-center">
        <h2 className="mx-auto mb-3.5 max-w-[18ch] font-landing-display text-[clamp(26px,3.6vw,34px)] font-bold leading-[1.15] tracking-[-0.02em]">
          Pick up where you left off. Always.
        </h2>
        <p className="mb-8 text-ink-dim">Connect your keys in two minutes. Free while in beta.</p>
        <SignedIn>
          <Link href="/chat" className="inline-block rounded-full bg-teal-landing px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-teal-landing-dark">
            Open your workspace
          </Link>
        </SignedIn>
        <SignedOut>
          <Link href="/sign-up" className="inline-block rounded-full bg-teal-landing px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-teal-landing-dark">
            Create your workspace
          </Link>
        </SignedOut>
      </div>

      {/* ── Footer ── */}
      <footer className="border-t border-paper-line px-6 py-7 text-sm text-ink-dim">
        <div className="mx-auto flex max-w-[1060px] flex-wrap items-center justify-between gap-2.5">
          <span>© 2026 SYNQ</span>
          <span className="flex gap-4">
            <a href="#" className="hover:text-text-ink">Docs</a>
            <a href="#" className="hover:text-text-ink">GitHub</a>
            <a href="#" className="hover:text-text-ink">Status</a>
          </span>
        </div>
      </footer>
    </div>
  );
}
