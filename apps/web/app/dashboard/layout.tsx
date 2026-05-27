import { UserButton } from "@clerk/nextjs";
import { ConversationSidebar } from "@/components/conversation-sidebar";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <aside className="flex w-72 shrink-0 flex-col border-r border-gray-200 bg-gray-50">
        <div className="flex items-center justify-between border-b border-gray-200 p-4">
          <span className="font-semibold tracking-tight">SYNQ</span>
          <UserButton afterSignOutUrl="/" />
        </div>
        <ConversationSidebar />
      </aside>
      <main className="flex-1 overflow-y-auto bg-gray-50/30 dark:bg-gray-950">{children}</main>
    </div>
  );
}
