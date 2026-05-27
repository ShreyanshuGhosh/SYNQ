"use client";

import { useEffect } from "react";

/**
 * Mounted once at the root of the app — kicks off the OTel web tracer
 * so subsequent fetch() calls carry traceparent headers. Best-effort:
 * failures are logged but never surface to the user.
 */
export function ObservabilityBoot() {
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mod = await import("@/lib/tracing");
        if (!cancelled) {
          await mod.configureTracing();
        }
      } catch {
        /* tracing is optional — never block the app on it */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);
  return null;
}
