"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { LedgerEvent } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  const res = await fetch(`/api${path}`, {
    ...rest,
    headers: json !== undefined ? { "content-type": "application/json", ...rest.headers } : rest.headers,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {}
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------- live ledger

type Listener = (e: LedgerEvent) => void;
const listeners = new Set<Listener>();
let source: EventSource | null = null;
let liveSlug: string | null = null;

/** Point the live feed at the business the owner has open (called by the business provider). */
export function setLiveBusiness(slug: string | null) {
  if (slug === liveSlug) return;
  if (liveSlug) cache.clear(); // another business: nothing cached belongs to it
  liveSlug = slug;
  source?.close();
  source = null;
  if (listeners.size) ensureSource();
}

function ensureSource() {
  if (source || typeof window === "undefined" || !liveSlug) return;
  const slug = liveSlug;
  source = new EventSource(`/api/businesses/${slug}/events`);
  source.addEventListener("ledger", (m) => {
    const ev = JSON.parse((m as MessageEvent).data) as LedgerEvent;
    listeners.forEach((l) => l(ev));
  });
  source.onerror = () => {
    source?.close();
    source = null;
    setTimeout(() => listeners.size && liveSlug === slug && ensureSource(), 3000);
  };
}

export function useLedgerEvents(onEvent: Listener) {
  const ref = useRef(onEvent);
  ref.current = onEvent;
  useEffect(() => {
    const l: Listener = (e) => ref.current(e);
    listeners.add(l);
    ensureSource();
    return () => {
      listeners.delete(l);
    };
  }, []);
}

// Last answer per path, kept while the tab is open: a page opened again shows what it showed before at once and
// refreshes in the background, instead of starting from a skeleton. Reads of the same path that overlap share one
// request (the header, the page and a card often ask for the same thing).
const cache = new Map<string, unknown>();
const inflight = new Map<string, Promise<unknown>>();

function load<T>(path: string): Promise<T> {
  let p = inflight.get(path) as Promise<T> | undefined;
  if (!p) {
    p = api<T>(path).then(
      (v) => {
        cache.set(path, v);
        inflight.delete(path);
        return v;
      },
      (e) => {
        inflight.delete(path);
        throw e;
      },
    );
    inflight.set(path, p);
  }
  return p;
}

/** Fetch a resource and refetch it whenever the ledger reports a change (debounced). */
export function useResource<T>(path: string | null, filter?: (e: LedgerEvent) => boolean) {
  const [data, setData] = useState<T | null>(() => (path ? ((cache.get(path) as T | undefined) ?? null) : null));
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const reload = useCallback(async () => {
    if (!path) return;
    try {
      setData(await load<T>(path));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [path]);

  useEffect(() => {
    if (path) setData((cache.get(path) as T | undefined) ?? null);
    reload();
  }, [reload, path]);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  useLedgerEvents((e) => {
    if (filter && !filter(e)) return;
    if (timer.current) clearTimeout(timer.current);
    // An agent at work writes many ledger lines in a burst; refetch once it pauses.
    timer.current = setTimeout(reload, 500);
  });

  return { data, error, reload };
}
