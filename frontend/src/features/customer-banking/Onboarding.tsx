import { useRef, useState } from "react";
import type { FormEvent } from "react";

import { ApiError, request } from "../../api/http";
import type { Account } from "../../api/accounts";
import { SessionControls, useAuth } from "../../auth/AuthProvider";
import { ErrorNotice } from "../../components/Banking";

interface Profile {
  birth_date: string; employment_status: string; employment_months: number | null;
  monthly_net_income: string; monthly_housing_cost: string; monthly_debt_payments: string;
  monthly_basic_expenses: string; housing_status: string; country_of_residence: string; currency: string;
}
const moneyFields = [
  ["monthly_net_income", "Ingresos netos mensuales"],
  ["monthly_housing_cost", "Gastos mensuales de vivienda"],
  ["monthly_debt_payments", "Pagos mensuales de deudas"],
  ["monthly_basic_expenses", "Otros gastos básicos mensuales"],
] as const;
function amount(value: FormDataEntryValue | null): string {
  const text = String(value ?? "").trim();
  if (!/^(0|[1-9]\d{0,15})(?:\.\d{1,2})?$/.test(text)) throw new Error("Introduce importes no negativos, con punto y hasta dos decimales.");
  const [whole, fraction = ""] = text.split(".");
  return `${whole}.${fraction.padEnd(2, "0")}`;
}
export function Onboarding() {
  const auth = useAuth(); const sending = useRef(false);
  const [prepared, setPrepared] = useState<Profile | null>(null);
  const [busy, setBusy] = useState(false); const [error, setError] = useState<Error | null>(null);
  async function send(profile: Profile) {
    if (sending.current || !auth.actor || !auth.isCurrentSession(auth.actor.id, auth.version)) return;
    sending.current = true; setBusy(true); setError(null);
    try {
      const account = await request<Account>("/me/onboarding", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(profile) });
      if (!auth.isCurrentSession(auth.actor.id, auth.version)) return;
      if (!account?.id || account.currency !== profile.currency || account.product_type !== "SAVINGS_ACCOUNT") throw new Error("No se puede confirmar la apertura. Reintenta con los mismos datos.");
      await auth.restore();
    } catch (cause) {
      if (!auth.isCurrentSession(auth.actor.id, auth.version)) return;
      setError(cause instanceof Error ? cause : new Error("No se ha podido completar el alta."));
      // Validation failures confirm that no Customer was provisioned. Network
      // uncertainty retains the exact payload; never invent a second request.
      if (cause instanceof ApiError && cause.status === 422) setPrepared(null);
    } finally { sending.current = false; setBusy(false); }
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(null);
    try {
      const form = new FormData(event.currentTarget);
      const months = String(form.get("employment_months") ?? "");
      const profile: Profile = {
        birth_date: String(form.get("birth_date")), employment_status: String(form.get("employment_status")),
        employment_months: months === "" ? null : Number(months),
        monthly_net_income: amount(form.get("monthly_net_income")), monthly_housing_cost: amount(form.get("monthly_housing_cost")),
        monthly_debt_payments: amount(form.get("monthly_debt_payments")), monthly_basic_expenses: amount(form.get("monthly_basic_expenses")),
        housing_status: String(form.get("housing_status")), country_of_residence: String(form.get("country_of_residence")).trim().toUpperCase(),
        currency: String(form.get("currency")).trim().toUpperCase(),
      };
      setPrepared(profile); void send(profile);
    } catch (cause) { setError(cause instanceof Error ? cause : new Error("Revisa los datos.")); }
  }
  return <div className="banking-shell"><header className="banking-header"><strong>CBS · Alta bancaria</strong><SessionControls /></header><main className="banking-main"><section className="panel form-panel"><h1>Completa tu perfil bancario</h1><p>Tu perfil bancario todavía no está vinculado a tu cuenta.</p><p>Con estos datos crearemos tu perfil de cliente y abriremos tu primera cuenta de ahorro, con saldo inicial cero.</p>{error && <ErrorNotice error={error} />}{prepared ? <section><h2>{busy ? "Preparando tu cuenta…" : "Alta pendiente de confirmar"}</h2><p>{busy ? "Espera a que termine la apertura." : "Reintenta con los mismos datos. Si la solicitud anterior llegó al banco, se recuperará el mismo cliente y la misma cuenta."}</p><button className="button primary" disabled={busy} onClick={() => void send(prepared)}>Reintentar alta</button><button className="button secondary" disabled={busy} onClick={() => void auth.restore()}>Comprobar estado</button></section> : <form className="create-form" onSubmit={submit}>
    <label htmlFor="birth-date">Fecha de nacimiento</label><input id="birth-date" name="birth_date" type="date" max={new Date().toISOString().slice(0,10)} required />
    <label htmlFor="employment-status">Situación laboral</label><select id="employment-status" name="employment_status" required defaultValue=""><option value="" disabled>Selecciona tu situación</option><option value="EMPLOYED">Empleado</option><option value="SELF_EMPLOYED">Autónomo</option><option value="UNEMPLOYED">Desempleado</option><option value="RETIRED">Jubilado</option><option value="STUDENT">Estudiante</option></select>
    <label htmlFor="employment-months">Meses de antigüedad laboral (opcional)</label><input id="employment-months" name="employment_months" type="number" min="0" step="1" />
    {moneyFields.map(([name,label])=><div key={name}><label htmlFor={name}>{label}</label><input id={name} name={name} inputMode="decimal" required placeholder="0.00" /></div>)}
    <label htmlFor="housing-status">Vivienda</label><select id="housing-status" name="housing_status" required defaultValue=""><option value="" disabled>Selecciona tu vivienda</option><option value="OWNER">En propiedad</option><option value="MORTGAGE">Con hipoteca</option><option value="RENT">Alquiler</option><option value="OTHER">Otra situación</option></select>
    <label htmlFor="residence-country">País de residencia (dos letras)</label><input id="residence-country" name="country_of_residence" required pattern="[A-Za-z]{2}" maxLength={2} placeholder="ES" />
    <label htmlFor="account-currency">Moneda de la cuenta</label><select id="account-currency" name="currency" required><option value="CZK">CZK</option><option value="EUR">EUR</option><option value="USD">USD</option></select>
    <p>Al continuar confirmas los datos y solicitas la apertura de la cuenta de ahorro.</p><button className="button primary" type="submit">Crear perfil y abrir cuenta</button>
  </form>}</section></main></div>;
}
