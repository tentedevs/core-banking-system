import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, errorMessage, getAccount, listAccounts } from "../api/accounts";
import type { Account } from "../api/accounts";
import { postOperation } from "../api/transactions";
import type { MonetaryPayload, Operation } from "../api/transactions";
import { ErrorNotice, Money } from "../components/Banking";
import { decimalAmount, intentStorageKey, loadIntent, saveIntent } from "../operationIntent";
import type { Intent } from "../operationIntent";

const titles: Record<Operation, string> = { deposit: "Depósito", withdrawal: "Retirada", transfer: "Transferencia" };

function AccountPicker({ label, id, value, onChange, selected, currency }: { label: string; id: string; value: string; onChange: (id: string) => void; selected?: Account; currency?: string }) {
  const [offset, setOffset] = useState(0);
  const query = useQuery({ queryKey: ["accounts", "list", "", 20, offset], queryFn: ({ signal }) => listAccounts("", 20, offset, signal) });
  const items = query.data?.items ?? [];
  return <div className="account-picker"><label htmlFor={id}>{label}</label><select id={id} value={value} required onChange={e => onChange(e.target.value)}><option value="">Selecciona una cuenta activa</option>{value && !items.some(item => item.id === value) && <option value={value}>{selected ? `${selected.account_number} · ${selected.currency}` : value}</option>}{items.map(item => <option key={item.id} value={item.id} disabled={item.status !== "ACTIVE" || (!!currency && item.currency !== currency)}>{item.account_number} · {item.currency} · {item.status}</option>)}</select>{query.isPending && <p role="status">Cargando cuentas…</p>}{query.isError && <><ErrorNotice error={query.error} /><button type="button" className="button secondary" onClick={() => void query.refetch()}>Reintentar cuentas</button></>}{query.data && <div className="picker-pagination"><button type="button" className="button secondary" aria-label={`${label}: anteriores`} disabled={!offset || query.isFetching} onClick={() => setOffset(Math.max(0, offset - 20))}>←</button><span>{offset + (items.length ? 1 : 0)}–{offset + items.length} de {query.data.pagination.total_items}</span><button type="button" className="button secondary" aria-label={`${label}: siguientes`} disabled={offset + 20 >= query.data.pagination.total_items || query.isFetching} onClick={() => setOffset(offset + 20)}>→</button></div>}</div>;
}
export function MonetaryOperationRoute() {
  const { operation = "" } = useParams();
  if (!["deposit", "withdrawal", "transfer"].includes(operation)) return <section className="panel"><h1>Operación no disponible</h1><Link to="/transactions">Volver a transacciones</Link></section>;
  return <MonetaryOperation key={operation} operation={operation as Operation} />;
}
export function MonetaryOperation({ operation }: { operation: Operation }) {
  const back = "/transactions";
  const operationBase = "/transactions/new";
  const visible = useRef(true);
  useEffect(() => { visible.current = true; return () => { visible.current = false; }; }, []);
  const [params] = useSearchParams(); const navigate = useNavigate(); const client = useQueryClient();
  const [stored] = useState(loadIntent); const [intent, setIntent] = useState(stored.intent);
  const [sourceId, setSourceId] = useState(params.get("account") ?? ""); const [destinationId, setDestinationId] = useState("");
  const [amount, setAmount] = useState(""); const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(stored.error); const submitting = useRef(false);
  const source = useQuery({ queryKey: ["accounts", "detail", sourceId], queryFn: ({ signal }) => getAccount(sourceId, signal), enabled: !!sourceId });
  const destination = useQuery({ queryKey: ["accounts", "detail", destinationId], queryFn: ({ signal }) => getAccount(destinationId, signal), enabled: !!destinationId && operation === "transfer" });
  const mutation = useMutation({ mutationFn: (pending: Intent) => postOperation(pending.operation, pending.payload, pending.key), retry: false });
  function review(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(null);
    try {
      if (!source.data || source.isError || source.data.status !== "ACTIVE") throw new Error("Selecciona una cuenta activa y espera a que termine de cargarse.");
      if (operation === "transfer" && (!destination.data || destination.isError || destination.data.status !== "ACTIVE")) throw new Error("Selecciona una cuenta de destino activa.");
      if (operation === "transfer" && sourceId === destinationId) throw new Error("Origen y destino deben ser cuentas distintas.");
      if (operation === "transfer" && source.data.currency !== destination.data?.currency) throw new Error("Las monedas de las cuentas deben coincidir.");
      const payload: MonetaryPayload = { amount: decimalAmount(amount), currency: source.data.currency, description: description || null, ...(operation === "transfer" ? { source_account_id: sourceId, destination_account_id: destinationId } : { account_id: sourceId }) };
      const pending: Intent = { version: 1, operation, payload, key: crypto.randomUUID(), outcome: "ready" };
      saveIntent(pending); setIntent(pending);
    } catch (cause) { setError(errorMessage(cause)); }
  }
  async function send(pending: Intent) {
    if (submitting.current) return;
    submitting.current = true; setError(null);
    try {
      // Persist uncertainty BEFORE sending: reload/navigation cannot create a new key.
      const sending: Intent = { ...pending, outcome: "uncertain" };
      saveIntent(sending); setIntent(sending);
      const transaction = await mutation.mutateAsync(sending);
      // If storage cleanup fails, retaining the same key is safe on subsequent visits.
      try { sessionStorage.removeItem(intentStorageKey); } catch { /* Keep original key. */ }
      client.setQueryData(["transactions", "detail", transaction.id], transaction);
      const ids = [pending.payload.account_id, pending.payload.source_account_id, pending.payload.destination_account_id].filter((id): id is string => !!id);
      await Promise.all([client.invalidateQueries({ queryKey: ["transactions"] }), ...ids.flatMap(id => [client.invalidateQueries({ queryKey: ["accounts", "balance", id] }), client.invalidateQueries({ queryKey: ["accounts", "movements", id] })])]);
      if (visible.current) navigate(`${"/transactions"}/${transaction.id}`, { state: { posted: true } });
    } catch (cause) {
      const uncertain = !(cause instanceof ApiError) || cause.status === null || cause.status >= 500 || cause.status < 400 || /idempotency/i.test(cause.message);
      const failed: Intent = { ...pending, outcome: uncertain ? "uncertain" : "failed" };
      try { saveIntent(failed); } catch { /* The pre-send receipt remains conservative. */ }
      setIntent(failed);
      const message = errorMessage(cause);
      setError(message === "Insufficient funds" ? "Fondos insuficientes. No se ha registrado la operación." : message === "Account must be ACTIVE" ? "La cuenta debe estar activa." : message);
    } finally { submitting.current = false; }
  }
  function clearPrepared() {
    try { sessionStorage.removeItem(intentStorageKey); setIntent(null); setError(null); mutation.reset(); }
    catch { setError("No se puede actualizar el almacenamiento de la sesión."); }
  }
  if (intent && intent.operation !== operation) return <><h1>Operación pendiente</h1><p className="notice">Hay una petición guardada que debes revisar antes de preparar otra operación.</p><Link className="button primary" to={`${operationBase}/${intent.operation}`}>Recuperar {titles[intent.operation].toLowerCase()}</Link></>;
  return <><Link className="back-link" to={back}>← Volver a transacciones</Link><div className="page-heading"><div><p className="eyebrow">OPERACIÓN MONETARIA</p><h1>{titles[operation]}</h1>{operation === "deposit" && <p>Depósito simulado de efectivo.</p>}</div></div><section className="panel form-panel">
    {error && <ErrorNotice error={new Error(error)} />}
    {intent ? <section aria-label="Confirmar operación"><h2>{intent.outcome === "ready" ? "Revisar operación" : "Petición conservada"}</h2><dl className="confirmation-details"><div><dt>{operation === "transfer" ? "Origen" : "Cuenta"}</dt><dd className="mono">{intent.payload.account_id ?? intent.payload.source_account_id}</dd></div>{intent.payload.destination_account_id && <div><dt>Destino</dt><dd className="mono">{intent.payload.destination_account_id}</dd></div>}<div><dt>Importe</dt><dd><Money amount={intent.payload.amount} currency={intent.payload.currency} /></dd></div><div><dt>Descripción</dt><dd>{intent.payload.description ?? "—"}</dd></div><div><dt>Referencia de petición</dt><dd className="mono">{intent.key}</dd></div></dl>{intent.outcome === "uncertain" && <p role="status" className="notice">El resultado todavía no está confirmado. Reintenta la misma petición: se conservarán los datos y la clave original. No prepares otra operación para sustituirla.</p>}<div className="form-actions">{intent.outcome !== "uncertain" && <button className="button secondary" type="button" disabled={mutation.isPending} onClick={clearPrepared}>{intent.outcome === "ready" ? "Editar antes de enviar" : "Preparar otra operación"}</button>}<button className="button primary" disabled={mutation.isPending} onClick={() => void send(intent)}>{mutation.isPending ? "Enviando…" : intent.outcome === "ready" ? `Confirmar ${titles[operation].toLowerCase()}` : "Reintentar misma petición"}</button></div></section>
      : <form className="create-form" onSubmit={review}><AccountPicker label={operation === "transfer" ? "Cuenta origen" : "Cuenta"} id="source-account" value={sourceId} onChange={setSourceId} selected={source.data} />{source.isError && <ErrorNotice error={source.error} />}{operation === "transfer" && <><AccountPicker label="Cuenta destino" id="destination-account" value={destinationId} onChange={setDestinationId} selected={destination.data} currency={source.data?.currency} />{destination.isError && <ErrorNotice error={destination.error} />}</>}<label htmlFor="amount">Importe</label><input id="amount" inputMode="decimal" required value={amount} onChange={e => setAmount(e.target.value)} placeholder="0.00" /><label htmlFor="operation-currency">Moneda</label><input id="operation-currency" readOnly value={source.data?.currency ?? ""} placeholder="Selecciona una cuenta" /><label htmlFor="description">Descripción</label><input id="description" value={description} onChange={e => setDescription(e.target.value)} /><div className="form-actions"><Link className="button secondary" to={back}>Cancelar</Link><button className="button primary" disabled={!!stored.error}>Revisar operación</button></div></form>}
    </section></>;
}
