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
        <p className="text-xs text-gray-500">
          Change by editing <code>.env</code> and restarting the API.
        </p>
      </CardHeader>
      <CardContent>
        {(!data || data.flags.length === 0) && (
          <p className="text-sm text-gray-500">No flags registered.</p>
        )}
        {data && data.flags.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-left text-xs uppercase text-gray-500 dark:border-gray-800">
                <th className="py-2 pr-4 font-medium">Flag</th>
                <th className="py-2 pr-4 font-medium">State</th>
                <th className="py-2 font-medium">Description</th>
              </tr>
            </thead>
            <tbody>
              {data.flags.map((f) => (
                <tr
                  key={f.name}
                  className="border-b border-gray-100 align-top last:border-b-0 dark:border-gray-900"
                >
                  <td className="py-2 pr-4 font-mono text-xs">{f.name}</td>
                  <td className="py-2 pr-4">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${
                        f.value
                          ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
                          : "bg-gray-100 text-gray-600 dark:bg-gray-900 dark:text-gray-400"
                      }`}
                    >
                      {f.value ? "ON" : "OFF"}
                    </span>
                  </td>
                  <td className="py-2 text-xs text-gray-600 dark:text-gray-300">
                    {f.description}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}
