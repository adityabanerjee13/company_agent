// Live updates: one EventSource to /api/events. Any data change bumps `tick`, and every view
// fetched through useLiveData refetches in place (keeping what it shows until the new data lands).
import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, enc } from "./lib.js";

const LiveContext = createContext(null);
const DirectoryContext = createContext(null);

export function LiveProvider({ children }) {
  const [status, setStatus] = useState(null);
  const [connected, setConnected] = useState(false);
  const [tick, setTick] = useState(0);
  const [lastChange, setLastChange] = useState(null);
  const pending = useRef(null);

  useEffect(() => {
    const source = new EventSource("/api/events");
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false); // EventSource reconnects by itself
    source.onmessage = (e) => {
      const event = JSON.parse(e.data);
      if (event.type === "sync") {
        setStatus(event.status);
        return;
      }
      setLastChange({ ...event, at: Date.now() });
      // several writes land together (a message + its reply + the trace file): refetch once
      clearTimeout(pending.current);
      pending.current = setTimeout(() => setTick((t) => t + 1), 250);
    };
    return () => source.close();
  }, []);

  const value = useMemo(() => ({ status, connected, tick, lastChange }), [status, connected, tick, lastChange]);
  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

export const useLive = () => useContext(LiveContext);

export function useLiveData(path) {
  const { tick } = useLive();
  const [state, setState] = useState({ data: null, error: null, path: null });
  useEffect(() => {
    if (!path) return;
    let cancelled = false;
    api(path)
      .then((data) => !cancelled && setState({ data, error: null, path }))
      .catch((error) => !cancelled && setState((s) => ({ data: s.path === path ? s.data : null, error, path })));
    return () => { cancelled = true; };
  }, [path, tick]);
  const stale = state.path !== path;
  return { data: stale ? null : state.data, error: stale ? null : state.error, loading: stale || (!state.data && !state.error) };
}

// Users and conversations, needed by the sidebar and for rendering names everywhere.
export function DirectoryProvider({ children }) {
  const [selectedUser, setSelectedUser] = useState("");
  const users = useLiveData("/api/users").data || [];
  const allConvs = useLiveData("/api/conversations").data || [];
  const userConvs = useLiveData(selectedUser ? `/api/conversations?user=${enc(selectedUser)}` : null).data;
  const names = useMemo(() => Object.fromEntries(users.map((u) => [u.id, u.name])), [users]);
  const value = useMemo(() => {
    const userName = (id) => (id ? names[id] || id : "unknown");
    const channelName = (id) => allConvs.find((c) => c.id === id)?.name || id;
    const isBot = (id) => id === "bot" || users.some((u) => u.id === id && u.is_bot);
    const user = (id) => users.find((u) => u.id === id);
    return {
      users, allConvs, convs: selectedUser ? userConvs || [] : allConvs,
      selectedUser, setSelectedUser, userName, channelName, isBot, user,
    };
  }, [users, allConvs, userConvs, selectedUser, names]);
  return <DirectoryContext.Provider value={value}>{children}</DirectoryContext.Provider>;
}

export const useDirectory = () => useContext(DirectoryContext);

// Breadcrumbs: pages declare theirs, the top bar renders them.
const CrumbsContext = createContext(null);

export function CrumbsProvider({ children }) {
  const [crumbs, setCrumbs] = useState([]);
  return <CrumbsContext.Provider value={{ crumbs, setCrumbs }}>{children}</CrumbsContext.Provider>;
}

export function useCrumbs(items) {
  const { setCrumbs } = useContext(CrumbsContext);
  const key = JSON.stringify(items);
  useEffect(() => { setCrumbs(items); }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
}

export const useCrumbState = () => useContext(CrumbsContext).crumbs;
