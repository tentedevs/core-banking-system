import { ApiError, request } from "./http";
import type { AccountPage } from "./accounts";

export type TransactionType = "DEPOSIT" | "WITHDRAWAL" | "TRANSFER";
export type TransactionStatus = "PENDING" | "POSTED" | "REJECTED" | "REVERSED";
export type Operation = "deposit" | "withdrawal" | "transfer";
export interface Transaction {
  id: string; transaction_type: TransactionType; status: TransactionStatus;
  amount: string; currency: string; description: string | null;
  effective_at: string; posted_at: string | null; created_at: string;
  idempotency_key: string | null; reversal_of_id: string | null;
}
export interface Movement {
  id: string; transaction_id: string; account_id: string; direction: "CREDIT" | "DEBIT";
  amount: string; balance_after: string | null; booked_at: string;
  category?: string | null; counterparty_account?: string | null; counterparty_bank?: string | null;
}
export interface Balance { account_id: string; booked_balance: string; available_balance: string; updated_at: string }
export interface Page<T> { items: T[]; pagination: AccountPage["pagination"] }
export interface MonetaryPayload { amount: string; currency: string; description: string | null; account_id?: string; source_account_id?: string; destination_account_id?: string }
export function listTransactions(type: string, status: string, limit: number, offset: number, signal?: AbortSignal) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (type) params.set("transaction_type", type);
  if (status) params.set("status", status);
  return request<Page<Transaction>>(`/transactions?${params}`, { signal });
}
export const getTransaction = (id: string, signal?: AbortSignal) => request<Transaction>(`/transactions/${encodeURIComponent(id)}`, { signal });
export const getBalance = (id: string, signal?: AbortSignal) => request<Balance>(`/accounts/${encodeURIComponent(id)}/balance`, { signal });
export const listMovements = (scope: "accounts" | "transactions", id: string, limit: number, offset: number, signal?: AbortSignal) => request<Page<Movement>>(`/${scope}/${encodeURIComponent(id)}/movements?limit=${limit}&offset=${offset}`, { signal });
export async function postOperation(operation: Operation, payload: MonetaryPayload, key: string): Promise<Transaction> {
  const result = await request<Partial<Transaction> | null>(`/transactions/${operation === "deposit" ? "deposits" : operation === "withdrawal" ? "withdrawals" : "transfers"}`, {
    method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": key }, body: JSON.stringify(payload),
  });
  const uuid = /^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i;
  const timestamp = (value: unknown) => typeof value === "string" && /(Z|[+-]\d{2}:\d{2})$/.test(value) && !Number.isNaN(Date.parse(value));
  const type = operation === "deposit" ? "DEPOSIT" : operation === "withdrawal" ? "WITHDRAWAL" : "TRANSFER";
  // A successful HTTP response with incomplete/mismatched JSON is still uncertain.
  // Never discard a key until the backend confirms this exact posted request.
  if (!result || typeof result.id !== "string" || !uuid.test(result.id) || result.status !== "POSTED" || result.transaction_type !== type || result.idempotency_key !== key || result.amount !== payload.amount || result.currency !== payload.currency || result.description !== payload.description || result.reversal_of_id !== null || !timestamp(result.posted_at) || !timestamp(result.effective_at) || !timestamp(result.created_at)) {
    throw new ApiError("CBS ha devuelto una confirmación incompleta. Conserva esta petición y reinténtala con su clave original.", 201);
  }
  return result as Transaction;
}
