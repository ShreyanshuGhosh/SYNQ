import { SignUp } from "@clerk/nextjs";
import Link from "next/link";
import { SynqLogo } from "@/components/synq-logo";

export default function SignUpPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-8 bg-bg p-6">
      <Link href="/">
        <SynqLogo size="text-xl" />
      </Link>
      <SignUp
        appearance={{
          variables: {
            colorPrimary: "#2fbfae",
            colorBackground: "#151b26",
            colorText: "#e7eaf0",
            colorTextSecondary: "#8b95a7",
            colorInputBackground: "#0d1117",
            colorInputText: "#e7eaf0",
            borderRadius: "10px",
          },
          elements: {
            card: "border border-line shadow-none",
          },
        }}
      />
    </main>
  );
}
