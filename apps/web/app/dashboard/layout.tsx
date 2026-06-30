import { UserButton } from "@clerk/nextjs";
import { ConversationSidebar } from "@/components/conversation-sidebar";
import Link from "next/link";
import { SynqLogo } from "@/components/synq-logo";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#090d1a]">
      <aside className="flex w-72 shrink-0 flex-col border-r border-white/[0.07] bg-[#0a0e1c]">
        <div className="flex items-center justify-between border-b border-white/[0.07] px-4 py-4">
          <Link href="/">
            <SynqLogo size="text-base" />
          </Link>
          <UserButton afterSignOutUrl="/" />
        </div>
        <ConversationSidebar />
      </aside>
      <main className="flex-1 overflow-y-auto bg-[#090d1a]">{children}</main>
    </div>
  );
}
