import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useNavigate } from "react-router";
import { App } from "./App";
import type { Account } from "./api/accounts";
import type { Movement, Transaction } from "./api/transactions";
import { sumMoney } from "./features/customer-banking/money";
import { intentStorageKey } from "./operationIntent";
const customerA="00000000-0000-4000-8000-000000000001", customerB="00000000-0000-4000-8000-000000000002";
const account:Account={id:"00000000-0000-4000-8000-000000000010",customer_id:customerA,account_number:"MIA-CZK",product_type:"SAVINGS_ACCOUNT",currency:"CZK",status:"ACTIVE",opened_at:"2026-10-30",closed_at:null,created_at:"2026-10-30T10:00:00Z",updated_at:"2026-10-30T10:00:00Z"};
const second={...account,id:"00000000-0000-4000-8000-000000000011",account_number:"MIA-SEGUNDA"};
const euro:Account={...account,id:"00000000-0000-4000-8000-000000000012",account_number:"MIA-EUR",currency:"EUR",status:"BLOCKED"};
const foreign={...account,id:"00000000-0000-4000-8000-000000000013",customer_id:customerB,account_number:"DESTINO-EXTERNO"};
const tx:Transaction={id:"00000000-0000-4000-8000-000000000020",transaction_type:"TRANSFER",status:"POSTED",amount:"10.00",currency:"CZK",description:"Mi transferencia",effective_at:account.created_at,created_at:account.created_at,posted_at:account.created_at,idempotency_key:"old",reversal_of_id:null};
const movement:Movement={id:"00000000-0000-4000-8000-000000000030",transaction_id:tx.id,account_id:account.id,direction:"DEBIT",amount:"10.00",balance_after:"100.00",booked_at:"2026-10-30T12:00:00Z",category:"INTERNAL_TRANSFER",counterparty_account:foreign.account_number,counterparty_bank:null};
const foreignMove={...movement,id:"00000000-0000-4000-8000-000000000031",account_id:foreign.id,direction:"CREDIT" as const,balance_after:"999.00"};
const json=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status});
const fetchMock=vi.fn<typeof fetch>();
const clients:QueryClient[]=[];
let rows:Account[], balances:Record<string,string>, history:Record<string,Movement[]>, transactionMovements:Movement[], current:Transaction;
let missingCustomerAccounts=false;
let intercept:((url:URL,init?:RequestInit)=>Promise<Response>|Response|undefined)|undefined;
beforeEach(()=>{
  rows=[account,second,euro,foreign];balances={[account.id]:"100.00",[second.id]:"50.00",[euro.id]:"30.00",[foreign.id]:"999.00"};
  history={[account.id]:[movement], [second.id]:[],[euro.id]:[],[foreign.id]:[foreignMove]}; transactionMovements=[movement,foreignMove];current={...tx};missingCustomerAccounts=false;intercept=undefined;
  sessionStorage.clear();fetchMock.mockReset();
  fetchMock.mockImplementation(async(input,init)=>{
    const url=new URL(String(input),"http://localhost");
    const override=intercept?.(url,init);if(override)return override;
    const path=url.pathname;const limit=Number(url.searchParams.get("limit")??20),offset=Number(url.searchParams.get("offset")??0);
    const page=(items:unknown[])=>({items:items.slice(offset,offset+limit),pagination:{limit,offset,total_items:items.length,total_pages:Math.ceil(items.length/limit)}});
    if(init?.method==="POST"){
      const p=JSON.parse(String(init.body));const source=p.account_id??p.source_account_id;
      current={...tx,transaction_type:path.endsWith("deposits")?"DEPOSIT":path.endsWith("withdrawals")?"WITHDRAWAL":"TRANSFER",amount:p.amount,currency:p.currency,description:p.description,idempotency_key:new Headers(init.headers).get("Idempotency-Key")};
      transactionMovements=[{...movement,account_id:source,amount:p.amount}];
      return json(current,201);
    }
    if(path==="/api/accounts"){
      const customer=url.searchParams.get("customer_id");
      return json(page(customer?(missingCustomerAccounts?[]:rows.filter(row=>row.customer_id===customer)):rows));
    }
    if(path.includes("/accounts/by-number/"))return json(rows.find(row=>row.account_number===decodeURIComponent(path.split("/").at(-1)!))??{},200);
    if(path.endsWith("/balance")){const id=path.split("/").at(-2)!;return json({account_id:id,booked_balance:balances[id],available_balance:balances[id],updated_at:account.updated_at});}
    if(path.endsWith("/movements")){const id=path.split("/").at(-2)!;return json(page(path.includes("/transactions/")?transactionMovements:history[id]??[]));}
    if(path.startsWith("/api/accounts/"))return json(rows.find(row=>row.id===path.split("/").at(-1))??{},200);
    if(path==="/api/transactions")return json(page([current]));
    if(path.startsWith("/api/transactions/"))return json(current);
    return json({detail:"not found"},404);
  });
  vi.stubGlobal("fetch",fetchMock);
});
afterEach(()=>{clients.forEach(client=>client.clear());clients.length=0;vi.unstubAllGlobals();});
function TestNavigation(){
  const navigate=useNavigate();
  return <div aria-label="Navegación de prueba"><button onClick={()=>navigate(`/banking/accounts/${foreign.id}`)}>Abrir cuenta ajena</button><button onClick={()=>navigate(`/banking/operations/deposit?account=${foreign.id}`)}>Abrir operación ajena</button></div>;
}
function show(path="/banking"){
  const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});clients.push(client);
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App/><TestNavigation/></MemoryRouter></QueryClientProvider>);
}
async function select(customer=customerA){
  const user=userEvent.setup();await screen.findByRole("option",{name:customer});await user.selectOptions(screen.getByLabelText("Cliente DEMO"),customer);return user;
}
const posts=()=>fetchMock.mock.calls.filter(([,init])=>init?.method==="POST");
it("presenta DEMO y descubre referencias reales sin inventar /customers",async()=>{
  show();await screen.findByRole("option",{name:customerA});
  expect(screen.getByText(/sin autenticación ni autorización/)).toBeTruthy();
  expect(screen.getByRole("heading",{name:"Tu banca en modo DEMO"})).toBeTruthy();
  expect(fetchMock.mock.calls.some(([url])=>String(url).includes("/customers"))).toBe(false);
});
it("filtra cuentas en el servidor y suma saldos por moneda con precisión exacta",async()=>{
  show();await select();await screen.findByRole("link",{name:"MIA-CZK"});
  expect(fetchMock.mock.calls.some(([url])=>String(url).includes(`customer_id=${customerA}`))).toBe(true);
  expect(await screen.findAllByText("150.00 CZK")).toHaveLength(2);
  expect(await screen.findAllByText("30.00 EUR")).toHaveLength(3);
  expect(screen.queryByText(foreign.account_number)).toBeNull();
  expect(screen.getByText("Cuentas activas").nextSibling?.textContent).toBe("2");
  expect(sumMoney(["9999999999999999.99","0.01"])).toBe("10000000000000000.00");
  expect(sumMoney(["-10.01","2.02"])).toBe("-7.99");
});
it("combina movimientos recientes, los ordena y elimina duplicados",async()=>{
  const older={...movement,id:"00000000-0000-4000-8000-000000000039",account_id:second.id,booked_at:"2026-10-29T10:00:00Z",amount:"9.00"};
  history[account.id]=[movement,movement];history[second.id]=[older];
  show();await select();const table=await screen.findByRole("table");
  const tableRows=within(table).getAllByRole("row").slice(1);
  expect(tableRows).toHaveLength(2);expect(tableRows[0]?.textContent).toContain("10.00");expect(tableRows[1]?.textContent).toContain("9.00");
  expect(screen.getByText(/No es una paginación global/)).toBeTruthy();
  expect(fetchMock.mock.calls.some(([url])=>String(url).includes(`${foreign.id}/movements`))).toBe(false);
});
it("cambia de cliente sin mostrar datos anteriores durante respuestas tardías",async()=>{
  let finish!:(response:Response)=>void;
  show();const user=await select();await screen.findByRole("link",{name:account.account_number});
  intercept=(url)=>url.pathname==="/api/accounts"&&url.searchParams.get("customer_id")===customerB?new Promise(resolve=>{finish=resolve;}):undefined;
  await user.selectOptions(screen.getByLabelText("Cliente DEMO"),customerB);
  expect(screen.queryByRole("link",{name:account.account_number})).toBeNull();expect(screen.queryByText("150.00 CZK")).toBeNull();
  await waitFor(()=>expect(finish).toBeTypeOf("function"));
  finish(json({items:[foreign],pagination:{limit:100,offset:0,total_items:1,total_pages:1}}));
  expect(await screen.findByRole("link",{name:foreign.account_number})).toBeTruthy();
});
it("conserva una referencia seleccionada que ahora no tiene cuentas",async()=>{
  show();const user=await select();await screen.findByRole("link",{name:account.account_number});
  missingCustomerAccounts=true;
  await user.click(screen.getByRole("button",{name:"Actualizar mi banca"}));
  expect(await screen.findByRole("heading",{name:"No tienes cuentas asociadas"})).toBeTruthy();
  expect(screen.queryByText("150.00 CZK")).toBeNull();
});
it("muestra detalle, balance e historial sin controles administrativos",async()=>{
  show();const user=await select();await user.click(await screen.findByRole("link",{name:account.account_number}));
  expect(await screen.findByRole("heading",{name:account.account_number})).toBeTruthy();
  expect(await screen.findAllByText("100.00 CZK")).toHaveLength(2);
  const table=await screen.findByRole("table");
  expect(within(table).getByRole("link",{name:tx.id}).getAttribute("href")).toBe(`/banking/transactions/${tx.id}`);
  expect(screen.queryByRole("button",{name:"Bloquear cuenta"})).toBeNull();
});
it("no muestra una cuenta ajena solicitada por URL",async()=>{
  show();const user=await select();await screen.findByRole("link",{name:account.account_number});
  await user.click(screen.getByRole("button",{name:"Abrir cuenta ajena"}));
  expect(await screen.findByRole("heading",{name:"No disponible en este contexto DEMO"})).toBeTruthy();
  expect(screen.queryByText(foreign.account_number)).toBeNull();
  expect(fetchMock.mock.calls.some(([url])=>String(url).includes(`${foreign.id}/balance`))).toBe(false);
});
it("rechaza un origen ajeno preseleccionado sin cargar sus datos",async()=>{
  show();const user=await select();await screen.findByRole("link",{name:account.account_number});
  await user.click(screen.getByRole("button",{name:"Abrir operación ajena"}));
  expect(await screen.findByRole("heading",{name:"No disponible en este contexto DEMO"})).toBeTruthy();
  expect(screen.queryByLabelText("Importe")).toBeNull();expect(posts()).toHaveLength(0);
  expect(fetchMock.mock.calls.some(([url])=>url===`/api/accounts/${foreign.id}`)).toBe(false);
});
it("filtra ambos lados de una transferencia y oculta la cuenta del otro cliente",async()=>{
  show();const user=await select();const table=await screen.findByRole("table");
  await user.click(within(table).getByRole("link",{name:tx.id}));
  expect(await screen.findByRole("heading",{name:"Detalle de operación"})).toBeTruthy();
  await screen.findByText("Mi transferencia");
  expect(screen.queryByRole("link",{name:foreign.id})).toBeNull();expect(screen.queryByText("999.00")).toBeNull();
  expect(screen.queryByText(foreign.account_number)).toBeNull();
  const own=screen.getByRole("table");expect(within(own).getAllByRole("row")).toHaveLength(2);
});
it.each(["deposit","withdrawal","transfer"])("ejecuta %s con confirmación y el contrato existente",async operation=>{
  show();const user=await select();await screen.findByRole("link",{name:account.account_number});
  await user.click(screen.getByRole("link",{name:operation==="transfer"?"Transferir":operation==="deposit"?"Depósito simulado":"Retirada simulada"}));
  await user.selectOptions(screen.getByLabelText(operation==="transfer"?"Cuenta origen":"Cuenta"),account.id);
  await screen.findByDisplayValue("CZK");
  if(operation==="transfer"){
    expect(screen.queryByRole("option",{name:/DESTINO-EXTERNO/})).toBeNull();
    await user.type(screen.getByLabelText("Referencia CBS de destino"),foreign.account_number);
    await user.click(screen.getByRole("button",{name:"Comprobar destino"}));
    await screen.findByText(/Cuenta destino localizada/);
    expect(within(screen.getByRole("main")).queryByText(customerB)).toBeNull();
  } else expect(screen.getByText(operation==="deposit"?"Depósito simulado de efectivo.":"Retirada simulada de efectivo.")).toBeTruthy();
  await user.type(screen.getByLabelText("Importe"),"10");
  await user.click(screen.getByRole("button",{name:"Revisar operación"}));
  expect(posts()).toHaveLength(0);
  if(operation==="transfer") expect(screen.queryByText(foreign.id)).toBeNull();
  await user.click(screen.getByRole("button",{name:`Confirmar ${operation==="deposit"?"depósito":operation==="withdrawal"?"retirada":"transferencia"}`}));
  expect(await screen.findByText("Operación registrada correctamente.")).toBeTruthy();
  const payload=JSON.parse(String(posts()[0]![1]?.body));
  expect(payload.amount).toBe("10.00");expect(payload.customer_id).toBeUndefined();
  expect(payload.account_id??payload.source_account_id).toBe(account.id);
  if(operation==="transfer")expect(payload.destination_account_id).toBe(foreign.id);
});
it("no presenta totales parciales como saldos completos cuando falla un balance",async()=>{
  intercept=url=>url.pathname===`/api/accounts/${second.id}/balance`?json({detail:"private SQL"},503):undefined;
  show();await select();
  expect(await screen.findByText("Totales no disponibles: falta algún balance.")).toBeTruthy();
  expect(screen.queryByText("150.00 CZK")).toBeNull();
  expect(await screen.findAllByRole("alert")).not.toHaveLength(0);
  expect(screen.getByText("Total contabilizado")).toBeTruthy();
});
it("maneja fallos del backend y permite volver a Administración",async()=>{
  intercept=url=>url.searchParams.get("customer_id")?json({detail:"private SQL"},500):undefined;
  show();const user=await select();
  expect((await screen.findByRole("alert")).textContent).not.toContain("private SQL");
  await user.click(screen.getByRole("link",{name:"Administración →"}));
  expect(await screen.findByRole("heading",{name:"Cuentas"})).toBeTruthy();
  await user.click(screen.getByRole("link",{name:"Banca cliente · DEMO →"}));
  expect(screen.getByLabelText("Cliente DEMO")).toBeTruthy();
});
it("un selector sin referencias no inventa clientes",async()=>{
  rows=[];show();expect(await screen.findByText("No hay referencias de clientes en las cuentas disponibles.")).toBeTruthy();
  expect(screen.getAllByRole("option")).toHaveLength(1);
});
it("no persiste la identidad DEMO entre montajes",async()=>{
  const view=show();await select();await screen.findByRole("link",{name:account.account_number});view.unmount();show();
  expect(screen.getByRole("heading",{name:"Tu banca en modo DEMO"})).toBeTruthy();
});
it("una petición de otro cliente conserva su clave sin revelar su payload",async()=>{
  sessionStorage.setItem(intentStorageKey,JSON.stringify({version:1,operation:"deposit",key:"safe-original",customer_id:customerB,payload:{account_id:foreign.id,amount:"123.00",currency:"CZK",description:"private-other-description"},outcome:"uncertain"}));
  show();const user=await select();await user.click(screen.getByRole("link",{name:"Depósito simulado"}));
  expect(await screen.findByRole("heading",{name:"Petición de otro contexto"})).toBeTruthy();
  expect(screen.queryByText("private-other-description")).toBeNull();expect(screen.queryByText(foreign.id)).toBeNull();expect(posts()).toHaveLength(0);
  expect(JSON.parse(sessionStorage.getItem(intentStorageKey)!).key).toBe("safe-original");
});
it("una respuesta tardía del balance anterior no reaparece tras cambiar cliente",async()=>{
  let finish!:(response:Response)=>void;
  intercept=url=>url.pathname===`/api/accounts/${account.id}/balance`?new Promise(resolve=>{finish=resolve;}):undefined;
  show();const user=await select();await screen.findByRole("link",{name:account.account_number});
  await waitFor(()=>expect(finish).toBeTypeOf("function"));
  await user.selectOptions(screen.getByLabelText("Cliente DEMO"),customerB);
  await screen.findByRole("link",{name:foreign.account_number});
  finish(json({account_id:account.id,booked_balance:"123456.78",available_balance:"123456.78",updated_at:account.updated_at}));
  await waitFor(()=>expect(screen.queryByText("123456.78 CZK")).toBeNull());
  expect(screen.queryByRole("link",{name:account.account_number})).toBeNull();
});
it("no muestra metadatos de una transacción sin movimientos del cliente",async()=>{
  transactionMovements=[foreignMove];show();const user=await select();
  await user.click(within(await screen.findByRole("table")).getByRole("link",{name:tx.id}));
  expect(await screen.findByRole("heading",{name:"No disponible en este contexto DEMO"})).toBeTruthy();
  expect(screen.queryByText(tx.description!)).toBeNull();
  expect(fetchMock.mock.calls.some(([url])=>url===`/api/transactions/${tx.id}`)).toBe(false);
});
it("recorre referencias reales paginadas sin duplicar clientes",async()=>{
  rows=[...Array.from({length:100},(_,i)=>({...account,id:`00000000-0000-4000-8000-${String(i+100).padStart(12,"0")}`})),foreign];
  show();const user=userEvent.setup();await screen.findByRole("option",{name:customerA});
  expect(screen.queryByRole("option",{name:customerB})).toBeNull();
  await user.click(screen.getByRole("button",{name:"Cargar más referencias"}));
  expect(await screen.findByRole("option",{name:customerB})).toBeTruthy();
  expect(screen.getAllByRole("option",{name:customerA})).toHaveLength(1);
  expect(fetchMock.mock.calls.some(([url])=>url==="/api/accounts?limit=100&offset=100")).toBe(true);
});
it("al cambiar de cliente se descarta el formulario visible pero no la clave pendiente",async()=>{
  show();const user=await select();await user.click(screen.getByRole("link",{name:"Depósito simulado"}));
  await user.selectOptions(screen.getByLabelText("Cuenta"),account.id);await screen.findByDisplayValue("CZK");
  await user.type(screen.getByLabelText("Importe"),"12");await user.type(screen.getByLabelText("Descripción"),"private-demo-A");
  await user.click(screen.getByRole("button",{name:"Revisar operación"}));
  const key=JSON.parse(sessionStorage.getItem(intentStorageKey)!).key;
  await user.selectOptions(screen.getByLabelText("Cliente DEMO"),customerB);
  expect(screen.queryByText("private-demo-A")).toBeNull();
  await screen.findByRole("link",{name:foreign.account_number});await user.click(screen.getByRole("link",{name:"Depósito simulado"}));
  expect(await screen.findByRole("heading",{name:"Petición de otro contexto"})).toBeTruthy();
  expect(screen.queryByText("private-demo-A")).toBeNull();expect(posts()).toHaveLength(0);
  expect(JSON.parse(sessionStorage.getItem(intentStorageKey)!).key).toBe(key);
});
it("conserva los enlaces administrativos antiguos y sus alias /admin",async()=>{
  show("/admin/accounts");expect(await screen.findByRole("heading",{name:"Cuentas"})).toBeTruthy();
  expect(screen.getByRole("navigation",{name:"Navegación principal"})).toBeTruthy();
});
