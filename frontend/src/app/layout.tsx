import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";

export const metadata: Metadata = {
  title: "AI Research Agent",
  description:
    "Autonomous agent that plans, searches, analyses and reports on any topic with verified citations.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <header className="sticky top-0 z-20 border-b border-[#1e2a42] bg-[#070b14]/85 backdrop-blur">
          <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-5 py-3.5">
            <Link href="/" className="flex items-center gap-2.5">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#4f8cff] font-bold text-[#05070f]">
                R
              </span>
              <span className="text-sm font-semibold tracking-tight text-[#e6edf7]">
                Research Agent
              </span>
            </Link>
            <nav className="flex items-center gap-4 font-mono text-xs text-[#8b9bb4]">
              <Link href="/" className="transition hover:text-[#e6edf7]">
                New research
              </Link>
              <a
                href="http://127.0.0.1:8000/docs"
                target="_blank"
                rel="noreferrer noopener"
                className="transition hover:text-[#e6edf7]"
              >
                API docs
              </a>
            </nav>
          </div>
        </header>
        {children}
        <footer className="border-t border-[#1e2a42] px-5 py-5">
          <p className="mx-auto max-w-6xl font-mono text-[11px] text-[#667891]">
            Planner &rarr; Web search &rarr; Analyser &rarr; Report writer &middot; citations are
            validated against retrieved sources
          </p>
        </footer>
      </body>
    </html>
  );
}
