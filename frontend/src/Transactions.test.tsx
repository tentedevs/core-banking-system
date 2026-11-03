import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { App } from "./App";
import type { Account } from "./api/accounts";
import type { Transaction, Movement } from "./api/transactions";
import { decimalAmount, intentStorageKey } from "./operationIntent";

const a: Account = { id: "00000000-0000-4000-8000-000000000001", customer_id: "00000000-0000-4000-8000-000000000002", account_number: "CBS-001", product_type: "SAVINGS_ACCOUNT", currency: "CZK", status: "ACTIVE", opened_at: "2026-10-30", closed_at: null, created_at: "2026-10-30T09:00:00Z", updated_at: "2026-10-30T09:00:00Z" };
const b = { ...a, id: "00000000-0000-4000-8000-000000000003", account_number: "CBS-002" };
const euro = { ...a, id: "00000000-0000-4000-8000-000000000004", account_number: "CBS-EUR", currency: "EUR" };
const blocked: Account = { ...a, id: "00000000-0000-4000-8000-000000000005", account_number: "CBS-BLOCKED", status: "BLOCKED" };
const transaction: Transaction = { id: "00000000-0000-4000-8000-000000000010", transaction_type: "DEPOSIT", status: "POSTED", amount: "500.00", currency: "CZK", description: "Efectivo", effective_at: a.created_at, created_at: a.created_at, posted_at: a.created_at, idempotency_key: "historical-key", reversal_of_id: null };
const movement: Movement = { id: "00000000-0000-4000-8000-000000000020", transaction_id: transaction.id, account_id: a.id, direction: "CREDIT", amount: "500.00", balance_after: "500.00", booked_at: a.created_at, category: "SIMULATED_CASH_DEPOSIT", counterparty_account: null, counterparty_bank: null };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const page = (items: unknown[], total = items.length, limit = 20, offset = 0) => ({ items, pagination: { limit, offset, total_items: total, total_pages: Math.ceil(total / limit) } });
function posted(path: string, init: RequestInit): Transaction {
  const body = JSON.parse(String(init.body));
  return {...transaction,amount:body.amount,description:body.description,transaction_type:path.endsWith("transfers") ? "TRANSFER" : path.endsWith("withdrawals") ? "WITHDRAWAL" : "DEPOSIT",idempotency_key:new Headers(init.headers).get("Idempotency-Key")};
}
const fetchMock = vi.fn<typeof fetch>();
let onPost: ((url: string, init: RequestInit) => Response | Promise<Response>) | undefined;
let accounts = [a,b,euro,blocked]; let total = 1; let tx: Transaction; let effects: Movement[];
let booked = "500.00";
const clients: QueryClient[] = [];
beforeEach(() => {
  sessionStorage.clear(); fetchMock.mockReset(); onPost = undefined;
  accounts = [a,b,euro,blocked]; total = 1; tx = { ...transaction }; effects = [{ ...movement }]; booked = "500.00";
  fetchMock.mockImplementation(async (input, init) => {
    const url = new URL(String(input), "http://localhost"); const path = url.pathname;
    const limit = Number(url.searchParams.get("limit") ?? 20), offset = Number(url.searchParams.get("offset") ?? 0);
    if (init?.method === "POST") {
      const result = onPost ? await onPost(path, init) : json(posted(path,init),201);
      if (result.status === 201) tx = await result.clone().json();
      return result;
    }
    if (path === "/api/accounts") return json(page(accounts.slice(offset,offset+limit), accounts.length,limit,offset));
    if (path.endsWith("/balance")) return json({ account_id:a.id, booked_balance:booked, available_balance:booked, updated_at:a.created_at });
    if (path.endsWith("/movements")) return json(page(effects.slice(offset,offset+limit),effects.length,limit,offset));
    if (path.startsWith("/api/accounts/")) return json(accounts.find(item => item.id === path.split("/").at(-1)) ?? { detail:"not found" });
    if (path === "/api/transactions") return json(page(offset ? [] : [tx],total,limit,offset));
    if (path.startsWith("/api/transactions/")) return json(tx);
    return json({ detail:"not found" },404);
  });
  vi.stubGlobal("fetch",fetchMock);
});
afterEach(() => { clients.forEach(client => client.clear()); clients.length = 0; vi.unstubAllGlobals(); });
function show(path = "/transactions", client = new QueryClient({ defaultOptions: { queries: { retry:false }, mutations: { retry:false } } })) {
  clients.push(client);
  const view = render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>);
  return { ...view, client };
}
const posts = () => fetchMock.mock.calls.filter(([,init]) => init?.method === "POST");
async function review(operation = "deposit", amount = "50.00", source = a.id, destination = b.id) {
  show(`/transactions/new/${operation}?account=${source}`);
  const user = userEvent.setup();
  await screen.findByDisplayValue("CZK");
  if (operation === "transfer") { await user.selectOptions(screen.getByLabelText("Cuenta destino"), destination); }
  await user.type(screen.getByLabelText("Importe"),amount);
  await user.click(screen.getByRole("button",{name:"Revisar operación"}));
  await screen.findByRole("region",{name:"Confirmar operación"});
  return user;
}

it("lista datos reales y aplica filtros, paginación y actualización en el servidor", async () => {
  total = 41; show(); const user = userEvent.setup();
  await screen.findByRole("link",{name:`Abrir transacción ${tx.id}`});
  expect(screen.getByText("500.00")).toBeTruthy();
  await user.click(screen.getByRole("button",{name:"Siguiente"}));
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("limit=20&offset=20"))).toBe(true));
  await user.selectOptions(screen.getByLabelText("Tipo"),"TRANSFER");
  await user.selectOptions(screen.getByLabelText("Estado"),"PENDING");
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/transactions?limit=20&offset=0&transaction_type=TRANSFER&status=PENDING")).toBe(true));
  const before = fetchMock.mock.calls.length;
  await user.click(screen.getByRole("button",{name:"Actualizar"}));
  await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(before));
});
it("muestra carga, vacío y error sin inventar transacciones", async () => {
  fetchMock.mockReturnValue(new Promise(() => {})); const view = show();
  expect(screen.getByText("Cargando transacciones…")).toBeTruthy(); view.unmount();
  fetchMock.mockResolvedValue(json(page([]))); const empty = show();
  expect(await screen.findByText("No hay transacciones en esta página.")).toBeTruthy(); empty.unmount();
  fetchMock.mockResolvedValue(json({ detail:"private SQL" },500)); show();
  expect((await screen.findByRole("alert")).textContent).not.toContain("private SQL");
});
it("abre el detalle con movimientos asociados y navega al detalle de cuenta", async () => {
  effects = [movement,{...movement,id:"another",account_id:b.id,direction:"DEBIT",balance_after:"150.00"}];
  show(`/transactions/${tx.id}`); const user = userEvent.setup();
  const table = await screen.findByRole("table");
  expect(within(table).getByText("CREDIT · Entrada")).toBeTruthy();
  expect(within(table).getByText("DEBIT · Salida")).toBeTruthy();
  expect(fetchMock.mock.calls.some(([url]) => url === `/api/transactions/${tx.id}/movements?limit=20&offset=0`)).toBe(true);
  await user.click(within(table).getByRole("link",{name:a.id}));
  expect(await screen.findByRole("heading",{name:a.account_number})).toBeTruthy();
  expect(await screen.findByRole("heading",{name:"Balance actual"})).toBeTruthy();
  expect(screen.getByRole("link",{name:"Depósito"}).getAttribute("href")).toContain(`account=${a.id}`);
});
it("maneja transacciones rechazadas sin movimientos", async () => {
  tx = { ...tx,status:"REJECTED",posted_at:null }; effects = [];
  show(`/transactions/${tx.id}`);
  expect(await screen.findByText("Rechazada")).toBeTruthy();
  expect(await screen.findByText("No hay movimientos registrados.")).toBeTruthy();
});
it.each(["deposit","withdrawal","transfer"])("confirma %s y envía únicamente el contrato real con importes string", async operation => {
  const user = await review(operation);
  expect(posts()).toHaveLength(0);
  const stored = JSON.parse(sessionStorage.getItem(intentStorageKey)!);
  await user.click(screen.getByRole("button",{name:`Confirmar ${operation === "deposit" ? "depósito" : operation === "withdrawal" ? "retirada" : "transferencia"}`}));
  expect(await screen.findByText("Operación registrada correctamente.")).toBeTruthy();
  expect(posts()).toHaveLength(1);
  const [url,init] = posts()[0]!;
  expect(url).toBe(`/api/transactions/${operation === "deposit" ? "deposits" : operation === "withdrawal" ? "withdrawals" : "transfers"}`);
  expect(new Headers(init?.headers).get("Idempotency-Key")).toBe(stored.key);
  expect(JSON.parse(String(init?.body))).toEqual({amount:"50.00",currency:"CZK",description:null,...(operation === "transfer" ? {source_account_id:a.id,destination_account_id:b.id} : {account_id:a.id})});
  expect(sessionStorage.getItem(intentStorageKey)).toBeNull();
});
it.each(["0","-1","0.001","1e3","1,50","10000000000000000"])("rechaza el importe %s antes de enviar", async amount => {
  show(`/transactions/new/deposit?account=${a.id}`); const user = userEvent.setup();
  await screen.findByDisplayValue("CZK"); await user.type(screen.getByLabelText("Importe"),amount);
  await user.click(screen.getByRole("button",{name:"Revisar operación"}));
  expect(await screen.findByRole("alert")).toBeTruthy(); expect(posts()).toHaveLength(0);
});
it("preserva la precisión en los límites monetarios", () => {
  expect(decimalAmount("9999999999999999.99")).toBe("9999999999999999.99");
  expect(decimalAmount("1.2")).toBe("1.20");
});
it("exige una cuenta seleccionada y no permite cuentas bloqueadas", async () => {
  show("/transactions/new/deposit"); const user = userEvent.setup();
  await user.type(screen.getByLabelText("Importe"),"1"); await user.click(screen.getByRole("button",{name:"Revisar operación"}));
  expect(posts()).toHaveLength(0);
  expect((screen.getByRole("option",{name:/CBS-BLOCKED/}) as HTMLOptionElement).disabled).toBe(true);
});
it("rechaza transferencias a la misma cuenta", async () => {
  show(`/transactions/new/transfer?account=${a.id}`); const user = userEvent.setup();
  await screen.findByDisplayValue("CZK"); await user.selectOptions(screen.getByLabelText("Cuenta destino"),a.id);
  await user.type(screen.getByLabelText("Importe"),"1"); await user.click(screen.getByRole("button",{name:"Revisar operación"}));
  expect((await screen.findByRole("alert")).textContent).toContain("distintas");
  expect(posts()).toHaveLength(0);
  expect((within(screen.getByLabelText("Cuenta destino")).getByRole("option",{name:/CBS-EUR/}) as HTMLOptionElement).disabled).toBe(true);
});
it("pagina las cuentas seleccionables sin descargar el directorio completo", async () => {
  accounts = Array.from({length:21},(_,i) => ({...a,id:`00000000-0000-4000-8000-${String(i+100).padStart(12,"0")}`,account_number:`CBS-${i}`}));
  show("/transactions/new/deposit"); const user = userEvent.setup();
  await screen.findByRole("option",{name:/CBS-0 ·/}); await user.click(screen.getByRole("button",{name:"Cuenta: siguientes"}));
  expect(await screen.findByRole("option",{name:/CBS-20 ·/})).toBeTruthy();
  expect(fetchMock.mock.calls.some(([url]) => url === "/api/accounts?limit=20&offset=20")).toBe(true);
});
it("muestra fondos insuficientes y conserva la petición para un reintento explícito", async () => {
  onPost = () => json({detail:"Insufficient funds"},409);
  const user = await review("withdrawal");
  await user.click(screen.getByRole("button",{name:"Confirmar retirada"}));
  expect((await screen.findByRole("alert")).textContent).toContain("Fondos insuficientes");
  await user.click(screen.getByRole("button",{name:"Reintentar misma petición"}));
  await waitFor(() => expect(posts()).toHaveLength(2));
  expect(posts()[0]![1]?.headers).toEqual(posts()[1]![1]?.headers);
});
it("impide doble envío durante la petición", async () => {
  let complete!: (response: Response) => void;
  onPost = () => new Promise(resolve => {complete = resolve;});
  const user = await review(); await user.dblClick(screen.getByRole("button",{name:"Confirmar depósito"}));
  expect(posts()).toHaveLength(1);
  expect((screen.getByRole("button",{name:"Enviando…"}) as HTMLButtonElement).disabled).toBe(true);
  complete(json(posted(String(posts()[0]![0]),posts()[0]![1]!),201)); await screen.findByText("Operación registrada correctamente.");
});
it("recupera una respuesta incierta tras recargar sin generar otra clave", async () => {
  onPost = () => { throw new TypeError("network outcome unknown"); };
  const user = await review(); await user.click(screen.getByRole("button",{name:"Confirmar depósito"}));
  await screen.findByRole("button",{name:"Reintentar misma petición"});
  expect(screen.queryByRole("button",{name:"Preparar otra operación"})).toBeNull();
  const first = posts()[0]!; const saved = sessionStorage.getItem(intentStorageKey);
  // A reload unmounts the component and discards its React Query cache.
  const {cleanup} = await import("@testing-library/react"); cleanup();
  onPost = (url,init) => json(posted(url,init),201); show("/transactions/new/deposit");
  await screen.findByRole("button",{name:"Reintentar misma petición"});
  expect(posts()).toHaveLength(1); expect(sessionStorage.getItem(intentStorageKey)).toBe(saved);
  await user.click(screen.getByRole("button",{name:"Reintentar misma petición"}));
  await screen.findByText("Operación registrada correctamente.");
  expect(posts()[1]![1]?.body).toBe(first[1]?.body);
  expect(posts()[1]![1]?.headers).toEqual(first[1]?.headers);
});
it.each([500,503])("un HTTP %s no cambia la clave ni permite sustituir una petición incierta", async status => {
  onPost = () => json({detail:"private SQL"},status);
  const user = await review(); await user.click(screen.getByRole("button",{name:"Confirmar depósito"}));
  expect((await screen.findByRole("alert")).textContent).not.toContain("private SQL");
  expect(screen.queryByRole("button",{name:"Preparar otra operación"})).toBeNull();
  expect(JSON.parse(sessionStorage.getItem(intentStorageKey)!).outcome).toBe("uncertain");
});
it("invalida balances, movimientos e historial después del éxito y muestra el balance del servidor", async () => {
  const user = await review();
  const client = clients.at(-1)!;
  client.setQueryData(["accounts","balance",a.id],{account_id:a.id,booked_balance:"500.00",available_balance:"500.00",updated_at:a.created_at});
  client.setQueryData(["accounts","movements",a.id,20,0],page([movement]));
  client.setQueryData(["transactions","list","","",20,0],page([transaction]));
  onPost = (url,init) => {booked = "550.00";return json(posted(url,init),201);};
  await user.click(screen.getByRole("button",{name:"Confirmar depósito"}));
  await screen.findByText("Operación registrada correctamente.");
  expect(client.getQueryState(["accounts","balance",a.id])?.isInvalidated).toBe(true);
  expect(client.getQueryState(["accounts","movements",a.id,20,0])?.isInvalidated).toBe(true);
  expect(client.getQueryState(["transactions","list","","",20,0])?.isInvalidated).toBe(true);
  await user.click(await screen.findByRole("link",{name:a.id}));
  expect(await screen.findAllByText("550.00 CZK")).toHaveLength(2);
});
it("comprueba compatibilidad de monedas si se cambia el origen", async () => {
  show(`/transactions/new/transfer?account=${a.id}`); const user = userEvent.setup();
  await screen.findByDisplayValue("CZK");
  await user.selectOptions(screen.getByLabelText("Cuenta destino"),b.id);
  await user.selectOptions(screen.getByLabelText("Cuenta origen"),euro.id);
  await screen.findByDisplayValue("EUR"); await user.type(screen.getByLabelText("Importe"),"1");
  await user.click(screen.getByRole("button",{name:"Revisar operación"}));
  expect((await screen.findByRole("alert")).textContent).toContain("monedas");
  expect(posts()).toHaveLength(0);
});
it("una operación nueva tras el éxito recibe una nueva clave", async () => {
  const user = await review();
  await user.click(screen.getByRole("button",{name:"Confirmar depósito"}));
  await screen.findByText("Operación registrada correctamente.");
  const firstKey = new Headers(posts()[0]![1]?.headers).get("Idempotency-Key");
  await user.click(screen.getByRole("link",{name:"← Volver a transacciones"}));
  await user.click(screen.getByRole("link",{name:"Depósito"}));
  await user.selectOptions(screen.getByLabelText("Cuenta"),a.id);
  await screen.findByDisplayValue("CZK"); await user.type(screen.getByLabelText("Importe"),"2");
  await user.click(screen.getByRole("button",{name:"Revisar operación"}));
  expect(JSON.parse(sessionStorage.getItem(intentStorageKey)!).key).not.toBe(firstKey);
  expect(posts()).toHaveLength(1);
});
it("bloquea otra operación mientras existe una petición incierta", async () => {
  onPost = () => {throw new TypeError("network");};
  const user = await review(); await user.click(screen.getByRole("button",{name:"Confirmar depósito"}));
  await screen.findByRole("button",{name:"Reintentar misma petición"});
  const {cleanup} = await import("@testing-library/react"); cleanup();
  show("/transactions/new/transfer");
  expect(screen.getByRole("link",{name:"Recuperar depósito"})).toBeTruthy();
  expect(screen.queryByLabelText("Importe")).toBeNull(); expect(posts()).toHaveLength(1);
});
it("no envía dinero si no puede guardar la clave idempotente", async () => {
  show(`/transactions/new/deposit?account=${a.id}`); const user = userEvent.setup();
  await screen.findByDisplayValue("CZK"); await user.type(screen.getByLabelText("Importe"),"1");
  const write = vi.spyOn(Storage.prototype,"setItem").mockImplementation(() => {throw new Error("Storage unavailable");});
  try {
    await user.click(screen.getByRole("button",{name:"Revisar operación"}));
    expect((await screen.findByRole("alert")).textContent).toContain("Storage unavailable");
    expect(posts()).toHaveLength(0);
  } finally {write.mockRestore();}
});
it("una respuesta 201 incompleta conserva la clave y no confirma éxito", async () => {
  onPost = () => json({},201);
  const user = await review(); await user.click(screen.getByRole("button",{name:"Confirmar depósito"}));
  expect((await screen.findByRole("alert")).textContent).toContain("confirmación incompleta");
  expect(screen.queryByText("Operación registrada correctamente.")).toBeNull();
  expect(JSON.parse(sessionStorage.getItem(intentStorageKey)!).outcome).toBe("uncertain");
  const firstKey = new Headers(posts()[0]![1]?.headers).get("Idempotency-Key");
  onPost = (url,init) => json(posted(url,init),201);
  await user.click(screen.getByRole("button",{name:"Reintentar misma petición"}));
  await screen.findByText("Operación registrada correctamente.");
  expect(new Headers(posts()[1]![1]?.headers).get("Idempotency-Key")).toBe(firstKey);
});
