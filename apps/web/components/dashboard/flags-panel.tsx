"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { FlagsResponse } from "@/lib/api";

interface Props {
  data: FlagsResponse | null;
}

export function FlagsPanel({ data }: Props) {
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="block">Feature flags</CardTitle>
        <p className="font-mono-data text-[11px] text-faint">
          Change by editing <code className="text-dim">.env</code> and restarting the API.
        </p>
      </CardHeader>
      <CardContent>
        {(!data || data.flags.length === 0) && (
          <p className="font-mono-data text-xs text-faint">No flags registered.</p>
        )}
        {data && data.flags.length > 0 && (
          <div>
            {data.flags.map((f, i) => (
              <div
                key={f.name}
                className={`flex items-start gap-4 py-2.5 text-sm ${i < data.flags.length - 1 ? "border-b border-line" : ""}`}
              >
                <span className="w-40 shrink-0 font-mono-data text-xs text-dim">{f.name}</span>
                <span
                  className={`shrink-0 rounded-full px-2 py-0.5 font-mono-data text-[10px] font-medium uppercase tracking-wide ${
                    f.value ? "bg-brand-green/10 text-brand-green" : "bg-panel-2 text-faint"
                  }`}
                >
                  {f.value ? "ON" : "OFF"}
                </span>
                <span className="text-xs text-dim">{f.description}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
