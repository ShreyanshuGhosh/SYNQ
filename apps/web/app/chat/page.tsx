export default function ChatIndex() {
  return (
    <div className="flex flex-1 items-center justify-center bg-bg">
      <div className="flex flex-col items-center gap-3 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-line bg-panel">
          <svg width="20" height="20" viewBox="0 0 22 22" fill="none" aria-hidden="true">
            <path
              d="M2 11 C6 4, 9 18, 13 11 S 18 5, 20 11"
              stroke="#2fbfae"
              strokeWidth="2.6"
              strokeLinecap="round"
            />
          </svg>
        </div>
        <p className="font-mono-data text-sm text-faint">Select a conversation or start a new one.</p>
      </div>
    </div>
  );
}
