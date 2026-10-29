import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, ApiError, type ComparisonRequest, type DocumentSummary } from "@/api/client";

const busy = (d: DocumentSummary) =>
  d.status === "queued" || d.status === "extracting" || d.summaries_status === "running";

export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000, retry: false });
}

export function useDocuments() {
  return useQuery({
    queryKey: ["documents"],
    queryFn: api.listDocuments,
    refetchInterval: (q) => (q.state.data?.items.some(busy) ? 1500 : false),
  });
}

export function useDocument(id: string | undefined) {
  return useQuery({
    queryKey: ["document", id],
    queryFn: () => api.getDocument(id!),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data && busy(q.state.data) ? 1500 : false),
  });
}

export function useUpload() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.uploadDocument,
    onSuccess: (doc) => {
      qc.invalidateQueries({ queryKey: ["documents"] });
      toast.success(doc.status === "ready" ? `${doc.filename} is already processed` : `Uploaded ${doc.filename}`);
    },
    onError: (e, file) => toast.error(`${file.name}: ${e instanceof ApiError ? e.message : "upload failed"}`),
  });
}

export function useDeleteDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.deleteDocument,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["documents"] });
      toast.success("Plan removed");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Couldn't remove the plan"),
  });
}

export function useGenerateSummaries() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.generateSummaries,
    onSuccess: (_, id) => qc.invalidateQueries({ queryKey: ["document", id] }),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Couldn't start summaries"),
  });
}

export function useCatalog(params: Parameters<typeof api.searchCatalog>[0]) {
  return useQuery({ queryKey: ["catalog", params], queryFn: () => api.searchCatalog(params), placeholderData: keepPreviousData });
}

export function useFacets() {
  return useQuery({ queryKey: ["facets"], queryFn: api.facets, staleTime: 60_000 });
}

export function useScenarios() {
  return useQuery({ queryKey: ["scenarios"], queryFn: api.scenarios, staleTime: Infinity });
}

export function useReferencePrices() {
  return useQuery({ queryKey: ["reference-prices"], queryFn: api.referencePrices, staleTime: Infinity });
}

export function useCreateComparison() {
  return useMutation({
    mutationFn: (req: ComparisonRequest) => api.createComparison(req),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Comparison failed"),
  });
}

export function useComparison(id: string | undefined) {
  return useQuery({
    queryKey: ["comparison", id],
    queryFn: () => api.getComparison(id!),
    enabled: !!id,
    refetchInterval: (q) => {
      const s = q.state.data?.explanation_status;
      return s === "pending" || s === "running" ? 1500 : false;
    },
  });
}

export function useRegenerateExplanation(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.regenerateExplanation(id),
    onSuccess: (data) => qc.setQueryData(["comparison", id], data),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Couldn't regenerate"),
  });
}

export function useComparisons() {
  return useQuery({ queryKey: ["comparisons"], queryFn: api.listComparisons });
}

export function useDeleteComparison() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string | "all") => (id === "all" ? api.deleteAllComparisons() : api.deleteComparison(id)),
    onSuccess: (_, id) => {
      qc.invalidateQueries({ queryKey: ["comparisons"] });
      toast.success(id === "all" ? "All saved comparisons deleted" : "Comparison deleted");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Couldn't delete"),
  });
}
