export type AccountStatus = "ACTIVE" | "BLOCKED" | "CLOSED";
export interface Account {
  id: string;
  customer_id: string;
  account_number: string;
  product_type: "SAVINGS_ACCOUNT";
  currency: string;
  status: AccountStatus;
  opened_at: string;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
}
export interface AccountPage {
  items: Account[];
  pagination: { limit: number; offset: number; total_items: number; total_pages: number };
}
export class ApiError extends Error {
  constructor(message: string, public status: number | null) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try { response = await fetch(`/api${path}`, init); }
  catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("No se puede conectar con CBS. Comprueba que su API está arrancada en el puerto 8001.", null);
  }
  if (!response.ok) {
    if (response.status === 503) throw new ApiError("La base de datos de CBS no está disponible. Comprueba PostgreSQL y el modo postgres del backend.", 503);
    if (response.status >= 500) throw new ApiError("CBS no ha podido completar la operación. Inténtalo de nuevo.", response.status);
    let detail: unknown;
    try { detail = (await response.json() as { detail?: unknown }).detail; } catch { /* No JSON body. */ }
    const message = typeof detail === "string" ? detail : Array.isArray(detail)
      ? detail.map((item: { msg?: string }) => item.msg || "Entrada no válida").join(". ") : "La solicitud no es válida.";
    throw new ApiError(response.status === 404 ? "Cuenta no encontrada." : message, response.status);
  }
  try { return await response.json() as T; }
  catch { throw new ApiError("CBS ha devuelto una respuesta no válida.", response.status); }
}

export const getAccount = (id: string, signal?: AbortSignal) => request<Account>(`/accounts/${encodeURIComponent(id)}`, { signal });
export const getAccountByNumber = (number: string) => request<Account>(`/accounts/by-number/${encodeURIComponent(number)}`);
export function listAccounts(customer: string, limit: number, offset: number, signal?: AbortSignal) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (customer) params.set("customer_id", customer);
  return request<AccountPage>(`/accounts?${params}`, { signal });
}
export const createAccount = (payload: { customer_id: string; currency: string }) => request<Account>("/accounts", {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
});
export const changeAccountState = (id: string, operation: "block" | "reactivate") => request<Account>(`/accounts/${encodeURIComponent(id)}/${operation}`, { method: "PATCH" });
export const errorMessage = (error: unknown) => error instanceof Error ? error.message : "No se ha podido completar la operación.";
