import { ApiError, request } from "./http";
import type { Account, AccountPage } from "./accounts";
import type { Balance, Movement, Page, MonetaryPayload, Transaction } from "./transactions";
export type CustomerTransaction = Pick<Transaction, "id" | "transaction_type" | "status" | "amount" | "currency" | "description" | "effective_at" | "posted_at">;
export type CustomerDetail = CustomerTransaction & { movements: Page<Movement> };
export const getCustomerAccount = (id: string, signal?: AbortSignal) => request<Account>(`/me/accounts/${encodeURIComponent(id)}`, { signal });
export const getCustomerBalance = (id: string, signal?: AbortSignal) => request<Balance>(`/me/accounts/${encodeURIComponent(id)}/balance`, { signal });
export const getCustomerMovements = (id: string, limit: number, offset: number, signal?: AbortSignal) => request<Page<Movement>>(`/me/accounts/${encodeURIComponent(id)}/movements?limit=${limit}&offset=${offset}`, { signal });
export const listCustomerAccounts = (limit: number, offset: number, signal?: AbortSignal) => request<AccountPage>(`/me/accounts?limit=${limit}&offset=${offset}`, { signal });
export function listCustomerTransactions(type: string, status: string, limit: number, offset: number, signal?: AbortSignal) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (type) params.set("transaction_type", type); if (status) params.set("status", status);
  return request<Page<CustomerTransaction>>(`/me/transactions?${params}`, { signal });
}
export const getCustomerTransaction = (id: string, limit = 20, offset = 0, signal?: AbortSignal) => request<CustomerDetail>(`/me/transactions/${encodeURIComponent(id)}?limit=${limit}&offset=${offset}`, { signal });
export async function postCustomerTransfer(payload: MonetaryPayload, key: string): Promise<CustomerTransaction> {
  const result = await request<CustomerTransaction>("/me/transfers", { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": key }, body: JSON.stringify(payload) });
  const timestamp = (value: unknown) => typeof value === "string" && /(Z|[+-]\d{2}:\d{2})$/.test(value) && !Number.isNaN(Date.parse(value));
  if (!result || typeof result.id !== "string" || !/^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i.test(result.id) || result.status !== "POSTED" || result.transaction_type !== "TRANSFER" || result.amount !== payload.amount || result.currency !== payload.currency || result.description !== payload.description || !timestamp(result.posted_at) || !timestamp(result.effective_at)) throw new ApiError("Confirmación incompleta. Reintenta con la misma clave.", 201);
  return result;
}
