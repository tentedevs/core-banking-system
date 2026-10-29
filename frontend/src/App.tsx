import { useState } from "react";
import type { FormEvent } from "react";
import { Link, NavLink, Navigate, Route, Routes, useNavigate, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, changeAccountState, createAccount, errorMessage, getAccount, getAccountByNumber, listAccounts } from "./api/accounts";
import type { AccountStatus } from "./api/accounts";

const labels: Record<AccountStatus, string> = { ACTIVE: "Activa", BLOCKED: "Bloqueada", CLOSED: "Cerrada" };
const uuidPattern = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
function Status({ status }: { status: AccountStatus }) { return <span className={`status status-${status.toLowerCase()}`}><span aria-hidden="true">●</span> {labels[status]}</span>; }
function ErrorNotice({ error }: { error: unknown }) { return <p role="alert" className="notice error">{errorMessage(error)}</p>; }
function Loading() { return <p role="status" className="loading">Cargando cuentas…</p>; }
function date(value: string) { return new Intl.DateTimeFormat("es", { dateStyle: "medium", timeZone: "UTC" }).format(new Date(`${value}T00:00:00Z`)); }

export function App() {
  return <div className="shell">
    <aside className="sidebar">
      <Link to="/accounts" className="brand"><span className="brand-icon">C</span><span>CBS<small>CORE BANKING SYSTEM</small></span></Link>
      <p className="nav-label">ESPACIO DE TRABAJO</p>
      <nav aria-label="Navegación principal"><NavLink to="/accounts">▤ <span>Cuentas</span><span aria-hidden="true">↗</span></NavLink></nav>
      <div className="sidebar-footer"><span>Core Banking</span><small>Gestión de cuentas de ahorro</small></div>
    </aside>
    <div className="workspace"><header className="topbar"><span>Operaciones <span className="separator">/</span> Cuentas</span><span className="workspace-tag">CBS · Entorno local</span></header>
      <main><Routes>
        <Route path="/" element={<Navigate to="/accounts" replace />} />
        <Route path="/accounts" element={<AccountsPage />} />
        <Route path="/accounts/new" element={<CreateAccountPage />} />
        <Route path="/accounts/:accountId" element={<AccountDetail />} />
        <Route path="*" element={<section className="panel"><h1>Página no encontrada</h1><Link to="/accounts">Volver a cuentas</Link></section>} />
      </Routes></main>
    </div>
  </div>;
}

function AccountsPage() {
  const [customer, setCustomer] = useState("");
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(20);
  const navigate = useNavigate();
  const query = useQuery({ queryKey: ["accounts", "list", customer, limit, offset], queryFn: ({ signal }) => listAccounts(customer, limit, offset, signal) });
  const lookup = useMutation({ mutationFn: async ({ mode, value }: { mode: string; value: string }) => mode === "number" ? getAccountByNumber(value) : getAccount(value), onSuccess: (account) => navigate(`/accounts/${account.id}`) });
  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const values = new FormData(event.currentTarget);
    lookup.mutate({ mode: String(values.get("mode")), value: String(values.get("value")) });
  }
  function filter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const values = new FormData(event.currentTarget);
    setCustomer(String(values.get("customer")).trim()); setOffset(0);
  }
  const data = query.data;
  return <>
    <div className="page-heading"><div><p className="eyebrow">GESTIÓN DE CUENTAS</p><h1>Cuentas</h1><p>Consulta y administra las cuentas de ahorro de tus clientes.</p></div><Link className="button primary" to="/accounts/new"><span aria-hidden="true">＋</span> Nueva cuenta</Link></div>
    <section className="summary" aria-label="Resumen de cuentas"><div><span>CUENTAS {customer ? "DEL CLIENTE" : "REGISTRADAS"}</span><strong>{data ? data.pagination.total_items.toLocaleString("es") : "—"}</strong></div><div className="product-label"><span>PRODUCTO DISPONIBLE</span><strong>Cuenta de ahorro</strong><small>SAVINGS_ACCOUNT</small></div><div className="summary-note">Un espacio para consultar cada cuenta y gestionar su estado.</div></section>
    <section className="panel"><div className="panel-heading"><h2>Directorio de cuentas</h2><button className="button secondary" disabled={query.isFetching} onClick={() => void query.refetch()}>Actualizar</button></div>
      <div className="tools"><form onSubmit={search} className="search-form"><label className="sr-only" htmlFor="lookup-mode">Buscar por</label><select id="lookup-mode" name="mode"><option value="number">Número de cuenta</option><option value="id">ID de cuenta</option></select><label className="sr-only" htmlFor="lookup">Referencia de cuenta</label><input id="lookup" name="value" placeholder="Introduce la referencia exacta" required /><button className="button secondary" disabled={lookup.isPending}>{lookup.isPending ? "Buscando…" : "Buscar"}</button></form>
      <form onSubmit={filter} className="filter-form"><label htmlFor="customer-filter">Cliente</label><input id="customer-filter" name="customer" pattern={uuidPattern} placeholder="Filtrar por UUID del cliente" /><button className="button secondary">Filtrar</button></form></div>
      {lookup.isError && <ErrorNotice error={lookup.error} />}
      {query.isPending && <Loading />}
      {query.isError && <ErrorNotice error={query.error} />}
      {data && !query.isError && <>
        {data.items.length ? <div className="table-scroll"><table><thead><tr><th>Cuenta</th><th>Cliente</th><th>Producto</th><th>Moneda</th><th>Estado</th><th>Apertura</th><th><span className="sr-only">Abrir</span></th></tr></thead><tbody>{data.items.map((account) => <tr key={account.id}><td><Link className="account-link" to={`/accounts/${account.id}`}>{account.account_number}</Link><small className="mono muted">{account.id}</small></td><td className="mono customer-ref" title={account.customer_id}>{account.customer_id}</td><td>Cuenta de ahorro</td><td><span className="currency">{account.currency}</span></td><td><Status status={account.status} /></td><td>{date(account.opened_at)}</td><td><Link aria-label={`Abrir cuenta ${account.account_number}`} className="open-link" to={`/accounts/${account.id}`}>↗</Link></td></tr>)}</tbody></table></div> : <div className="empty-state"><span aria-hidden="true">▤</span><h3>No hay cuentas en esta página</h3><p>{customer ? "No se han encontrado cuentas para este cliente." : "Crea una cuenta de ahorro para empezar."}</p></div>}
        <div className="pagination"><label>Por página <select aria-label="Cuentas por página" value={limit} onChange={(event) => { setLimit(Number(event.target.value)); setOffset(0); }}><option value={20}>20</option><option value={50}>50</option><option value={100}>100</option></select></label><span>{data.items.length ? `${offset + 1}–${offset + data.items.length}` : "0"} de {data.pagination.total_items}</span><div><button className="button secondary" disabled={offset === 0 || query.isFetching} onClick={() => setOffset(Math.max(0, offset - limit))}>Anterior</button><button className="button secondary" disabled={offset + limit >= data.pagination.total_items || query.isFetching} onClick={() => setOffset(offset + limit)}>Siguiente</button></div></div>
      </>}
    </section>
  </>;
}

function CreateAccountPage() {
  const navigate = useNavigate(); const client = useQueryClient();
  const mutation = useMutation({ mutationFn: createAccount, onSuccess: async (account) => { await client.invalidateQueries({ queryKey: ["accounts", "list"] }); navigate(`/accounts/${account.id}`); } });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const values = new FormData(event.currentTarget);
    mutation.mutate({ customer_id: String(values.get("customer_id")), currency: String(values.get("currency")) });
  }
  return <><Link className="back-link" to="/accounts">← Volver a cuentas</Link><div className="page-heading"><div><p className="eyebrow">APERTURA</p><h1>Nueva cuenta</h1><p>Abre una cuenta de ahorro para un cliente.</p></div></div><section className="panel form-panel"><h2>Datos de la cuenta</h2><p className="muted">El número de cuenta y el estado inicial se generan automáticamente.</p><form onSubmit={submit} className="create-form"><label htmlFor="customer-id">UUID del cliente</label><input id="customer-id" name="customer_id" required pattern={uuidPattern} placeholder="00000000-0000-0000-0000-000000000000" /><small>Se valida el formato del UUID; la existencia del cliente todavía no se comprueba.</small><label htmlFor="currency">Moneda</label><input id="currency" name="currency" required pattern="[A-Z]{3}" minLength={3} maxLength={3} defaultValue="CZK" /><small>Código de tres letras mayúsculas, por ejemplo CZK, EUR o USD.</small><div className="read-only-field"><span>Producto</span><strong>Cuenta de ahorro · SAVINGS_ACCOUNT</strong></div>{mutation.isError && <ErrorNotice error={mutation.error} />}<div className="form-actions"><Link className="button secondary" to="/accounts">Cancelar</Link><button className="button primary" disabled={mutation.isPending}>{mutation.isPending ? "Creando…" : "Crear cuenta"}</button></div></form></section></>;
}

function AccountDetail() {
  const { accountId = "" } = useParams(); const client = useQueryClient();
  const query = useQuery({ queryKey: ["accounts", "detail", accountId], queryFn: ({ signal }) => getAccount(accountId, signal) });
  const mutation = useMutation({ mutationFn: (operation: "block" | "reactivate") => changeAccountState(accountId, operation), onSuccess: async (account) => {
    client.setQueryData(["accounts", "detail", accountId], account);
    await client.invalidateQueries({ queryKey: ["accounts", "list"] });
  }, onError: async (error) => { if (error instanceof ApiError && error.status === 409) await query.refetch(); } });
  const account = query.data;
  return <><Link className="back-link" to="/accounts">← Volver a cuentas</Link><div className="page-heading"><div><p className="eyebrow">DETALLE DE CUENTA</p><h1>Cuenta de ahorro</h1><p>Información de la cuenta y gestión de su estado.</p></div><button className="button secondary" disabled={query.isFetching || mutation.isPending} onClick={() => { mutation.reset(); void query.refetch(); }}>Actualizar</button></div>{query.isPending && <Loading />}{query.isError && <ErrorNotice error={query.error} />}{account && <><section className="panel account-overview"><div><span className="eyebrow">NÚMERO DE CUENTA</span><h2 className="mono account-number">{account.account_number}</h2><p className="muted">Referencia interna de CBS; no es un IBAN.</p></div><Status status={account.status} /></section><section className="panel"><div className="panel-heading"><h2>Información de la cuenta</h2><span className="currency">{account.currency}</span></div><dl className="details-grid"><div><dt>ID de cuenta</dt><dd className="mono">{account.id}</dd></div><div><dt>Cliente</dt><dd className="mono">{account.customer_id}</dd></div><div><dt>Producto</dt><dd>Cuenta de ahorro <small>SAVINGS_ACCOUNT</small></dd></div><div><dt>Fecha de apertura</dt><dd>{date(account.opened_at)}</dd></div><div><dt>Fecha de cierre</dt><dd>{account.closed_at ? date(account.closed_at) : "Sin fecha de cierre"}</dd></div><div><dt>Moneda</dt><dd>{account.currency}</dd></div><div><dt>Creación · hora local</dt><dd>{new Date(account.created_at).toLocaleString("es")}</dd></div><div><dt>Última actualización · hora local</dt><dd>{new Date(account.updated_at).toLocaleString("es")}</dd></div></dl></section><section className="panel state-panel"><div><h2>Estado de la cuenta</h2><p className="muted">{account.status === "CLOSED" ? "Esta cuenta está cerrada. Se conserva para consulta histórica." : account.status === "ACTIVE" ? "Puedes bloquear temporalmente esta cuenta." : "Puedes reactivar esta cuenta bloqueada."}</p></div>{account.status !== "CLOSED" && <button className={`button ${account.status === "ACTIVE" ? "danger" : "primary"}`} disabled={mutation.isPending || query.isError} onClick={() => mutation.mutate(account.status === "ACTIVE" ? "block" : "reactivate")}>{mutation.isPending ? "Guardando…" : account.status === "ACTIVE" ? "Bloquear cuenta" : "Reactivar cuenta"}</button>}{mutation.isError && <ErrorNotice error={mutation.error} />}{mutation.isSuccess && <p role="status" className="notice success">Estado actualizado correctamente.</p>}</section></>}</>;
}
