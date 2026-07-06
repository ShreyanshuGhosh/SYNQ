import { AppShell } from "@/components/app-shell";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto bg-bg">{children}</div>
    </AppShell>
  );
}
