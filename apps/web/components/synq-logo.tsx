import { cn } from "@/lib/utils";

interface Props {
  className?: string;
  /** Tailwind text-size class to match surrounding text, e.g. "text-lg" */
  size?: string;
  /** "app" = dark app shell (white text, app teal). "landing" = light marketing page (ink text, landing teal). */
  variant?: "app" | "landing";
}

/**
 * SYNQ brand mark: wave-path logo + wordmark. One continuous stroke
 * echoes the "one conversation, many models" thread motif used across
 * the landing page's hero SVG.
 */
export function SynqLogo({ className, size = "text-lg", variant = "app" }: Props) {
  const stroke = variant === "app" ? "#2fbfae" : "#0e7c74";
  const textClass = variant === "app" ? "text-ink" : "text-text-ink";
  return (
    <div
      className={cn("flex select-none items-center gap-2", className)}
      aria-label="SYNQ"
    >
      <svg
        width="20"
        height="20"
        viewBox="0 0 22 22"
        fill="none"
        aria-hidden="true"
        className="shrink-0"
      >
        <path
          d="M2 11 C6 4, 9 18, 13 11 S 18 5, 20 11"
          stroke={stroke}
          strokeWidth="2.6"
          strokeLinecap="round"
        />
      </svg>
      <span
        className={cn(
          "font-mono-data font-semibold tracking-wide",
          textClass,
          size,
        )}
      >
        synq
      </span>
    </div>
  );
}
