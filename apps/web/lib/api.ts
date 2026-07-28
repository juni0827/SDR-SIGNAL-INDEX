export interface Envelope<T> {
  data: T;
  provenance: Array<Record<string, unknown>>;
  query: Record<string, unknown>;
  pagination: Record<string, unknown>;
  warnings: string[];
  generated_at_utc: string;
}

// Same-origin is the default so a forwarded/private Codespaces port needs no
// browser-visible API host or CORS exception. Deployments may still opt into a
// separate public API with NEXT_PUBLIC_API_URL.
export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";

export function csrfToken(): string | undefined {
  if (typeof document === "undefined") return undefined;
  return document.cookie.split("; ").find((value) => value.startsWith("signal_csrf="))?.split("=").slice(1).join("=");
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const form = init?.body instanceof FormData;
  const csrf = csrfToken();
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(!form ? {"content-type": "application/json"} : {}),
      ...(csrf ? {"x-csrf-token": csrf} : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) throw new Error(`api_error:${response.status}:${(await response.text()).slice(0, 300)}`);
  return response.json() as Promise<T>;
}
