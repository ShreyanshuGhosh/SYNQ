import Link from "next/link";
import { SignedIn, SignedOut } from "@clerk/nextjs";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-24">
      <h1 className="text-5xl font-bold tracking-tight">SYNQ</h1>
      <p className="max-w-md text-center text-lg text-gray-500">
        Continue AI conversations across providers — when Claude runs out, keep
        going on Gemini.
      </p>
      <SignedOut>
        <div className="flex gap-3">
          <Link
            href="/sign-in"
            className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700"
          >
            Sign in
          </Link>
          <Link
            href="/sign-up"
            className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium hover:bg-gray-50"
          >
            Sign up
          </Link>
        </div>
      </SignedOut>
      <SignedIn>
        <Link
          href="/chat"
          className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700"
        >
          Open chat
        </Link>
      </SignedIn>
    </main>
  );
}
