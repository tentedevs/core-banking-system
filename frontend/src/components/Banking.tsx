import { useState } from "react";
import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { errorMessage } from "../api/accounts";
import { getCustomerBalance, getCustomerMovements } from "../api/customer";
import { getBalance, listMovements } from "../api/transactions";
import type { Movement, Page, TransactionStatus } from "../api/transactions";

const statuses: Record<TransactionStatus, string> = { PENDING: "Pendiente", POSTED: "Registrada", REJECTED: "Rechazada", REVERSED: "Revertida" };
export function TransactionState({ status }: { status: TransactionStatus }) { return <span className={`status status-${status.toLowerCase()}`}>{statuses[status]}</span>; }
export function ErrorNotice({ error }: { error: unknown }) { return <p role="alert" className="notice error">{errorMessage(error)}</p>; }
export function Timestamp({ value }: { value: string | null }) { return <>{value ? new Date(value).toLocaleString("es") : "—"}</>; }
export function Money({ amount, currency }: { amount: string | null; currency?: string }) { return <span className="money">{amount ?? "—"}{currency ? ` ${currency}` : ""}</span>; }
export function Pagination({ pagination, length, busy, onOffset, onLimit, label }: {
  pagination: Page<unknown>["pagination"]; length: number; busy: boolean;
  onOffset: (offset: number) => void; onLimit: (limit: number) => void; label: string;
}) {
  const { offset, limit, total_items } = pagination;
  return <div className="pagination"><label>Por página <select aria-label={`${label} por página`} value={limit} onChange={e => onLimit(Number(e.target.value))}><option value={20}>20</option><option value={50}>50</option><option value={100}>100</option></select></label><span>{length ? `${offset + 1}–${offset + length}` : "0"} de {total_items}</span><div><button className="button secondary" disabled={!offset || busy} onClick={() => onOffset(Math.max(0, offset - limit))}>Anterior</button><button className="button secondary" disabled={offset + limit >= total_items || busy} onClick={() => onOffset(offset + limit)}>Siguiente</button></div></div>;
}
export function AccountBalance({ accountId, currency, queryPrefix, customer = false }: { accountId: string; currency: string; queryPrefix?: readonly (string | null)[]; customer?: boolean }) {
  const query = useQuery({ queryKey: [...(queryPrefix ?? ["accounts"]), "balance", accountId], queryFn: ({ signal }) => customer ? getCustomerBalance(accountId, signal) : getBalance(accountId, signal) });
  return <section className="panel"><div className="panel-heading"><h2>Balance actual</h2><button className="button secondary" disabled={query.isFetching} onClick={() => void query.refetch()}>Actualizar balance</button></div>{query.isPending && <p role="status" className="loading">Cargando balance…</p>}{query.isError && <ErrorNotice error={query.error} />}{query.data && !query.isError && <dl className="details-grid"><div><dt>Saldo contabilizado</dt><dd><Money amount={query.data.booked_balance} currency={currency} /></dd></div><div><dt>Saldo disponible</dt><dd><Money amount={query.data.available_balance} currency={currency} /></dd></div><div><dt>Actualización · hora local</dt><dd><Timestamp value={query.data.updated_at} /></dd></div></dl>}</section>;
}
export function Movements({ scope, id, accountBase = "/accounts", transactionBase = "/transactions", queryPrefix, allowedAccountIds, customer = false }: { scope: "accounts" | "transactions"; id: string; accountBase?: string; transactionBase?: string; queryPrefix?: readonly (string | null)[]; allowedAccountIds?: string[]; customer?: boolean }) {
  const [offset, setOffset] = useState(0); const [limit, setLimit] = useState(20);
  const query = useQuery({ queryKey: [...(queryPrefix ?? [scope]), "movements", id, limit, offset], queryFn: ({ signal }) => customer ? getCustomerMovements(id, limit, offset, signal) : listMovements(scope, id, limit, offset, signal) });
  return <section className="panel"><div className="panel-heading"><h2>Movimientos</h2><button className="button secondary" disabled={query.isFetching} onClick={() => void query.refetch()}>Actualizar movimientos</button></div>
    {query.isPending && <p role="status" className="loading">Cargando movimientos…</p>}{query.isError && <ErrorNotice error={query.error} />}
    {query.data && !query.isError && <>{query.data.items.length ? <MovementTable items={query.data.items.filter(item => !allowedAccountIds || allowedAccountIds.includes(item.account_id))} accountBase={accountBase} transactionBase={transactionBase} /> : <p className="empty-state">No hay movimientos registrados.</p>}<Pagination pagination={query.data.pagination} length={query.data.items.length} busy={query.isFetching} onOffset={setOffset} onLimit={value => { setLimit(value); setOffset(0); }} label="Movimientos" /></>}
  </section>;
}

export function MovementTable({ items, accountBase = "/accounts", transactionBase = "/transactions" }: { items: Movement[]; accountBase?: string; transactionBase?: string }) {
  return <div className="table-scroll"><table><thead><tr><th>Cuenta</th><th>Dirección</th><th>Importe</th><th>Balance posterior</th><th>Registro · hora local</th><th>Transacción</th></tr></thead><tbody>{items.map(item => <tr key={item.id}><td><Link className="mono" to={`${accountBase}/${item.account_id}`}>{item.account_id}</Link></td><td><span className={`status direction-${item.direction.toLowerCase()}`}>{item.direction === "CREDIT" ? "CREDIT · Entrada" : "DEBIT · Salida"}</span></td><td><Money amount={item.amount} /></td><td><Money amount={item.balance_after} /></td><td><Timestamp value={item.booked_at} /></td><td><Link className="mono" to={`${transactionBase}/${item.transaction_id}`}>{item.transaction_id}</Link></td></tr>)}</tbody></table></div>;
}
