/**
 * Single source of truth for provider → color, used everywhere a provider
 * is named (sidebar dots, chat gutter labels, dashboard charts, status
 * rows). Keeping this in one place is what makes the identity consistent
 * across the whole app instead of each component picking its own hue.
 */
export type KnownProvider = "gemini" | "mistral" | "groq";

const DOT_CLASS: Record<KnownProvider, string> = {
  gemini: "bg-gemini",
  mistral: "bg-mistral",
  groq: "bg-groq",
};

const TEXT_CLASS: Record<KnownProvider, string> = {
  gemini: "text-gemini",
  mistral: "text-mistral",
  groq: "text-groq",
};

function normalize(provider: string | null | undefined): KnownProvider | null {
  if (!provider) return null;
  const p = provider.toLowerCase();
  if (p.includes("gemini")) return "gemini";
  if (p.includes("mistral")) return "mistral";
  if (p.includes("groq") || p.includes("llama")) return "groq";
  return null;
}

/** Best-effort provider guess from a model id like "gemini-2.5-flash". */
export function providerFromModel(modelId: string | null | undefined): KnownProvider | null {
  return normalize(modelId);
}

export function providerDotClass(provider: string | null | undefined): string {
  const p = normalize(provider);
  return p ? DOT_CLASS[p] : "bg-faint";
}

export function providerTextClass(provider: string | null | undefined): string {
  const p = normalize(provider);
  return p ? TEXT_CLASS[p] : "text-faint";
}
