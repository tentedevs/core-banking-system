import { useState } from "react";
import { Link, useLocation, useParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { listCustomerTransactions } from "../api/customer";
import { getTransaction, listTransactions } from "../api/transactions";
import { ErrorNotice, Money, Movements, Pagination, Timestamp, TransactionState } from "../components/Banking";

export function TransactionsPage({ customer = false }: { customer?: boolean }) {
  const [type, setType] = useState(""); const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0); const [limit, setLimit] = useState(20);
  const query = useQuery({ queryKey: [customer ? "banking" : "transactions", "list", type, status, limit, offset], queryFn: ({ signal }) => customer ? listCustomerTransactions(type, status, limit, offset, signal) : listTransactions(type, status, limit, offset, signal) });
  return <><div className="page-heading"><div><p className="eyebrow">{customer ? "MI BANCA" : "ADMINISTRACIÓN BANCARIA"}</p><h1>Transacciones</h1></div>{!customer && <OperationLinks />}</div><section className="panel"><div className="panel-heading"><h2>Historial de operaciones</h2><button className="button secondary" disabled={query.isFetching} onClick={() => void query.refetch()}>Actualizar</button></div>
    <div className="tools transaction-filters"><label>Tipo <select value={type} onChange={e => { setType(e.target.value); setOffset(0); }}><option value="">Todos</option><option value="DEPOSIT">Depósito</option><option value="WITHDRAWAL">Retirada</option><option value="TRANSFER">Transferencia</option></select></label><label>Estado <select value={status} onChange={e => { setStatus(e.target.value); setOffset(0); }}><option value="">Todos</option><option value="PENDING">Pendiente</option><option value="POSTED">Registrada</option><option value="REJECTED">Rechazada</option><option value="REVERSED">Revertida</option></select></label></div>
    {query.isPending && <p role="status" className="loading">Cargando transacciones…</p>}{query.isError && <ErrorNotice error={query.error} />}
    {query.data && !query.isError && <>{query.data.items.length ? <div className="table-scroll"><table><thead><tr><th>Referencia</th><th>Tipo</th><th>Importe</th><th>Moneda</th><th>Estado</th><th>Fecha efectiva</th><th>Registro</th><th>Descripción</th></tr></thead><tbody>{query.data.items.map(item => <tr key={item.id}><td><Link className="mono" aria-label={`Abrir transacción ${item.id}`} to={`${customer ? "/me/transactions" : "/transactions"}/${item.id}`}>{item.id}</Link></td><td>{item.transaction_type}</td><td><Money amount={item.amount} /></td><td>{item.currency}</td><td><TransactionState status={item.status} /></td><td><Timestamp value={item.effective_at} /></td><td><Timestamp value={item.posted_at} /></td><td>{item.description ?? "—"}</td></tr>)}</tbody></table></div> : <p className="empty-state">No hay transacciones en esta página.</p>}<Pagination pagination={query.data.pagination} length={query.data.items.length} busy={query.isFetching} onOffset={setOffset} onLimit={value => { setLimit(value); setOffset(0); }} label="Transacciones" /></>}
  </section></>;
}
export function OperationLinks({ accountId }: { accountId?: string }) {
  const params = accountId ? `?account=${encodeURIComponent(accountId)}` : "";
  return <div className="operation-links"><Link className="button primary" to={`/transactions/new/deposit${params}`}>Depósito</Link><Link className="button secondary" to={`/transactions/new/withdrawal${params}`}>Retirada</Link><Link className="button secondary" to={`/transactions/new/transfer${params}`}>Transferencia</Link></div>;
}
export function TransactionDetail() {
  const { transactionId = "" } = useParams(); const location = useLocation();
  const query = useQuery({ queryKey: ["transactions", "detail", transactionId], queryFn: ({ signal }) => getTransaction(transactionId, signal) });
  const item = query.data;
  return <><Link className="back-link" to="/transactions">← Volver a transacciones</Link><div className="page-heading"><h1>Detalle de transacción</h1><button className="button secondary" disabled={query.isFetching} onClick={() => void query.refetch()}>Actualizar</button></div>{location.state?.posted && <p role="status" className="notice success">Operación registrada correctamente.</p>}{query.isPending && <p role="status" className="loading">Cargando transacción…</p>}{query.isError && <ErrorNotice error={query.error} />}{item && !query.isError && <><section className="panel"><div className="panel-heading"><h2 className="mono">{item.id}</h2><TransactionState status={item.status} /></div><dl className="details-grid"><div><dt>Tipo</dt><dd>{item.transaction_type}</dd></div><div><dt>Importe</dt><dd><Money amount={item.amount} currency={item.currency} /></dd></div><div><dt>Referencia de petición</dt><dd className="mono">{item.idempotency_key ?? "—"}</dd></div><div><dt>Descripción</dt><dd>{item.description ?? "—"}</dd></div><div><dt>Fecha efectiva · hora local</dt><dd><Timestamp value={item.effective_at} /></dd></div><div><dt>Registro · hora local</dt><dd><Timestamp value={item.posted_at} /></dd></div></dl></section><Movements key={transactionId} scope="transactions" id={transactionId} /></>}</>;
}
