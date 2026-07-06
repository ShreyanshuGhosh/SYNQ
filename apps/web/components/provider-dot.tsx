import { providerDotClass } from "@/lib/provider-identity";
import { cn } from "@/lib/utils";

/** Small identity dot used everywhere a provider is named — sidebar rows,
 * chat gutter labels, dashboard chains/charts. Same color mapping site-wide. */
export function ProviderDot({
  provider,
  className,
}: {
  provider: string | null | undefined;
  className?: string;
}) {
  return (
    <span
      className={cn("inline-block h-1.5 w-1.5 shrink-0 rounded-full", providerDotClass(provider), className)}
      aria-hidden="true"
    />
  );
}
