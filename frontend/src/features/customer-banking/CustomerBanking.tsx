import { useInfiniteQuery, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, NavLink, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import { listAccounts } from "../../api/accounts";
import { getBalance, getTransaction, listMovements } from "../../api/transactions";
import type { Movement, Operation } from "../../api/transactions";
import { AccountBalance, ErrorNotice, Money, MovementTable, Movements, Timestamp, TransactionState } from "../../components/Banking";
import { MonetaryOperation } from "../../pages/MonetaryOperation";
import { useCustomerAccounts, useDemoCustomer } from "./context";
import { sumMoney } from "./money";

export function CustomerBanking() {
  const { customerId, selectCustomer } = useDemoCustomer(); const navigate = useNavigate();
  const directory = useInfiniteQuery({ queryKey: ["demo-customer-directory"], initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => listAccounts("", 100, pageParam, signal),
    getNextPageParam: page => page.pagination.offset + page.items.length < page.pagination.total_items && page.items.length ? page.pagination.offset + page.items.length : undefined });
  const customers = [...new Set(directory.data?.pages.flatMap(page => page.items.map(account => account.customer_id)) ?? [])];
  if (customerId && !customers.includes(customerId)) customers.push(customerId);
  return <div className="banking-shell"><header className="banking-header"><Link className="banking-brand" to="/banking">CBS <span>Mi banca</span></Link><nav aria-label="Navegación de cliente"><NavLink to="/banking" end>Mis cuentas</NavLink><Link to="/accounts">Administración →</Link></nav><span className="demo-badge">DEMO · Local</span></header><section className="demo-context"><div><label htmlFor="demo-customer">Cliente DEMO</label><select id="demo-customer" value={customerId ?? ""} onChange={e => { selectCustomer(e.target.value || null); navigate("/banking"); }}><option value="">Selecciona un cliente</option>{customers.map(id => <option key={id} value={id}>{id}</option>)}</select></div><p>Selector de demostración, sin autenticación ni autorización.</p>{directory.isPending && <p role="status">Cargando referencias de clientes…</p>}{directory.isError && <><ErrorNotice error={directory.error} /><button className="button secondary" onClick={() => void directory.refetch()}>Reintentar clientes</button></>}{directory.hasNextPage && <button className="button secondary" disabled={directory.isFetchingNextPage} onClick={() => void directory.fetchNextPage()}>Cargar más referencias</button>}<button className="button secondary" disabled={directory.isFetching} onClick={() => void directory.refetch()}>Actualizar referencias</button>{directory.data && !customers.length && <p>No hay referencias de clientes en las cuentas disponibles.</p>}</section><main className="banking-main" key={customerId ?? "none"}>{!customerId ? <section className="panel banking-welcome"><h1>Tu banca en modo DEMO</h1><p>Selecciona una referencia de cliente real para consultar sus cuentas.</p><p className="muted">Las referencias proceden de Accounts. Los clientes sin cuentas no pueden descubrirse mediante esta API.</p></section> : <Routes><Route index element={<CustomerDashboard />} /><Route path="accounts/:accountId" element={<CustomerAccount />} /><Route path="transactions/:transactionId" element={<CustomerTransaction />} /><Route path="operations/:operation" element={<CustomerOperation />} /><Route path="*" element={<section className="panel"><h1>Página no encontrada</h1><Link to="/banking">Volver a mi banca</Link></section>} /></Routes>}</main></div>;
}
function CustomerActions({ accountId }: { accountId?: string }) {
  const query = accountId ? `?account=${encodeURIComponent(accountId)}` : "";
  return <div className="operation-links"><Link className="button primary" to={`/banking/operations/transfer${query}`}>Transferir</Link><Link className="button secondary" to={`/banking/operations/deposit${query}`}>Depósito simulado</Link><Link className="button secondary" to={`/banking/operations/withdrawal${query}`}>Retirada simulada</Link></div>;
}
function CustomerDashboard() {
  const { customerId } = useDemoCustomer(); const accounts = useCustomerAccounts(); const client = useQueryClient();
  const rows = accounts.data ?? [];
  const balances = useQueries({ queries: rows.map(account => ({ queryKey: ["banking", customerId, "balance", account.id], queryFn: ({ signal }: { signal: AbortSignal }) => getBalance(account.id, signal) })) });
  const recent = useQueries({ queries: rows.map(account => ({ queryKey: ["banking", customerId, "recent", account.id], queryFn: ({ signal }: { signal: AbortSignal }) => listMovements("accounts", account.id, 5, 0, signal) })) });
  const grouped = [...new Set(rows.map(account => account.currency))];
  const relevant = new Set(rows.map(account => account.id));
  const movements = [...new Map(recent.flatMap(query => query.isError ? [] : query.data?.items ?? []).filter(item => relevant.has(item.account_id)).map(item => [item.id, item])).values()].sort((a,b) => Date.parse(b.booked_at) - Date.parse(a.booked_at) || a.id.localeCompare(b.id)).slice(0,10);
  return <><div className="page-heading"><div><p className="eyebrow">MI BANCA · DEMO</p><h1>Mis cuentas</h1><p className="mono customer-reference">{customerId}</p></div><button className="button secondary" onClick={() => void client.invalidateQueries({queryKey:["banking",customerId]})}>Actualizar mi banca</button></div>{accounts.isPending && <p role="status">Cargando cuentas del cliente…</p>}{accounts.isError && <ErrorNotice error={accounts.error} />}{accounts.data && !accounts.isError && <>{!rows.length ? <section className="panel empty-state"><h2>No tienes cuentas asociadas</h2><p>El backend no devuelve cuentas para este cliente DEMO.</p></section> : <><section className="customer-overview" aria-label="Resumen del cliente"><div className="balance-card"><span>Cuentas activas</span><strong>{rows.filter(account => account.status === "ACTIVE").length}</strong></div>{grouped.map(currency => {
    const indices = rows.flatMap((account,index) => account.currency === currency ? [index] : []);
    const complete = indices.every(index => balances[index]?.data && !balances[index]?.isError);
    const failed = indices.some(index => balances[index]?.isError);
    return <div className="balance-card" key={currency}><h2>{currency}</h2>{complete ? <><span>Total contabilizado</span><strong><Money amount={sumMoney(indices.map(index => balances[index]!.data!.booked_balance))} currency={currency} /></strong><span>Total disponible</span><strong><Money amount={sumMoney(indices.map(index => balances[index]!.data!.available_balance))} currency={currency} /></strong></> : <p role={failed ? "alert" : "status"}>{failed ? "Totales no disponibles: falta algún balance." : "Cargando saldos…"}</p>}</div>;
  })}</section><CustomerActions /><section className="customer-accounts" aria-label="Cuentas del cliente">{rows.map((account,index) => <article className="panel customer-account-card" key={account.id}><div><h2><Link to={`/banking/accounts/${account.id}`}>{account.account_number}</Link></h2><span className={`status status-${account.status.toLowerCase()}`}>{account.status}</span></div><p>Cuenta de ahorro · SAVINGS_ACCOUNT · {account.currency}</p><span>Saldo disponible</span>{balances[index]?.isError ? <ErrorNotice error={balances[index]!.error} /> : balances[index]?.data ? <strong><Money amount={balances[index]!.data!.available_balance} currency={account.currency} /></strong> : <p role="status">Cargando saldo…</p>}<Link to={`/banking/accounts/${account.id}`}>Ver cuenta y movimientos →</Link></article>)}</section><section className="panel"><div className="panel-heading"><h2>Movimientos recientes</h2></div><p className="movement-sample">Muestra de hasta 5 movimientos por cuenta, con los 10 más recientes de las cuentas cargadas. No es una paginación global.</p>{recent.some(query => query.isError) && <p role="alert" className="notice error">No se han podido cargar todos los movimientos recientes.</p>}{recent.some(query => query.isPending) && <p role="status">Cargando movimientos recientes…</p>}{movements.length ? <MovementTable items={movements} accountBase="/banking/accounts" transactionBase="/banking/transactions" /> : recent.every(query => !query.isPending && !query.isError) && <p className="empty-state">No hay movimientos recientes.</p>}</section></>}</>}</>;
}
function CustomerAccount() {
  const { customerId } = useDemoCustomer(); const { accountId = "" } = useParams(); const query = useCustomerAccounts();
  const account = query.data?.find(row => row.id === accountId);
  if (query.isPending) return <p role="status">Comprobando contexto de cuenta…</p>;
  if (query.isError) return <ErrorNotice error={query.error} />;
  if (!account) return <ContextMismatch />;
  return <><Link className="back-link" to="/banking">← Volver a mis cuentas</Link><div className="page-heading"><div><p className="eyebrow">MI CUENTA · DEMO</p><h1>{account.account_number}</h1><p>Cuenta de ahorro · SAVINGS_ACCOUNT · {account.currency}</p></div><span className={`status status-${account.status.toLowerCase()}`}>{account.status}</span></div><AccountBalance accountId={account.id} currency={account.currency} queryPrefix={["banking",customerId]} />{account.status === "ACTIVE" && <CustomerActions accountId={account.id} />}<p className="movement-sample">Los movimientos más recientes aparecen primero. Navega por el historial completo.</p><Movements key={account.id} scope="accounts" id={account.id} accountBase="/banking/accounts" transactionBase="/banking/transactions" queryPrefix={["banking",customerId]} allowedAccountIds={[account.id]} /></>;
}
function ContextMismatch() { return <section className="panel empty-state"><h1>No disponible en este contexto DEMO</h1><p>La cuenta o transacción no está vinculada a las cuentas del cliente seleccionado.</p><Link to="/banking">Volver a mis cuentas</Link></section>; }
function CustomerTransaction() {
  const { customerId } = useDemoCustomer(); const accounts = useCustomerAccounts(); const { transactionId = "" } = useParams();
  const owned = useQuery({ queryKey:["banking",customerId,"transaction-movements",transactionId], enabled:!!accounts.data && !accounts.isError,
    queryFn: async ({signal}) => {
      const ids = new Set(accounts.data!.map(account => account.id)); const items = new Map<string,Movement>();
      for (let offset=0;;offset+=100) {
        const page = await listMovements("transactions",transactionId,100,offset,signal);
        page.items.filter(item => ids.has(item.account_id)).forEach(item => items.set(item.id,item));
        if (offset + page.items.length >= page.pagination.total_items) return [...items.values()];
        if (!page.items.length) throw new Error("El historial cambió durante la consulta.");
      }
    } });
  if (accounts.isError) return <ErrorNotice error={accounts.error} />;
  if (owned.isError) return <ErrorNotice error={owned.error} />;
  if (!owned.data) return <p role="status">Cargando movimientos del cliente…</p>;
  if (!owned.data.length) return <ContextMismatch />;
  return <CustomerTransactionSnapshot transactionId={transactionId} movements={owned.data} />;
}
function CustomerTransactionSnapshot({transactionId,movements}:{transactionId:string;movements:Movement[]}) {
  const {customerId}=useDemoCustomer(); const location=useLocation();
  const query=useQuery({queryKey:["banking",customerId,"transaction",transactionId],queryFn:({signal})=>getTransaction(transactionId,signal)});
  const item=query.data;
  return <><Link className="back-link" to="/banking">← Volver a mi banca</Link><h1>Detalle de operación</h1>{location.state?.posted && <p className="notice success" role="status">Operación registrada correctamente.</p>}{query.isPending && <p role="status">Cargando operación…</p>}{query.isError && <ErrorNotice error={query.error} />}{item && !query.isError && <><section className="panel"><div className="panel-heading"><h2 className="mono">{item.id}</h2><TransactionState status={item.status} /></div><dl className="details-grid"><div><dt>Tipo</dt><dd>{item.transaction_type}</dd></div><div><dt>Importe</dt><dd><Money amount={item.amount} currency={item.currency} /></dd></div><div><dt>Descripción</dt><dd>{item.description ?? "—"}</dd></div><div><dt>Fecha efectiva</dt><dd><Timestamp value={item.effective_at} /></dd></div><div><dt>Registro</dt><dd><Timestamp value={item.posted_at} /></dd></div></dl></section><section className="panel"><div className="panel-heading"><h2>Movimientos de tus cuentas</h2></div><MovementTable items={movements} accountBase="/banking/accounts" transactionBase="/banking/transactions" /></section></>}</>;
}
function CustomerOperation() {
  const {customerId}=useDemoCustomer(); const accounts=useCustomerAccounts(); const {operation=""}=useParams(); const [params]=useSearchParams();
  if (accounts.isError) return <ErrorNotice error={accounts.error} />;
  if (!accounts.data) return <p role="status">Cargando cuentas para operar…</p>;
  if (!["deposit","withdrawal","transfer"].includes(operation)) return <ContextMismatch />;
  if (params.get("account") && !accounts.data.some(account => account.id === params.get("account"))) return <ContextMismatch />;
  return <MonetaryOperation key={`${customerId}:${operation}`} operation={operation as Operation} customer={{id:customerId!,accounts:accounts.data}} />;
}
