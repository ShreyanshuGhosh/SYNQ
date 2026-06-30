import { cn } from "@/lib/utils";

interface Props {
  className?: string;
  /** Tailwind text-size class to match surrounding text, e.g. "text-lg" */
  size?: string;
}

/**
 * SYNQ brand mark: "SYN" bold text + circular-refresh Q icon in blue.
 * The Q is an arc (≈330°) with an arrowhead, styled like the brand logo.
 */
export function SynqLogo({ className, size = "text-lg" }: Props) {
  return (
    <div className={cn("flex select-none items-center", className)} aria-label="SYNQ">
      <span className={cn("font-extrabold tracking-tight text-white", size)}>SYN</span>
      {/* Q — circular refresh arrow */}
      <svg
        viewBox="0 4 40 40"
        className="h-[1.15em] w-auto"
        fill="none"
        aria-hidden="true"
      >
        {/*
          Circle center (20, 25), r=14, strokeWidth=6.5.
          Arc from 25° to 355° clockwise (≈330° sweep, gap at top).
          25° point  → (20+14·sin25°,  25-14·cos25°)  ≈ (25.9, 12.3)
          355° point → (20+14·sin355°, 25-14·cos355°) ≈ (18.8, 11.1)
        */}
        <path
          d="M 25.9 12.3 A 14 14 0 1 1 18.8 11.1"
          stroke="#3b82f6"
          strokeWidth="6.5"
          strokeLinecap="butt"
        />
        {/*
          Arrowhead at the 355° end (top, just left of 12-o'clock).
          CW tangent at 355° ≈ (1, 0) → pointing right.
          Tip   : (23, 11)
          Left  : (15, 15)
          Right : (15,  7)
        */}
        <polygon points="23,11 15,15 15,7" fill="#3b82f6" />
      </svg>
    </div>
  );
}
