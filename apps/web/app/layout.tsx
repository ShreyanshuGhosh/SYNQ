import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { ObservabilityBoot } from "@/components/observability-boot";
import "./globals.css";

export const metadata: Metadata = {
  title: "SYNQ",
  description: "Continue AI conversations across providers",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <html lang="en">
        <body className="bg-white text-gray-900 antialiased">
          <ObservabilityBoot />
          {children}
        </body>
      </html>
    </ClerkProvider>
  );
}
