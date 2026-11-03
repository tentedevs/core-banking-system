import { createContext, useContext, useState } from "react";
import type { ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { listAccounts } from "../../api/accounts";
import type { Account } from "../../api/accounts";

const DemoCustomerContext = createContext<{ customerId: string | null; selectCustomer: (id: string | null) => void } | null>(null);
export function DemoCustomerProvider({ children }: { children: ReactNode }) {
  const [customerId, setCustomerId] = useState<string | null>(null);
  const client = useQueryClient();
  function selectCustomer(id: string | null) {
    if (id === customerId) return;
    void client.cancelQueries({ queryKey: ["banking"] });
    client.removeQueries({ queryKey: ["banking"] });
    setCustomerId(id);
  }
  return <DemoCustomerContext.Provider value={{ customerId, selectCustomer }}>{children}</DemoCustomerContext.Provider>;
}
// Identity is presentation context only. A future session adapter replaces this hook;
// backend ownership checks are still required for actual authorization.
// eslint-disable-next-line react-refresh/only-export-components
export function useDemoCustomer() {
  const value = useContext(DemoCustomerContext);
  if (!value) throw new Error("Demo customer context is unavailable");
  return value;
}
// eslint-disable-next-line react-refresh/only-export-components
export function useCustomerAccounts() {
  const { customerId } = useDemoCustomer();
  return useQuery({
    queryKey: ["banking", customerId, "accounts"], enabled: !!customerId,
    queryFn: async ({ signal }) => {
      const rows = new Map<string, Account>();
      for (let offset = 0; ; offset += 100) {
        const page = await listAccounts(customerId!, 100, offset, signal);
        if (page.items.some(account => account.customer_id !== customerId)) throw new Error("Las cuentas recibidas no corresponden al contexto DEMO.");
        page.items.forEach(account => rows.set(account.id, account));
        if (offset + page.items.length >= page.pagination.total_items) return [...rows.values()];
        if (!page.items.length) throw new Error("El directorio cambió durante la consulta. Actualiza las cuentas.");
      }
    },
  });
}
