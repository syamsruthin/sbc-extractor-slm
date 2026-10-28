import type { CostShare, Money } from "@/api/client";

const usd0 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const usd2 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });

export function money(v: number | null | undefined, fallback = "—"): string {
  if (v === null || v === undefined || Number.isNaN(v)) return fallback;
  return Number.isInteger(v) ? usd0.format(v) : usd2.format(v);
}

export function signedMoney(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (v === 0) return "$0";
  return (v > 0 ? "+" : "−") + money(Math.abs(v));
}

export function range(m: Money | null | undefined): string {
  if (!m) return "—";
  return m.low === m.high ? money(m.low) : `${money(m.low)} – ${money(m.high)}`;
}

export function signedRange(m: Money | null | undefined): string {
  if (!m) return "—";
  return m.low === m.high ? signedMoney(m.low) : `${signedMoney(m.low)} to ${signedMoney(m.high)}`;
}

export function describeCost(c: CostShare | null | undefined): string {
  if (!c) return "Not listed";
  if (!c.covered) return "Not covered";
  const parts: string[] = [];
  if (c.copay === 0 && c.coinsurance_pct === 0) parts.push("No charge");
  else {
    if (c.copay !== null && c.copay !== undefined) parts.push(`${money(c.copay)} copay`);
    if (c.coinsurance_pct !== null && c.coinsurance_pct !== undefined) parts.push(`${c.coinsurance_pct}% coinsurance`);
  }
  return parts.length ? parts.join(" then ") : "Covered (price not stated)";
}

export function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

export function relTime(iso: string): string {
  const d = new Date(iso);
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return d.toLocaleDateString();
}
