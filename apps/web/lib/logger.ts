/**
 * Frontend structured logger — pino with the same field discipline as the
 * backend's structlog: ``request_id`` and ``conversation_id`` always
 * present (when in scope), message content is NEVER logged.
 *
 * Browser bundles run pino's "browser" mode automatically (no extra
 * config needed). We expose a thin wrapper so the rest of the app
 * imports a stable API regardless of dev / prod or which side of the
 * SSR boundary we're on.
 */

import pino from "pino";

const isDev = process.env.NODE_ENV !== "production";

// pino-pretty is dev-only — listed in devDependencies so prod bundles
// don't pull it in. Browser pino has its own dev pretty mode.
const baseLogger = pino({
  level: process.env.NEXT_PUBLIC_LOG_LEVEL ?? (isDev ? "debug" : "info"),
  // Drop sensitive keys with `redact` so a misuse can't leak a JWT.
  redact: {
    paths: [
      "api_key",
      "authorization",
      "x_api_key",
      "message_content",
      "file_bytes",
      "embedding_vector",
      "token",
      "*.api_key",
      "*.authorization",
    ],
    censor: "<redacted>",
  },
  browser: {
    asObject: true,
  },
});

export type LogContext = {
  request_id?: string;
  conversation_id?: string;
  [key: string]: unknown;
};

export function getLogger(ctx?: LogContext) {
  if (!ctx || Object.keys(ctx).length === 0) return baseLogger;
  return baseLogger.child(ctx);
}

export const log = baseLogger;
