import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError, request } from "../api/http";
import { intentStorageKey } from "../operationIntent";
import { navigateToLogin } from "./navigation";

export interface AuthActor { id: string; email: string; applications: { application_code: string; actor_type: "ADMIN" | "CUSTOMER" }[] }
export interface BankingIdentity { actor_id: string; application_code: "CBS"; actor_type: "ADMIN" | "CUSTOMER"; customer_id: string | null; link_status: "LINKED" | "PENDING_LINK" | "NOT_APPLICABLE" }
interface State { status: "loading" | "ready" | "unauthenticated" | "denied" | "error"; actor: AuthActor | null; identity: BankingIdentity | null; error: string | null; version: number }
interface AuthValue extends State { restore: () => Promise<void>; logout: () => Promise<void>; isCurrentSession: (actorId: string, version: number) => boolean }
const AuthContext = createContext<AuthValue | null>(null);
function clearIntent() { try { sessionStorage.removeItem(intentStorageKey); } catch { /* Private UI is still unmounted. */ } }
async function authRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try { response = await fetch(`/auth/${path}`, { ...init, credentials: "same-origin", cache: "no-store" }); }
  catch (error) { if (error instanceof DOMException && error.name === "AbortError") throw error; throw new ApiError("El servicio de autenticación no está disponible.", null); }
  if (!response.ok) throw new ApiError(response.status === 401 ? "Sesión no válida." : response.status === 403 ? "Acceso denegado." : "El servicio de autenticación no está disponible.", response.status);
  if (path === "logout" && response.status !== 204) throw new ApiError("No se ha confirmado el cierre de sesión.", response.status);
  if (response.status === 204) return undefined as T;
  try { return await response.json() as T; }
  catch { throw new ApiError("El servicio de autenticación ha devuelto una respuesta inválida.", response.status); }
}
export function AuthProvider({ children }: { children: ReactNode }) {
  const [cache, setCache] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }));
  const cacheRef = useRef(cache);
  const epoch = useRef(0); const controller = useRef<AbortController | null>(null);
  const owner = useRef<{ actorId: string; version: number } | null>(null);
  const [state, setState] = useState<State>({ status: "loading", actor: null, identity: null, error: null, version: 0 });
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const resetCache = useCallback(() => {
    void cacheRef.current.cancelQueries(); cacheRef.current.clear();
    const fresh = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    cacheRef.current = fresh; setCache(fresh);
  }, []);
  const restore = useCallback(async () => {
    const version = ++epoch.current; owner.current = null;
    controller.current?.abort(); const abort = new AbortController(); controller.current = abort;
    setState({ status: "loading", actor: null, identity: null, error: null, version }); resetCache();
    const deadline = window.setTimeout(() => {
      if (epoch.current !== version) return;
      ++epoch.current; owner.current = null; abort.abort();
      setState({ status: "error", actor: null, identity: null, error: "La comprobación de sesión ha tardado demasiado. Comprueba que CBS y el servicio de autenticación están arrancados y reintenta la conexión.", version });
    }, 10_000);
    try {
      const actor = await authRequest<AuthActor>("me", { signal: abort.signal });
      if (epoch.current !== version) return;
      const access = actor.applications.find(item => item.application_code === "CBS");
      if (!access) { clearIntent(); setState({ status: "denied", actor, identity: null, error: "Tu cuenta no tiene acceso a CBS.", version }); return; }
      const identity = await request<BankingIdentity>("/me", { signal: abort.signal });
      if (epoch.current !== version) return;
      const validRole = identity.actor_type === "ADMIN" || identity.actor_type === "CUSTOMER";
      const validLink = identity.actor_type === "ADMIN"
        ? identity.link_status === "NOT_APPLICABLE" && identity.customer_id === null
        : (identity.link_status === "PENDING_LINK" && identity.customer_id === null)
          || (identity.link_status === "LINKED" && typeof identity.customer_id === "string" && /^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i.test(identity.customer_id));
      if (!validRole || !validLink || identity.actor_id !== actor.id || identity.application_code !== "CBS" || identity.actor_type !== access.actor_type) throw new ApiError("No se ha podido verificar la identidad de CBS.", 503);
      try { const pending = sessionStorage.getItem(intentStorageKey); if (pending && (JSON.parse(pending) as { actor_id?: string }).actor_id !== actor.id) clearIntent(); } catch { clearIntent(); }
      owner.current = { actorId: actor.id, version };
      setState({ status: "ready", actor, identity, error: null, version });
    } catch (error) {
      if (epoch.current !== version || abort.signal.aborted) return;
      const status = error instanceof ApiError ? error.status : null;
      if (status === 401 || status === 403) clearIntent();
      setState({ status: status === 401 ? "unauthenticated" : status === 403 ? "denied" : "error", actor: null, identity: null, error: error instanceof Error ? error.message : "No se ha podido restaurar la sesión.", version });
    } finally {
      window.clearTimeout(deadline);
    }
  }, [resetCache]);
  const disposeSession = useCallback(() => {
    ++epoch.current; owner.current = null; controller.current?.abort();
    void cacheRef.current.cancelQueries(); cacheRef.current.clear();
  }, []);
  useEffect(() => {
    void restore();
    const expired = () => {
      const version = ++epoch.current; owner.current = null; controller.current?.abort(); clearIntent(); resetCache();
      setState({ status: "unauthenticated", actor: null, identity: null, error: null, version });
    };
    window.addEventListener("cbs:unauthenticated", expired);
    return () => { window.removeEventListener("cbs:unauthenticated", expired); disposeSession(); };
  }, [restore, resetCache, disposeSession]);
  async function logout() {
    setLogoutError(null);
    try {
      await authRequest<void>("logout", { method: "POST" });
      const version = ++epoch.current; owner.current = null; controller.current?.abort(); clearIntent(); resetCache();
      setState({ status: "unauthenticated", actor: null, identity: null, error: null, version });
      navigateToLogin();
    } catch { setLogoutError("No se ha podido confirmar el cierre de sesión. Inténtalo de nuevo."); }
  }
  const isCurrentSession = (actorId: string, version: number) => owner.current?.actorId === actorId && owner.current.version === version;
  return <AuthContext.Provider value={{ ...state, restore, logout, isCurrentSession }}><QueryClientProvider client={cache}>{logoutError && <p role="alert" className="notice error">{logoutError}</p>}{children}</QueryClientProvider></AuthContext.Provider>;
}
// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() { const value = useContext(AuthContext); if (!value) throw new Error("AuthProvider is required"); return value; }
export function SessionControls() {
  const auth = useAuth(); const [busy, setBusy] = useState(false);
  return <><span>{auth.actor?.email}</span><button className="button secondary" disabled={busy} onClick={() => { setBusy(true); void auth.logout().finally(() => setBusy(false)); }}>{busy ? "Cerrando…" : "Cerrar sesión"}</button></>;
}
