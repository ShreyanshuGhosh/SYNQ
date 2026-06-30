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
        <CardTitle>Feature flags</CardTitle>
        <p className="text-xs text-slate-500">
          Change by editing <code className="text-slate-400">.env</code> and restarting the API.
        </p>
      </CardHeader>
      <CardContent>
        {(!data || data.flags.length === 0) && (
          <p className="text-sm text-slate-500">No flags registered.</p>
        )}
        {data && data.flags.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/[0.07] text-left text-xs uppercase text-slate-500">
                <th className="py-2 pr-4 font-medium">Flag</th>
                <th className="py-2 pr-4 font-medium">State</th>
                <th className="py-2 font-medium">Description</th>
              </tr>
            </thead>
            <tbody>
              {data.flags.map((f) => (
                <tr
                  key={f.name}
                  className="border-b border-white/[0.04] align-top last:border-b-0"
                >
                  <td className="py-2 pr-4 font-mono text-xs text-slate-300">{f.name}</td>
                  <td className="py-2 pr-4">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${
                        f.value
                          ? "bg-emerald-500/10 text-emerald-400"
                          : "bg-white/[0.06] text-slate-400"
                      }`}
                    >
                      {f.value ? "ON" : "OFF"}
                    </span>
                  </td>
                  <td className="py-2 text-xs text-slate-400">{f.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}
