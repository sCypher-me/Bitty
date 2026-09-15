import type { ButtonHTMLAttributes, InputHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" };

export function Button({ className, variant = "primary", ...props }: ButtonProps) {
  return <button className={cn("inline-flex min-h-11 items-center justify-center rounded-xl px-4 py-2 text-sm font-semibold outline-none transition duration-150 focus-visible:ring-2 focus-visible:ring-violet-400 focus-visible:ring-offset-2 focus-visible:ring-offset-[#080b16] disabled:cursor-not-allowed disabled:opacity-40", variant === "primary" && "bg-gradient-to-r from-violet-500 to-indigo-500 text-white shadow-lg shadow-violet-950/30 hover:-translate-y-0.5 hover:brightness-110", variant === "secondary" && "border border-white/10 bg-white/[.04] text-slate-100 hover:bg-white/[.08]", variant === "danger" && "border border-red-900 bg-red-950 text-red-200 hover:bg-red-900", className)} {...props} />;
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn("min-h-12 w-full rounded-xl border border-white/10 bg-black/20 px-4 text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-violet-400 focus:ring-2 focus:ring-violet-400/15", className)} {...props} />;
}

export function Badge({ children, tone = "green" }: { children: React.ReactNode; tone?: "green" | "amber" | "red" | "neutral" }) {
  return <span className={cn("inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold tracking-wide", tone === "green" && "border-emerald-500/25 bg-emerald-500/10 text-emerald-300", tone === "amber" && "border-amber-500/25 bg-amber-500/10 text-amber-300", tone === "red" && "border-red-500/25 bg-red-500/10 text-red-300", tone === "neutral" && "border-white/10 bg-white/[.04] text-slate-300")}>{children}</span>;
}
