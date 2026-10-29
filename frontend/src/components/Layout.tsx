import clsx from "clsx";
import { Component, type ErrorInfo, type ReactNode } from "react";
import { BarChart3, FileStack, History, Library, Scale, X } from "lucide-react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";

import { Badge, Button } from "@/components/ui";
import { useHealth } from "@/hooks/api";
import { MAX_PLANS, useSelection } from "@/hooks/selection";

const NAV = [
  { to: "/", label: "My plans", icon: FileStack, end: true },
  { to: "/catalog", label: "Marketplace catalog", icon: Library, end: false },
  { to: "/compare", label: "Compare", icon: Scale, end: false },
  { to: "/comparisons", label: "Saved", icon: History, end: true },
];

function HealthBadge() {
  const { data, isError } = useHealth();
  if (isError) return <Badge tone="red">API offline</Badge>;
  if (!data) return null;
  return data.llm_configured ? (
    <Badge tone="green" title={`LLM mode: ${data.llm_mode}`}>AI explanations on</Badge>
  ) : (
    <Badge tone="amber" title="No OpenRouter key: summaries and explanations use templates">AI off · templates</Badge>
  );
}

function SelectionTray() {
  const { items, remove, clear } = useSelection();
  const nav = useNavigate();
  if (!items.length) return null;
  return (
    <div className="fixed inset-x-0 bottom-0 z-30 border-t border-slate-200 bg-white/95 shadow-[0_-4px_20px_rgba(15,23,42,0.06)] backdrop-blur">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-3 sm:px-6">
        <span className="text-sm font-medium text-slate-700">
          Selected {items.length}/{MAX_PLANS}
        </span>
        <div className="flex flex-1 flex-wrap gap-2">
          {items.map((i) => (
            <span key={i.documentId} className="inline-flex max-w-[16rem] items-center gap-1 rounded-full bg-brand-50 py-1 pl-3 pr-1 text-xs text-brand-700">
              <span className="truncate">{i.label}</span>
              <button aria-label={`Remove ${i.label}`} onClick={() => remove(i.documentId)} className="rounded-full p-0.5 hover:bg-brand-100">
                <X className="h-3.5 w-3.5" />
              </button>
            </span>
          ))}
        </div>
        <Button variant="ghost" size="sm" onClick={clear}>
          Clear
        </Button>
        <Button size="sm" disabled={items.length < 2} onClick={() => nav("/compare")} title={items.length < 2 ? "Select at least 2 plans" : undefined}>
          <BarChart3 className="h-4 w-4" /> Compare {items.length} plans
        </Button>
      </div>
    </div>
  );
}

export function Layout() {
  return (
    <div className="min-h-screen pb-24">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 sm:flex-nowrap sm:px-6">
          <Link to="/" className="flex items-center gap-2 font-semibold text-slate-900">
            <img src="/favicon.svg" alt="" className="h-7 w-7" />
            Plan Compare
          </Link>
          <nav className="order-last flex w-full gap-1 overflow-x-auto sm:order-none sm:w-auto sm:flex-1" aria-label="Main">
            {NAV.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  clsx(
                    "inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium",
                    isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100",
                  )
                }
              >
                <Icon className="h-4 w-4" aria-hidden /> {label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto sm:ml-0"><HealthBadge /></div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
        <ErrorBoundary>
          <Outlet />
        </ErrorBoundary>
      </main>
      <SelectionTray />
    </div>
  );
}

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(error, info);
  }
  render() {
    if (this.state.error)
      return (
        <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-6 text-red-800">
          <p className="font-semibold">This page hit an unexpected error.</p>
          <p className="mt-1 text-sm">{this.state.error.message}</p>
          <Button className="mt-4" variant="secondary" onClick={() => this.setState({ error: null })}>
            Try again
          </Button>
        </div>
      );
    return this.props.children;
  }
}
