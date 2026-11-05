import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router";
import { App } from "./App";
import type { Account } from "./api/accounts";
import { sumMoney } from "./features/customer-banking/money";
import { intentStorageKey } from "./operationIntent";
import { navigateToLogin } from "./auth/navigation";
vi.mock("./auth/navigation", () => ({ navigateToLogin: vi.fn() }));
const actorId = "00000000-0000-4000-8000-000000000001";
const customerId = "00000000-0000-4000-8000-000000000002";
const account: Account = { id:"00000000-0000-4000-8000-000000000010", customer_id:customerId, account_number:"MI-CUENTA",product_type:"SAVINGS_ACCOUNT",currency:"CZK",status:"ACTIVE",opened_at:"2026-10-30",closed_at:null,created_at:"2026-10-30T10:00:00Z",updated_at:"2026-10-30T10:00:00Z" };
const destinationId = "00000000-0000-4000-8000-000000000011";
const transaction = { id:"00000000-0000-4000-8000-000000000020",transaction_type:"TRANSFER",status:"POSTED",amount:"10.00",currency:"CZK",description:null,effective_at:account.created_at,posted_at:account.created_at };
const movement = {id:"00000000-0000-4000-8000-000000000030",transaction_id:transaction.id,account_id:account.id,direction:"DEBIT",amount:"10.00",balance_after:"90.00",booked_at:account.created_at};
const json = (value: unknown,status=200) => new Response(JSON.stringify(value),{status});
const page = (items: unknown[], limit=20, offset=0, total=items.length) => ({items,pagination:{limit,offset,total_items:total,total_pages:Math.ceil(total/limit)}});
const fetchMock = vi.fn<typeof fetch>();
let role: "CUSTOMER"|"ADMIN", linked: boolean, permitted: boolean, authStatus: number, balance: string;
let override: ((path:string,init?:RequestInit)=>Response|Promise<Response>|undefined)|undefined;
beforeEach(() => {
  sessionStorage.clear(); vi.mocked(navigateToLogin).mockClear(); fetchMock.mockReset();
  role="CUSTOMER";linked=true;permitted=true;authStatus=200;balance="100.00";override=undefined;
  fetchMock.mockImplementation(async(input,init)=>{
    const url=new URL(String(input),"http://localhost"); const path=url.pathname;
    const changed=override?.(path,init); if(changed) return changed;
    if(path==="/auth/me") return json(authStatus===200?{id:actorId,email:"cliente@example.test",applications:permitted?[{application_code:"CBS",actor_type:role}]:[]}: {detail:"Not authenticated"},authStatus);
    if(path==="/api/me") return json({actor_id:actorId,application_code:"CBS",actor_type:role,customer_id:role==="CUSTOMER"&&linked?customerId:null,link_status:role==="ADMIN"?"NOT_APPLICABLE":linked?"LINKED":"PENDING_LINK"});
    if(path==="/auth/logout") return new Response(null,{status:204});
    if(path==="/api/me/accounts") return json(page([account],Number(url.searchParams.get("limit")??20)));
    if(path===`/api/me/accounts/${account.id}`) return json(account);
    if(path.endsWith("/balance")) return json({account_id:account.id,booked_balance:balance,available_balance:balance,updated_at:account.created_at});
    if(path.endsWith("/movements")) return json(page([movement]));
    if(path==="/api/me/transactions") return json(page([transaction],Number(url.searchParams.get("limit")??20)));
    if(path===`/api/me/transactions/${transaction.id}`) return json({...transaction,movements:page([movement])});
    if(path==="/api/me/transfers"){balance="90.00";return json(transaction,201);}
    if(path==="/api/accounts") return json(page([]));
    return json({detail:"Not found"},404);
  });
  vi.stubGlobal("fetch",fetchMock);
});
function Location(){const location=useLocation();return <output aria-label="Ruta actual">{location.pathname}</output>;}
function show(path="/"){return render(<MemoryRouter initialEntries={[path]}><App/><Location/></MemoryRouter>);}
it("restaura identidad CUSTOMER y sustituye DEMO por cuentas propias",async()=>{
 show();expect(await screen.findByRole("heading",{name:"Mis cuentas"})).toBeTruthy();
 expect(screen.getByLabelText("Ruta actual").textContent).toBe("/me");
 expect(screen.queryByLabelText("Cliente DEMO")).toBeNull();expect(screen.queryByText("Administración →")).toBeNull();
 expect(await screen.findByRole("link",{name:account.account_number})).toBeTruthy();
 expect(fetchMock.mock.calls.every(([path])=>!String(path).startsWith("/api/accounts"))).toBe(true);
});
it("redirige ADMIN a su administración existente",async()=>{role="ADMIN";show();expect(await screen.findByRole("heading",{name:"Cuentas"})).toBeTruthy();expect(screen.getByLabelText("Ruta actual").textContent).toBe("/accounts");});
it("no confunde falta de acceso CBS con sesión inexistente",async()=>{permitted=false;show();expect(await screen.findByRole("heading",{name:"Acceso denegado"})).toBeTruthy();expect(navigateToLogin).not.toHaveBeenCalled();expect(fetchMock.mock.calls.some(([path])=>path==="/api/me")).toBe(false);});
it("muestra PENDING_LINK sin solicitar datos bancarios",async()=>{linked=false;show();expect(await screen.findByText("Tu perfil bancario todavía no está vinculado a tu cuenta.")).toBeTruthy();expect(fetchMock.mock.calls.some(([path])=>String(path).startsWith("/api/me/"))).toBe(false);});
it("401 lleva al login y 503 ofrece reintento sin cerrar sesión",async()=>{authStatus=401;const view=show();await waitFor(()=>expect(navigateToLogin).toHaveBeenCalled());view.unmount();vi.mocked(navigateToLogin).mockClear();authStatus=503;show();expect(await screen.findByRole("heading",{name:"Servicio no disponible"})).toBeTruthy();expect(navigateToLogin).not.toHaveBeenCalled();});
it("403 de CBS muestra acceso denegado",async()=>{override=path=>path==="/api/me"?json({detail:"Forbidden"},403):undefined;show();expect(await screen.findByRole("heading",{name:"Acceso denegado"})).toBeTruthy();});
it("reutiliza saldo y movimientos desde las rutas personales",async()=>{show(`/me/accounts/${account.id}`);expect(await screen.findByRole("heading",{name:account.account_number})).toBeTruthy();expect(await screen.findByRole("heading",{name:"Balance actual"})).toBeTruthy();expect(await screen.findByText("90.00")).toBeTruthy();expect(screen.queryByRole("link",{name:"Depósito simulado"})).toBeNull();});
it("historial y detalle usan únicamente transacciones personales",async()=>{show("/me/transactions");const link=await screen.findByRole("link",{name:`Abrir transacción ${transaction.id}`});await userEvent.setup().click(link);expect(await screen.findByRole("heading",{name:"Detalle de operación"})).toBeTruthy();expect(await screen.findByText("Movimientos de tus cuentas")).toBeTruthy();expect(fetchMock.mock.calls.some(([path])=>String(path).startsWith("/api/transactions"))).toBe(false);});
it("transferencia reutiliza confirmación, clave estable y actualiza los datos",async()=>{
 show(`/me/transfers?account=${account.id}`);const user=userEvent.setup();
 await screen.findByLabelText("UUID de cuenta destino");await screen.findByDisplayValue("CZK");
 await user.type(screen.getByLabelText("UUID de cuenta destino"),destinationId);await user.type(screen.getByLabelText("Importe"),"10");
 await user.click(screen.getByRole("button",{name:"Revisar operación"}));
 await user.click(await screen.findByRole("button",{name:"Confirmar transferencia"}));
 expect(await screen.findByText("Operación registrada correctamente.")).toBeTruthy();
 const post=fetchMock.mock.calls.find(([path])=>path==="/api/me/transfers");expect(post?.[1]?.credentials).toBe("same-origin");
 expect(JSON.parse(String(post?.[1]?.body))).toEqual({source_account_id:account.id,destination_account_id:destinationId,amount:"10.00",currency:"CZK",description:null});
 expect(new Headers(post?.[1]?.headers).get("Idempotency-Key")).toBeTruthy();
 expect(fetchMock.mock.calls.some(([path])=>String(path).includes(destinationId))).toBe(false);
});
it("logout confirmado borra intención y datos privados",async()=>{show();await screen.findByRole("heading",{name:"Mis cuentas"});sessionStorage.setItem(intentStorageKey,"private-state");await userEvent.setup().click(screen.getByRole("button",{name:"Cerrar sesión"}));await waitFor(()=>expect(navigateToLogin).toHaveBeenCalled());expect(sessionStorage.getItem(intentStorageKey)).toBeNull();expect(screen.queryByText(account.account_number)).toBeNull();});
it("logout fallido mantiene identidad y muestra error",async()=>{override=path=>path==="/auth/logout"?json({},503):undefined;show();await screen.findByRole("heading",{name:"Mis cuentas"});await userEvent.setup().click(screen.getByRole("button",{name:"Cerrar sesión"}));expect(await screen.findByText(/No se ha podido confirmar el cierre/)).toBeTruthy();expect(screen.getByRole("heading",{name:"Mis cuentas"})).toBeTruthy();expect(navigateToLogin).not.toHaveBeenCalled();});
it("403 al leer una cuenta no se trata como logout",async()=>{override=path=>path===`/api/me/accounts/${account.id}`?json({detail:"Forbidden"},403):undefined;show(`/me/accounts/${account.id}`);expect(await screen.findByRole("alert")).toBeTruthy();expect(navigateToLogin).not.toHaveBeenCalled();});
it("moneda se suma sin coma flotante",()=>{expect(sumMoney(["0.10","0.20"])).toBe("0.30");});

it("un reintento de transferencia conserva cuerpo y clave tras un fallo de red",async()=>{
 let attempts=0;override=(path)=>{if(path==="/api/me/transfers"&&attempts++===0)return Promise.reject(new TypeError("network"));};
 show(`/me/transfers?account=${account.id}`);const user=userEvent.setup();await screen.findByLabelText("UUID de cuenta destino");await screen.findByDisplayValue("CZK");
 await user.type(screen.getByLabelText("UUID de cuenta destino"),destinationId);await user.type(screen.getByLabelText("Importe"),"10");
 await user.click(screen.getByRole("button",{name:"Revisar operación"}));await user.click(await screen.findByRole("button",{name:"Confirmar transferencia"}));
 await user.click(await screen.findByRole("button",{name:"Reintentar misma petición"}));await screen.findByText("Operación registrada correctamente.");
 const posts=fetchMock.mock.calls.filter(([path])=>path==="/api/me/transfers");expect(posts).toHaveLength(2);expect(posts[0]?.[1]?.body).toBe(posts[1]?.[1]?.body);expect(posts[0]?.[1]?.headers).toEqual(posts[1]?.[1]?.headers);
});
it("elimina datos e intención al recibir 401 después de entrar",async()=>{
 show();await screen.findByRole("link",{name:account.account_number});sessionStorage.setItem(intentStorageKey,"private-state");
 override=path=>path===`/api/me/accounts/${account.id}`?json({},401):undefined;
 await userEvent.setup().click(screen.getByRole("link",{name:account.account_number}));await waitFor(()=>expect(navigateToLogin).toHaveBeenCalled());
 expect(screen.queryByText(account.account_number)).toBeNull();expect(sessionStorage.getItem(intentStorageKey)).toBeNull();
});
it("no reutiliza la caché de otra identidad al restaurar una nueva sesión",async()=>{
 const view=show();await screen.findByRole("link",{name:account.account_number});view.unmount();
 override=(path)=>path==="/api/me/accounts"?json(page([])):undefined;
 show();expect(await screen.findByText("No tienes cuentas asociadas")).toBeTruthy();expect(screen.queryByText(account.account_number)).toBeNull();
});
it("un logout con respuesta fuera de contrato no se presenta como revocado",async()=>{
 override=path=>path==="/auth/logout"?json({message:"not-confirmed"},200):undefined;show();await screen.findByRole("heading",{name:"Mis cuentas"});
 await userEvent.setup().click(screen.getByRole("button",{name:"Cerrar sesión"}));expect(await screen.findByText(/No se ha podido confirmar el cierre/)).toBeTruthy();expect(navigateToLogin).not.toHaveBeenCalled();
});

async function fillProfile() {
 const user=userEvent.setup();await screen.findByRole("heading",{name:"Completa tu perfil bancario"});
 fireEvent.change(screen.getByLabelText("Fecha de nacimiento"),{target:{value:"1990-01-01"}});
 await user.selectOptions(screen.getByLabelText("Situación laboral"),"EMPLOYED");
 await user.type(screen.getByLabelText("Ingresos netos mensuales"),"2000");
 await user.type(screen.getByLabelText("Gastos mensuales de vivienda"),"500");
 await user.type(screen.getByLabelText("Pagos mensuales de deudas"),"0");
 await user.type(screen.getByLabelText("Otros gastos básicos mensuales"),"300");
 await user.selectOptions(screen.getByLabelText("Vivienda"),"RENT");await user.type(screen.getByLabelText("País de residencia (dos letras)"),"es");
 return user;
}
it("completar el perfil abre la cuenta y actualiza la identidad vinculada",async()=>{
 linked=false;override=(path)=>{if(path==="/api/me/onboarding"){linked=true;return json(account,201);}};
 show();const user=await fillProfile();await user.click(screen.getByRole("button",{name:"Crear perfil y abrir cuenta"}));
 expect(await screen.findByRole("heading",{name:"Mis cuentas"})).toBeTruthy();
 const post=fetchMock.mock.calls.find(([path])=>path==="/api/me/onboarding");const payload=JSON.parse(String(post?.[1]?.body));
 expect(payload.monthly_net_income).toBe("2000.00");expect(payload.country_of_residence).toBe("ES");
 expect(payload.actor_id).toBeUndefined();expect(payload.customer_id).toBeUndefined();expect(payload.email).toBeUndefined();
});
it("el alta incierta reintenta con el mismo perfil sin generar otra identidad",async()=>{
 linked=false;let calls=0;override=path=>{if(path==="/api/me/onboarding"){if(calls++===0)return json({},503);linked=true;return json(account,201);}};
 show();const user=await fillProfile();await user.click(screen.getByRole("button",{name:"Crear perfil y abrir cuenta"}));
 await user.click(await screen.findByRole("button",{name:"Reintentar alta"}));
 expect(await screen.findByRole("heading",{name:"Mis cuentas"})).toBeTruthy();
 const posts=fetchMock.mock.calls.filter(([path])=>path==="/api/me/onboarding");expect(posts).toHaveLength(2);expect(posts[0]?.[1]?.body).toBe(posts[1]?.[1]?.body);
});
it("un perfil rechazado permite corregir los datos",async()=>{
 linked=false;override=path=>path==="/api/me/onboarding"?json({detail:"Revisa los datos del perfil bancario."},422):undefined;
 show();const user=await fillProfile();await user.click(screen.getByRole("button",{name:"Crear perfil y abrir cuenta"}));
 expect(await screen.findByText("Revisa los datos del perfil bancario.")).toBeTruthy();expect(screen.getByRole("button",{name:"Crear perfil y abrir cuenta"})).toBeTruthy();
});
