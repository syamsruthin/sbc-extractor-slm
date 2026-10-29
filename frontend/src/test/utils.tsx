import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { StrictMode, type ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";

import { SelectionProvider } from "@/hooks/selection";

/** Route table: path -> JSON body (or [status, body]). Unmatched requests fail the test loudly. */
export function mockFetch(routes: Record<string, unknown>) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const key = Object.keys(routes).find((k) => {
      const [method, path] = k.includes(" ") ? k.split(" ") : ["GET", k];
      return (init?.method ?? "GET") === method && url.split("?")[0].endsWith(path);
    });
    if (!key) throw new Error(`unmocked request ${init?.method ?? "GET"} ${url}`);
    const v = routes[key];
    const [status, body] = Array.isArray(v) && typeof v[0] === "number" ? (v as [number, unknown]) : [200, v];
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return { fn, calls };
}

export function renderAt(
  ui: ReactElement,
  { path = "/", route = "/", cache = {} }: { path?: string; route?: string; cache?: Record<string, unknown> } = {},
) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // data already in the query cache, as after navigating from another page (key: JSON of the query key)
  for (const [key, data] of Object.entries(cache)) qc.setQueryData(JSON.parse(key), data);
  return render(
    <StrictMode>
    <QueryClientProvider client={qc}>
      <SelectionProvider>
        <MemoryRouter initialEntries={[route]}>
          <Routes>
            <Route path={path} element={ui} />
            <Route path="*" element={<div>other page</div>} />
          </Routes>
        </MemoryRouter>
      </SelectionProvider>
    </QueryClientProvider>
    </StrictMode>,
  );
}
