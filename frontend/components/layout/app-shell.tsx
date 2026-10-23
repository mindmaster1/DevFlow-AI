// 应用导航外壳：只负责全局入口和页面容器，不持有某个仓库的业务状态，避免路由间隐式共享数据。
// 视觉采用 Apple 风格：固定在顶部的磨砂玻璃导航、胶囊式选中态、克制的环境光背景。
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Sparkles } from "lucide-react";
import { clsx } from "clsx";

const navItems = [
  { href: "/", label: "Dashboard" },
  { href: "/knowledge", label: "项目知识" },
  { href: "/rag", label: "RAG 工作室" },
  { href: "/repos", label: "Repos" },
  { href: "/action-drafts", label: "Drafts" },
  { href: "/workflow-runs", label: "Runs" },
  { href: "/workspaces", label: "团队工作区" },
  { href: "/reports", label: "研发周报" },
  { href: "/code-graph", label: "Code Graph" },
  { href: "/evals", label: "Evals" }
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isDashboard = pathname === "/";

  return (
    <main className="min-h-screen">
      <header className="sticky top-0 z-50 border-b border-black/[0.06] bg-white/70 backdrop-blur-2xl backdrop-saturate-150">
        <div className="mx-auto flex h-14 w-full max-w-[1600px] items-center gap-3 px-4 sm:gap-4 sm:px-6 lg:px-8">
          <Link href="/" className="group flex shrink-0 items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-[10px] bg-gradient-to-br from-[#2997ff] via-[#0071e3] to-[#0055a4] text-white shadow-[0_4px_14px_rgba(0,113,227,0.35)] transition-transform duration-300 group-hover:scale-105">
              <Sparkles className="h-4 w-4" />
            </span>
            <span className="text-[15px] font-semibold tracking-[-0.02em] text-ink">DevFlow AI</span>
          </Link>

          <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {navItems.map((item) => {
              const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={clsx(
                    "whitespace-nowrap rounded-full px-3 py-1.5 text-[13px] font-medium transition-all duration-200",
                    active
                      ? "bg-accent text-white shadow-sm shadow-blue-500/20"
                      : "text-slate-600 hover:bg-black/[0.045] hover:text-ink"
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="hidden shrink-0 items-center gap-2 rounded-full border border-black/[0.06] bg-white/60 px-3 py-1 text-[11px] font-medium text-slate-500 sm:flex">
            <span className="h-1.5 w-1.5 rounded-full bg-[#34c759] shadow-[0_0_0_3px_rgba(52,199,89,0.12)]" />
            Local
          </div>
        </div>
      </header>

      <div
        className={clsx(
          isDashboard
            ? "w-full p-2 sm:p-3"
            : "mx-auto w-full max-w-[1600px] px-4 py-6 sm:px-6 lg:px-8"
        )}
      >
        {children}
      </div>
    </main>
  );
}
