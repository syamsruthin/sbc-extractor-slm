import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { ComparisonResult } from "@/api/client";
import { PLAN_COLORS } from "@/lib/colors";
import { money, range } from "@/lib/format";


/** Annual total per plan per scenario. A range is drawn as a solid bar to the low end plus a lighter
 * segment up to the high end. */
export function CostChart({ result }: { result: ComparisonResult }) {
  const names = Object.fromEntries(result.plans.map((p) => [p.plan_key, `${p.plan_key} · ${p.plan_name ?? `Plan ${p.plan_key}`}`]));
  const data = result.scenarios.map((s) => {
    const row: Record<string, number | string> = { scenario: s.scenario.label };
    for (const [k, r] of Object.entries(s.per_plan)) {
      row[`${k}_low`] = r.total.low;
      row[`${k}_range`] = Math.max(0, r.total.high - r.total.low);
    }
    return row;
  });
  const keys = result.plans.map((p) => p.plan_key);
  return (
    <div className="h-80 w-full" aria-label="Estimated yearly total by scenario" role="img">
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
          <XAxis dataKey="scenario" tick={{ fontSize: 12 }} />
          <YAxis tickFormatter={(v) => money(v)} tick={{ fontSize: 12 }} width={70} />
          <Tooltip
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              const s = result.scenarios.find((x) => x.scenario.label === label);
              return (
                <div className="rounded-lg border border-slate-200 bg-white p-3 text-xs shadow-md">
                  <p className="mb-1 font-medium">{label}</p>
                  {s &&
                    keys.map((k, i) => (
                      <p key={k} className="flex items-center gap-2">
                        <span className="inline-block h-2 w-2 rounded-full" style={{ background: PLAN_COLORS[i] }} />
                        {names[k]}: <span className="tabular font-medium">{range(s.per_plan[k].total)}</span>
                      </p>
                    ))}
                </div>
              );
            }}
          />
          <Legend formatter={(v: string) => names[v.split("_")[0]] ?? v} payload={keys.map((k, i) => ({ value: `${k}_low`, type: "square", color: PLAN_COLORS[i] }))} />
          {keys.map((k, i) => [
            <Bar key={`${k}_low`} dataKey={`${k}_low`} stackId={k} fill={PLAN_COLORS[i]} isAnimationActive={false} />,
            <Bar key={`${k}_range`} dataKey={`${k}_range`} stackId={k} fill={PLAN_COLORS[i]} fillOpacity={0.3} radius={[4, 4, 0, 0]} isAnimationActive={false} />,
          ])}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
