export class ApiError extends Error {
  constructor(message: string, public status: number | null) { super(message); }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try { response = await fetch(`/api${path}`, { ...init, credentials: "same-origin" }); }
  catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("No se puede conectar con CBS. Comprueba que su API está arrancada en el puerto 8001.", null);
  }
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event("cbs:unauthenticated"));
    if (response.status === 503) throw new ApiError("CBS o el servicio de autenticación no están disponibles. Inténtalo de nuevo.", 503);
    if (response.status >= 500) throw new ApiError("CBS no ha podido completar la operación. Inténtalo de nuevo.", response.status);
    let detail: unknown;
    try { detail = (await response.json() as { detail?: unknown }).detail; } catch { /* No JSON body. */ }
    const message = typeof detail === "string" ? detail : Array.isArray(detail)
      ? detail.map((item: { msg?: string }) => item.msg || "Entrada no válida").join(". ") : "La solicitud no es válida.";
    throw new ApiError(response.status === 404 ? ((path.startsWith("/accounts") || path.startsWith("/me/accounts") || path.endsWith("/transfers")) ? "Cuenta no encontrada." : "Transacción no encontrada.") : message, response.status);
  }
  try { return await response.json() as T; }
  catch { throw new ApiError("CBS ha devuelto una respuesta no válida.", response.status); }
}

