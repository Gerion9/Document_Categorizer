import { useCallback, useRef, useState } from "react";

export function useBusyActions() {
  const busyRef = useRef(new Set<string>());
  const [busy, setBusy] = useState<ReadonlySet<string>>(() => new Set());

  const syncBusy = useCallback(() => {
    setBusy(new Set(busyRef.current));
  }, []);

  const isBusy = useCallback(
    (key: string) => busy.has(key),
    [busy]
  );

  const run = useCallback(
    async (key: string, fn: () => Promise<void>) => {
      if (busyRef.current.has(key)) return;
      busyRef.current.add(key);
      syncBusy();
      try {
        await fn();
      } finally {
        busyRef.current.delete(key);
        syncBusy();
      }
    },
    [syncBusy]
  );

  return { isBusy, run };
}
