import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import type { FieldErrors, UseFormRegister, UseFormSetValue } from "react-hook-form";

import { Button, Card, inputClass } from "@/components/ui";
import { useReferencePrices } from "@/hooks/api";
import type { FormInput, FormValues } from "@/lib/compareForm";
import { money } from "@/lib/format";

/** Reference prices the estimates use; any of them can be replaced for this comparison. */
export function PricesPanel({
  register,
  setValue,
  overrides,
  errors,
}: {
  register: UseFormRegister<FormInput>;
  setValue: UseFormSetValue<FormInput>;
  overrides: Record<string, string>;
  errors: FieldErrors<FormValues>["overrides"];
}) {
  const prices = useReferencePrices();
  const changed = Object.values(overrides).filter((v) => v !== "").length;
  const [open, setOpen] = useState(changed > 0);
  if (!prices.data) return null;
  const { prices: values, labels, source, version } = prices.data;
  return (
    <Card className="p-5">
      <button type="button" className="flex w-full items-center gap-2 text-left font-semibold" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        Prices used for estimates
        {changed > 0 && <span className="text-sm font-normal text-slate-500">({changed} changed)</span>}
      </button>
      {open && (
        <div className="mt-3">
          <p className="mb-4 text-sm text-slate-500">
            What one use of each service costs before insurance ({source}, version {version}). Change any price to match what you'd really pay; blank fields use the default.
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(values).map(([key, v]) => (
              <label key={key} className="block text-sm">
                <span className="text-slate-700">{labels[key] ?? key}</span>
                <input
                  inputMode="decimal"
                  placeholder={money(v)}
                  aria-label={`Price for ${labels[key] ?? key}`}
                  className={`${inputClass} mt-1`}
                  {...register(`overrides.${key}` as const)}
                />
                {errors?.[key] && <span className="mt-1 block text-xs text-red-600">{errors[key]?.message}</span>}
              </label>
            ))}
          </div>
          {changed > 0 && (
            <Button type="button" variant="ghost" size="sm" className="mt-3" onClick={() => setValue("overrides", Object.fromEntries(Object.keys(values).map((k) => [k, ""])), { shouldDirty: true })}>
              Reset to defaults
            </Button>
          )}
        </div>
      )}
    </Card>
  );
}
