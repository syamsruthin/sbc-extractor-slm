import { Route, Routes } from "react-router-dom";

import { Layout } from "@/components/Layout";
import { EmptyState } from "@/components/ui";
import { CatalogPage } from "@/pages/CatalogPage";
import { CompareBuilderPage } from "@/pages/CompareBuilderPage";
import { ComparisonPage } from "@/pages/ComparisonPage";
import { HistoryPage } from "@/pages/HistoryPage";
import { PlanDetailPage } from "@/pages/PlanDetailPage";
import { PlansPage } from "@/pages/PlansPage";

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<PlansPage />} />
        <Route path="plans/:id" element={<PlanDetailPage />} />
        <Route path="catalog" element={<CatalogPage />} />
        <Route path="compare" element={<CompareBuilderPage />} />
        <Route path="comparisons" element={<HistoryPage />} />
        <Route path="comparisons/:id" element={<ComparisonPage />} />
        <Route path="*" element={<EmptyState title="Page not found">That link doesn't go anywhere.</EmptyState>} />
      </Route>
    </Routes>
  );
}
