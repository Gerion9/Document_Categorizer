import toast from "react-hot-toast";

import type { RagMatch } from "../types";
import { getApiErrorMessage } from "./apiErrors";

interface SemanticSearchResult {
  matches: RagMatch[];
}

interface RunSemanticSearchOptions {
  query: string;
  search: (query: string) => Promise<SemanticSearchResult>;
  setSearching: (value: boolean) => void;
  setResults: (matches: RagMatch[]) => void;
  fallbackError: string;
  emptyMessage?: string;
}

export async function runSemanticSearch({
  query,
  search,
  setSearching,
  setResults,
  fallbackError,
  emptyMessage = "Sin resultados para esa consulta",
}: RunSemanticSearchOptions): Promise<void> {
  const normalizedQuery = query.trim();
  if (!normalizedQuery) {
    return;
  }

  setSearching(true);
  try {
    const result = await search(normalizedQuery);
    setResults(result.matches);
    if (result.matches.length === 0) {
      toast(emptyMessage);
    }
  } catch (error: unknown) {
    toast.error(getApiErrorMessage(error, fallbackError));
  } finally {
    setSearching(false);
  }
}
