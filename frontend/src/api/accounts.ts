import { request } from "./http";
export { ApiError } from "./http";
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
