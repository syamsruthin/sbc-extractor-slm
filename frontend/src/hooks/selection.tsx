import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export const MAX_PLANS = 5;

export type SelectedPlan = {
  documentId: string;
  label: string;
  source: "upload" | "catalog";
  catalogPlanId?: string | null;
  issuer?: string | null;
};

type Ctx = {
  items: SelectedPlan[];
  has: (documentId: string) => boolean;
  toggle: (p: SelectedPlan) => boolean;
  remove: (documentId: string) => void;
  clear: () => void;
  replace: (items: SelectedPlan[]) => void;
};

const SelectionContext = createContext<Ctx | null>(null);
const KEY = "plan-compare:selection";

function load(): SelectedPlan[] {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as SelectedPlan[]).slice(0, MAX_PLANS) : [];
  } catch {
    return [];
  }
}

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<SelectedPlan[]>(load);
  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(items));
    } catch {
      /* private mode: selection lasts for this tab only */
    }
  }, [items]);

  const has = useCallback((id: string) => items.some((i) => i.documentId === id), [items]);
  const toggle = useCallback(
    (p: SelectedPlan) => {
      if (items.some((i) => i.documentId === p.documentId)) {
        setItems((xs) => xs.filter((i) => i.documentId !== p.documentId));
        return true;
      }
      if (items.length >= MAX_PLANS) return false;
      setItems((xs) => [...xs, p]);
      return true;
    },
    [items],
  );
  const remove = useCallback((id: string) => setItems((xs) => xs.filter((i) => i.documentId !== id)), []);
  const clear = useCallback(() => setItems([]), []);
  const replace = useCallback((xs: SelectedPlan[]) => setItems(xs.slice(0, MAX_PLANS)), []);
  const value = useMemo(() => ({ items, has, toggle, remove, clear, replace }), [items, has, toggle, remove, clear, replace]);
  return <SelectionContext.Provider value={value}>{children}</SelectionContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useSelection(): Ctx {
  const c = useContext(SelectionContext);
  if (!c) throw new Error("useSelection outside SelectionProvider");
  return c;
}
