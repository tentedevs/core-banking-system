import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "./AuthProvider";

const actor = { id: "00000000-0000-4000-8000-000000000099", email: "customer@example.test", applications: [{ application_code: "CBS", actor_type: "CUSTOMER" }] };
const identity = { actor_id: actor.id, application_code: "CBS", actor_type: "CUSTOMER", customer_id: null, link_status: "PENDING_LINK" };
const json = (value: unknown) => new Response(JSON.stringify(value));
function Probe() {
  const auth = useAuth();
  return <><p>{auth.status}</p><p>{auth.error}</p><button onClick={() => void auth.restore()}>Reintentar</button></>;
}
afterEach(() => { vi.useRealTimers(); });

describe("session restoration deadline", () => {
  it.each(["/auth/me", "/api/me"])("leaves loading when %s stalls and permits retry", async (stalledPath) => {
    vi.useFakeTimers();
    let finish!: (response: Response) => void;
    const fetchMock = vi.fn<typeof fetch>().mockImplementation((path) => String(path) === stalledPath
      ? new Promise<Response>((resolve) => { finish = resolve; })
      : Promise.resolve(json(actor)));
    vi.stubGlobal("fetch", fetchMock);
    render(<AuthProvider><Probe /></AuthProvider>);
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText("loading")).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(screen.getByText("error")).toBeTruthy();
    expect(screen.getByText(/ha tardado demasiado/)).toBeTruthy();
    expect(fetchMock.mock.calls.at(-1)?.[1]?.signal?.aborted).toBe(true);

    // A late response must not restore an identity after the deadline.
    await act(async () => { finish(json(stalledPath === "/auth/me" ? actor : identity)); });
    expect(screen.getByText("error")).toBeTruthy();
    fetchMock.mockImplementation((path) => Promise.resolve(json(String(path) === "/auth/me" ? actor : identity)));
    await act(async () => { fireEvent.click(screen.getByText("Reintentar")); });
    expect(screen.getByText("ready")).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(screen.getByText("ready")).toBeTruthy();
  });
});
