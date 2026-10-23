// 基础展示组件与按钮样式封装；children/props 决定内容和行为，组件本身不发请求或执行领域操作。
// 视觉采用 Apple 风格：磨砂白表面、较大字号层级、胶囊按钮与克制的蓝色强调。
import { clsx } from "clsx";

export function Card({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <section className={clsx("apple-card rounded-2xl p-5 sm:p-6", className)}>
      {children}
    </section>
  );
}

export function PageTitle({ title, description }: { title: string; description: string }) {
  return (
    <div className="mb-7 flex flex-col gap-2.5 border-b border-black/[0.06] pb-6">
      <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-accent">DevFlow AI</div>
      <h1 className="text-3xl font-semibold tracking-[-0.035em] text-ink md:text-4xl">{title}</h1>
      <p className="max-w-3xl text-[15px] leading-7 text-slate-600">{description}</p>
    </div>
  );
}

export function PrimaryButton({ children, className, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={clsx(
        "inline-flex items-center justify-center rounded-full bg-accent px-5 py-2.5 text-sm font-medium text-white shadow-[0_4px_14px_rgba(0,113,227,0.28)] transition-all duration-200 hover:bg-[#0077ed] hover:shadow-[0_6px_20px_rgba(0,113,227,0.36)] active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none",
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}

export function GhostButton({ children, className, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={clsx(
        "w-full rounded-xl border border-black/[0.08] bg-white/70 px-3.5 py-2.5 text-left text-sm text-slate-700 shadow-[0_1px_2px_rgba(0,0,0,0.02)] backdrop-blur transition-all duration-200 hover:border-accent/25 hover:bg-[#f5f9ff] hover:text-[#005bb5]",
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}
