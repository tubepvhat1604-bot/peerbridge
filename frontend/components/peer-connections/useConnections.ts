"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ConnectionResponse, ConnectionsResponse } from "@/lib/types";
import { errorMessage } from "./shared";

export function useConnections(token: string) {
  const [data, setData] = useState<ConnectionsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const mounted = useRef(true);
  const inFlight = useRef<Promise<ConnectionsResponse | null> | null>(null);

  const refresh = useCallback((): Promise<ConnectionsResponse | null> => {
    if (inFlight.current) return inFlight.current;
    setLoading(true);
    setError("");
    const request = (async () => {
      try {
        const result = await api.listConnections(token);
        if (mounted.current) setData(result);
        return result;
      } catch (failure) {
        if (mounted.current) setError(errorMessage(failure));
        return null;
      } finally {
        inFlight.current = null;
        if (mounted.current) setLoading(false);
      }
    })();
    inFlight.current = request;
    return request;
  }, [token]);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => { mounted.current = false; };
  }, [refresh]);

  function updateRequest(response: ConnectionResponse) {
    setData((current) => current ? {
      ...current,
      incoming: current.incoming.map((item) => item.id === response.id
        ? { ...item, status: response.status, responded_at: response.responded_at } : item),
      sent: current.sent.map((item) => item.id === response.id
        ? { ...item, status: response.status, responded_at: response.responded_at } : item),
    } : current);
  }

  return { data, loading, error, refresh, updateRequest };
}
