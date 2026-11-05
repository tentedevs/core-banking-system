import { SessionControls } from "../../auth/AuthProvider";
import { TransactionsPage } from "../../pages/Transactions";
import { useState } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, NavLink, Route, Routes, useLocation, useParams, useSearchParams } from "react-router";
import { getCustomerAccount, getCustomerBalance as getBalance, getCustomerTransaction, getCustomerMovements } from "../../api/customer";
import { AccountBalance, ErrorNotice, Money, MovementTable, Movements, Pagination, Timestamp, TransactionState } from "../../components/Banking";
import { MonetaryOperation } from "../../pages/MonetaryOperation";
import { useCustomerAccounts, useCustomerIdentity } from "./context";
import { sumMoney } from "./money";

export function CustomerBanking() {
  const { customerId } = useCustomerIdentity();
  return <div className="banking-shell"><header className="banking-header"><Link className="banking-brand" to="/me">CBS <span>Mi banca</span></Link><nav aria-label="Navegación de cliente"><NavLink to="/me" end>Mis cuentas</NavLink><NavLink to="/me/transactions">Transacciones</NavLink></nav><SessionControls /></header><main className="banking-main" key={customerId}><Routes><Route index element={<CustomerDashboard />} /><Route path="accounts/:accountId" element={<CustomerAccount />} /><Route path="transactions" element={<TransactionsPage customer />} /><Route path="transactions/:transactionId" element={<CustomerTransaction />} /><Route path="transfers" element={<CustomerOperation />} /><Route path="*" element={<section className="panel"><h1>Página no encontrada</h1><Link to="/me">Volver a mi banca</Link></section>} /></Routes></main></div>;
}

function CustomerActions({ accountId }: { accountId?: string }) {
  const query = accountId ? `?account=${encodeURIComponent(accountId)}` : "";
  return <div className="operation-links"><Link className="button primary" to={`/me/transfers${query}`}>Transferir</Link></div>;
}
function CustomerDashboard() {
  const { customerId } = useCustomerIdentity(); const accounts = useCustomerAccounts(); const client = useQueryClient();
  const rows = accounts.data ?? [];
  const balances = useQueries({ queries: rows.map(account => ({ queryKey: ["banking", customerId, "balance", account.id], queryFn: ({ signal }: { signal: AbortSignal }) => getBalance(account.id, signal) })) });
  const recent = useQueries({ queries: rows.map(account => ({ queryKey: ["banking", customerId, "recent", account.id], queryFn: ({ signal }: { signal: AbortSignal }) => getCustomerMovements(account.id, 5, 0, signal) })) });
  const grouped = [...new Set(rows.map(account => account.currency))];
  const relevant = new Set(rows.map(account => account.id));
  const movements = [...new Map(recent.flatMap(query => query.isError ? [] : query.data?.items ?? []).filter(item => relevant.has(item.account_id)).map(item => [item.id, item])).values()].sort((a,b) => Date.parse(b.booked_at) - Date.parse(a.booked_at) || a.id.localeCompare(b.id)).slice(0,10);
  return <><div className="page-heading"><div><p className="eyebrow">MI BANCA</p><h1>Mis cuentas</h1><p className="mono customer-reference">{customerId}</p></div><button className="button secondary" onClick={() => void client.invalidateQueries({queryKey:["banking",customerId]})}>Actualizar mi banca</button></div>{accounts.isPending && <p role="status">Cargando cuentas del cliente…</p>}{accounts.isError && <ErrorNotice error={accounts.error} />}{accounts.data && !accounts.isError && <>{!rows.length ? <section className="panel empty-state"><h2>No tienes cuentas asociadas</h2><p>El backend no devuelve cuentas para este cliente.</p></section> : <><section className="customer-overview" aria-label="Resumen del cliente"><div className="balance-card"><span>Cuentas activas</span><strong>{rows.filter(account => account.status === "ACTIVE").length}</strong></div>{grouped.map(currency => {
    const indices = rows.flatMap((account,index) => account.currency === currency ? [index] : []);
    const complete = indices.every(index => balances[index]?.data && !balances[index]?.isError);
    const failed = indices.some(index => balances[index]?.isError);
    return <div className="balance-card" key={currency}><h2>{currency}</h2>{complete ? <><span>Total contabilizado</span><strong><Money amount={sumMoney(indices.map(index => balances[index]!.data!.booked_balance))} currency={currency} /></strong><span>Total disponible</span><strong><Money amount={sumMoney(indices.map(index => balances[index]!.data!.available_balance))} currency={currency} /></strong></> : <p role={failed ? "alert" : "status"}>{failed ? "Totales no disponibles: falta algún balance." : "Cargando saldos…"}</p>}</div>;
  })}</section><CustomerActions /><section className="customer-accounts" aria-label="Cuentas del cliente">{rows.map((account,index) => <article className="panel customer-account-card" key={account.id}><div><h2><Link to={`/me/accounts/${account.id}`}>{account.account_number}</Link></h2><span className={`status status-${account.status.toLowerCase()}`}>{account.status}</span></div><p>Cuenta de ahorro · SAVINGS_ACCOUNT · {account.currency}</p><span>Saldo disponible</span>{balances[index]?.isError ? <ErrorNotice error={balances[index]!.error} /> : balances[index]?.data ? <strong><Money amount={balances[index]!.data!.available_balance} currency={account.currency} /></strong> : <p role="status">Cargando saldo…</p>}<Link to={`/me/accounts/${account.id}`}>Ver cuenta y movimientos →</Link></article>)}</section><section className="panel"><div className="panel-heading"><h2>Movimientos recientes</h2></div><p className="movement-sample">Muestra de hasta 5 movimientos por cuenta, con los 10 más recientes de las cuentas cargadas. No es una paginación global.</p>{recent.some(query => query.isError) && <p role="alert" className="notice error">No se han podido cargar todos los movimientos recientes.</p>}{recent.some(query => query.isPending) && <p role="status">Cargando movimientos recientes…</p>}{movements.length ? <MovementTable items={movements} accountBase="/me/accounts" transactionBase="/me/transactions" /> : recent.every(query => !query.isPending && !query.isError) && <p className="empty-state">No hay movimientos recientes.</p>}</section></>}</>}</>;
}
function CustomerAccount() {
  const { customerId } = useCustomerIdentity(); const { accountId = "" } = useParams();
  const query = useQuery({ queryKey: ["banking", customerId, "account", accountId], queryFn: ({signal}) => getCustomerAccount(accountId, signal) });
  if (query.isPending) return <p role="status">Cargando cuenta…</p>;
  if (query.isError) return <ErrorNotice error={query.error} />;
  const account = query.data;
  return <><Link className="back-link" to="/me">← Volver a mis cuentas</Link><div className="page-heading"><div><p className="eyebrow">MI CUENTA</p><h1>{account.account_number}</h1><p>Cuenta de ahorro · {account.currency}</p></div><span className={`status status-${account.status.toLowerCase()}`}>{account.status}</span></div><AccountBalance customer accountId={account.id} currency={account.currency} queryPrefix={["banking",customerId]} />{account.status === "ACTIVE" && <CustomerActions accountId={account.id} />}<Movements customer key={account.id} scope="accounts" id={account.id} accountBase="/me/accounts" transactionBase="/me/transactions" queryPrefix={["banking",customerId]} /></>;
}
function ContextMismatch() { return <section className="panel empty-state"><h1>Operación no disponible</h1><p>La cuenta o transacción no está disponible para tu usuario.</p><Link to="/me">Volver a mis cuentas</Link></section>; }
function CustomerTransaction() {
  const {customerId} = useCustomerIdentity(); const {transactionId = ""} = useParams(); const location = useLocation();
  const [limit, setLimit] = useState(20); const [offset, setOffset] = useState(0);
  const query = useQuery({queryKey:["banking",customerId,"transaction",transactionId,limit,offset],queryFn:({signal})=>getCustomerTransaction(transactionId,limit,offset,signal)});
  const item = query.data;
  return <><Link className="back-link" to="/me/transactions">← Volver a transacciones</Link><h1>Detalle de operación</h1>{location.state?.posted && <p className="notice success" role="status">Operación registrada correctamente.</p>}{query.isPending && <p role="status">Cargando operación…</p>}{query.isError && <ErrorNotice error={query.error} />}{item && !query.isError && <><section className="panel"><div className="panel-heading"><h2 className="mono">{item.id}</h2><TransactionState status={item.status} /></div><dl className="details-grid"><div><dt>Tipo</dt><dd>{item.transaction_type}</dd></div><div><dt>Importe</dt><dd><Money amount={item.amount} currency={item.currency} /></dd></div><div><dt>Descripción</dt><dd>{item.description ?? "—"}</dd></div><div><dt>Fecha efectiva</dt><dd><Timestamp value={item.effective_at} /></dd></div><div><dt>Registro</dt><dd><Timestamp value={item.posted_at} /></dd></div></dl></section><section className="panel"><h2>Movimientos de tus cuentas</h2>{item.movements.items.length ? <MovementTable items={item.movements.items} accountBase="/me/accounts" transactionBase="/me/transactions" /> : <p className="empty-state">No hay movimientos.</p>}<Pagination pagination={item.movements.pagination} length={item.movements.items.length} busy={query.isFetching} onOffset={setOffset} onLimit={value=>{setLimit(value);setOffset(0);}} label="Movimientos" /></section></>}</>;
}
function CustomerOperation() {
  const {customerId} = useCustomerIdentity(); const accounts = useCustomerAccounts(); const [params] = useSearchParams();
  if (accounts.isError) return <ErrorNotice error={accounts.error} />;
  if (!accounts.data) return <p role="status">Cargando cuentas para operar…</p>;
  if (params.get("account") && !accounts.data.some(account=>account.id === params.get("account"))) return <ContextMismatch />;
  return <MonetaryOperation key={customerId} operation="transfer" customer={{id:customerId!,accounts:accounts.data}} />;
}
