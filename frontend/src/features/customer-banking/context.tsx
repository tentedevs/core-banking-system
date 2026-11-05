import { useQuery } from "@tanstack/react-query";
import { listCustomerAccounts } from "../../api/customer";
import type { Account } from "../../api/accounts";
import { useAuth } from "../../auth/AuthProvider";

export function useCustomerIdentity() {
  const auth = useAuth();
  return { customerId: auth.identity?.customer_id ?? null, actorId: auth.actor?.id ?? null };
}
export function useCustomerAccounts() {
  const { customerId, actorId } = useCustomerIdentity();
  return useQuery({
    queryKey: ["banking", actorId, customerId, "accounts"], enabled: !!customerId,
    queryFn: async ({ signal }) => {
      const rows = new Map<string, Account>();
      for (let offset = 0; ; offset += 100) {
        const page = await listCustomerAccounts(100, offset, signal);
        page.items.forEach(account => rows.set(account.id, account));
        if (offset + page.items.length >= page.pagination.total_items) return [...rows.values()];
        if (!page.items.length) throw new Error("Las cuentas cambiaron durante la consulta. Actualiza la página.");
      }
    },
  });
}
