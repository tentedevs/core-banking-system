import type { MonetaryPayload, Operation } from "./api/transactions";
export const intentStorageKey = "cbs.monetary-intent.v1";
export interface Intent { customer_id?: string; destination_reference?: string; version: 1; operation: Operation; payload: MonetaryPayload; key: string; outcome: "ready" | "uncertain" | "failed" }
const uuid = /^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i;
export function decimalAmount(value: string): string {
  const trimmed = value.trim();
  if (!/^(0|[1-9]\d{0,15})(?:\.\d{1,2})?$/.test(trimmed) || !/[1-9]/.test(trimmed)) throw new Error("Introduce un importe positivo, con punto y hasta dos decimales (máximo 16 cifras enteras).");
  const [whole = "", fraction = ""] = trimmed.split(".");
  return `${whole}.${fraction.padEnd(2, "0")}`;
}
export function loadIntent(): { intent: Intent | null; error: string | null } {
  try {
    const raw = sessionStorage.getItem(intentStorageKey);
    if (!raw) return { intent: null, error: null };
    const value = JSON.parse(raw) as Intent;
    if (value.version !== 1 || !["deposit", "withdrawal", "transfer"].includes(value.operation) || !["ready", "uncertain", "failed"].includes(value.outcome) || typeof value.key !== "string" || !value.key.trim() || value.key.length > 100) throw new Error();
    if ((value.customer_id !== undefined && (typeof value.customer_id !== "string" || !uuid.test(value.customer_id))) || (value.destination_reference !== undefined && typeof value.destination_reference !== "string")) throw new Error();
    const p = value.payload;
    if (!p || typeof p.amount !== "string" || decimalAmount(p.amount) !== p.amount || !/^[A-Z]{3}$/.test(p.currency) || (p.description !== null && typeof p.description !== "string")) throw new Error();
    const fields = value.operation === "transfer" ? ["source_account_id", "destination_account_id"] : ["account_id"];
    if (!fields.every(field => uuid.test(String(p[field as keyof MonetaryPayload] ?? ""))) || Object.keys(p).some(field => ![...fields, "amount", "currency", "description"].includes(field))) throw new Error();
    if (value.operation === "transfer" && p.source_account_id === p.destination_account_id) throw new Error();
    return { intent: value, error: null };
  } catch { return { intent: null, error: "No se puede recuperar la petición guardada. No envíes otra operación hasta revisar el resultado de la anterior y el almacenamiento de esta sesión." }; }
}
export function saveIntent(intent: Intent) { sessionStorage.setItem(intentStorageKey, JSON.stringify(intent)); }
