import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, get, setWorkspace, type Me } from "./api";

interface AppState {
  me: Me | null;
  loading: boolean;
  needsSetup: boolean;
  refresh: () => Promise<void>;
  switchWorkspace: (id: string) => Promise<void>;
  theme: "system" | "light" | "dark";
  setTheme: (t: "system" | "light" | "dark") => void;
  toast: (msg: string, kind?: "info" | "error") => void;
}

const Ctx = createContext<AppState | null>(null);

function readTheme(): "system" | "light" | "dark" {
  try {
    const t = window.localStorage.getItem("prism.theme");
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [theme, setThemeState] = useState(readTheme);
  const [toasts, setToasts] = useState<{ id: number; msg: string; kind: string }[]>([]);

  const refresh = useCallback(async () => {
    try {
      const status = await get<{ needs_setup: boolean }>("/api/v1/setup/status");
      setNeedsSetup(status.needs_setup);
      if (status.needs_setup) {
        setMe(null);
        return;
      }
      setMe(await get<Me>("/api/v1/auth/me"));
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) setMe(null);
      else throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh().catch(() => setLoading(false));
  }, [refresh]);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
  }, [theme]);

  const setTheme = (t: "system" | "light" | "dark") => {
    setThemeState(t);
    try {
      window.localStorage.setItem("prism.theme", t);
    } catch {
      /* ignore */
    }
  };

  const switchWorkspace = async (id: string) => {
    setWorkspace(id);
    await refresh();
  };

  const toast = useCallback((msg: string, kind: "info" | "error" = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, msg, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "error" ? 6000 : 3500);
  }, []);

  const value = useMemo(
    () => ({ me, loading, needsSetup, refresh, switchWorkspace, theme, setTheme, toast }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [me, loading, needsSetup, refresh, theme, toast],
  );
  return (
    <Ctx.Provider value={value}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind === "error" ? "error" : ""}`}>
            {t.msg}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp outside provider");
  return v;
}

/** Load data from the API with loading/error state and a reload function. */
export function useLoad<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!!path);
  const load = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try {
      setData(await get<T>(path));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  useEffect(() => {
    void load();
  }, [load]);
  return { data, error, loading, reload: load, setData };
}

/** The theme actually shown ("system" resolved against the OS setting). */
export function effectiveTheme(pref: string): "light" | "dark" {
  if (pref === "light" || pref === "dark") return pref;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
