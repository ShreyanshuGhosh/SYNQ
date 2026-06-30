export default function ChatIndex() {
  return (
    <div className="flex flex-1 items-center justify-center bg-[#090d1a]">
      <div className="flex flex-col items-center gap-3 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-white/[0.07] bg-[#0d1526]">
          <svg viewBox="0 4 40 40" className="h-6 w-6" fill="none" aria-hidden="true">
            <path d="M 25.9 12.3 A 14 14 0 1 1 18.8 11.1" stroke="#3b82f6" strokeWidth="6.5" strokeLinecap="butt" />
            <polygon points="23,11 15,15 15,7" fill="#3b82f6" />
          </svg>
        </div>
        <p className="text-sm text-slate-400">Select a conversation or start a new one.</p>
      </div>
    </div>
  );
}
