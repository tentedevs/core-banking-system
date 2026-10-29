import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation } from "react-router";
import { App } from "./App";
import type { Account } from "./api/accounts";

const account: Account = {
  id: "00000000-0000-4000-8000-000000000001", customer_id: "00000000-0000-4000-8000-000000000002",
  account_number: "000-CBS-0001", product_type: "SAVINGS_ACCOUNT", currency: "CZK", status: "ACTIVE",
  opened_at: "2026-10-29", closed_at: null, created_at: "2026-10-29T09:00:00Z", updated_at: "2026-10-29T09:00:00Z",
};
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const page = (items: Account[] = [account], total = items.length) => ({ items, pagination: { limit: 20, offset: 0, total_items: total, total_pages: Math.ceil(total / 20) } });
const fetchMock = vi.fn<typeof fetch>();
const clients: QueryClient[] = [];
beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => { clients.forEach((client) => client.clear()); clients.length = 0; });
function Location() { const location = useLocation(); return <output aria-label="Ruta actual">{location.pathname}</output>; }
function show(path = "/accounts") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /><Location /></MemoryRouter></QueryClientProvider>);
  return client;
}

describe("Frontend independiente de CBS", () => {
  it("muestra las cuentas del backend y solo navegación de CBS", async () => {
    fetchMock.mockResolvedValue(json(page())); show();
    expect(await screen.findByRole("link", { name: account.account_number })).toBeTruthy();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/accounts?limit=20&offset=0");
    const nav = screen.getByRole("navigation", { name: "Navegación principal" });
    expect(within(nav).getByRole("link", { name: /Cuentas/ })).toBeTruthy();
    expect(within(nav).queryByText("Evaluations")).toBeNull();
    expect(screen.getByText("Activa")).toBeTruthy();
  });
  it("maneja resultados vacíos sin inventar cuentas", async () => {
    fetchMock.mockResolvedValue(json(page([]))); show();
    expect(await screen.findByText("No hay cuentas en esta página")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });
  it("pagina y filtra por cliente con parámetros enviados al backend", async () => {
    fetchMock.mockResolvedValue(json(page([account], 41))); show();
    await screen.findByRole("table");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await waitFor(() => expect(fetchMock.mock.calls.at(-1)?.[0]).toBe("/api/accounts?limit=20&offset=20"));
    await user.type(screen.getByLabelText("Cliente"), account.customer_id);
    await user.click(screen.getByRole("button", { name: "Filtrar" }));
    await waitFor(() => expect(fetchMock.mock.calls.at(-1)?.[0]).toBe(`/api/accounts?limit=20&offset=0&customer_id=${account.customer_id}`));
  });
  it.each(["number", "id"])("busca por %s preservando la referencia", async (mode) => {
    fetchMock.mockImplementation((url) => Promise.resolve(json(String(url).includes("?") ? page([]) : account)));
    show(); const user = userEvent.setup(); await screen.findByText("No hay cuentas en esta página");
    await user.selectOptions(screen.getByLabelText("Buscar por"), mode);
    await user.type(screen.getByLabelText("Referencia de cuenta"), mode === "id" ? account.id : account.account_number);
    await user.click(screen.getByRole("button", { name: "Buscar" }));
    await screen.findByRole("heading", { name: account.account_number });
    const path = mode === "id" ? `/api/accounts/${account.id}` : `/api/accounts/by-number/${account.account_number}`;
    expect(fetchMock.mock.calls.some(([url]) => url === path)).toBe(true);
    expect(screen.getByLabelText("Ruta actual").textContent).toBe(`/accounts/${account.id}`);
  });
  it("crea una cuenta con solo customer_id y currency y abre su detalle", async () => {
    fetchMock.mockImplementation((_url, options) => Promise.resolve(json(account, options?.method === "POST" ? 201 : 200)));
    show("/accounts/new"); const user = userEvent.setup();
    await user.type(screen.getByLabelText("UUID del cliente"), account.customer_id);
    await user.click(screen.getByRole("button", { name: "Crear cuenta" }));
    await screen.findByRole("heading", { name: account.account_number });
    const post = fetchMock.mock.calls.find(([, options]) => options?.method === "POST");
    expect(post?.[0]).toBe("/api/accounts");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ customer_id: account.customer_id, currency: "CZK" });
    expect(screen.getByLabelText("Ruta actual").textContent).toBe(`/accounts/${account.id}`);
  });
  it("impide dobles envíos mientras se crea una cuenta", async () => {
    let complete!: (response: Response) => void;
    fetchMock.mockReturnValue(new Promise((resolve) => { complete = resolve; }));
    show("/accounts/new"); const user = userEvent.setup();
    await user.type(screen.getByLabelText("UUID del cliente"), account.customer_id);
    await user.click(screen.getByRole("button", { name: "Crear cuenta" }));
    const button = await screen.findByRole("button", { name: "Creando…" });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    await user.click(button); expect(fetchMock).toHaveBeenCalledTimes(1);
    complete(json({ detail: "Conflicto de número" }, 409));
    expect(await screen.findByRole("alert")).toBeTruthy();
  });
  it("bloquea y reactiva usando únicamente respuestas del backend", async () => {
    let current = account;
    fetchMock.mockImplementation((url, options) => {
      if (options?.method === "PATCH") current = { ...account, status: String(url).endsWith("/block") ? "BLOCKED" : "ACTIVE" };
      return Promise.resolve(json(current));
    });
    show(`/accounts/${account.id}`); const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Bloquear cuenta" }));
    await user.click(await screen.findByRole("button", { name: "Reactivar cuenta" }));
    expect(await screen.findByText("Activa")).toBeTruthy();
    expect(fetchMock.mock.calls.filter(([, options]) => options?.method === "PATCH").map(([url]) => url)).toEqual([
      `/api/accounts/${account.id}/block`, `/api/accounts/${account.id}/reactivate`,
    ]);
  });
  it("no ofrece transiciones para una cuenta cerrada", async () => {
    fetchMock.mockResolvedValue(json({ ...account, status: "CLOSED", closed_at: "2026-10-29" }));
    show(`/accounts/${account.id}`);
    expect(await screen.findByText("Cerrada")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Reactivar cuenta" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Bloquear cuenta" })).toBeNull();
  });
  it("recarga el estado real tras un 409 y muestra el error", async () => {
    let conflicted = false;
    fetchMock.mockImplementation((_url, options) => {
      if (options?.method === "PATCH") { conflicted = true; return Promise.resolve(json({ detail: "Estado modificado por otra operación" }, 409)); }
      return Promise.resolve(json({ ...account, status: conflicted ? "BLOCKED" : "ACTIVE" }));
    });
    show(`/accounts/${account.id}`);
    await userEvent.click(await screen.findByRole("button", { name: "Bloquear cuenta" }));
    expect(await screen.findByRole("button", { name: "Reactivar cuenta" })).toBeTruthy();
    expect((await screen.findByRole("alert")).textContent).toContain("Estado modificado");
  });
  it.each([404, 503, 500])("muestra un error HTTP %s sin respuestas ficticias", async (status) => {
    fetchMock.mockResolvedValue(json({ detail: "private SQL" }, status)); show(`/accounts/${account.id}`);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).not.toContain("private SQL");
    expect(screen.queryByRole("button", { name: "Bloquear cuenta" })).toBeNull();
  });
  it("explica los fallos de conexión con la API CBS", async () => {
    fetchMock.mockRejectedValue(new TypeError("Network failure")); show();
    expect((await screen.findByRole("alert")).textContent).toContain("puerto 8001");
  });
});
