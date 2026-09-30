export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(method: string, path: string, body?: BodyInit, json = true): Promise<T> {
  const url = path.startsWith("/api/") ? path : `/api${path}`;
  const headers = json && body !== undefined ? { "Content-Type": "application/json" } : undefined;
  const res = await fetch(url, { method, body, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      if (j?.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      // non-JSON error body: keep statusText
    }
    throw new ApiError(res.status, `${method} ${url} failed (${res.status}): ${detail}`);
  }
  return (await res.json()) as T;
}

export const apiGet = <T>(path: string) => request<T>("GET", path);

export const apiPost = <T>(path: string, body?: unknown) =>
  request<T>("POST", path, body === undefined ? undefined : JSON.stringify(body));

export const apiPut = <T>(path: string, body: unknown) =>
  request<T>("PUT", path, JSON.stringify(body));

export function apiUpload<T>(path: string, file: File): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  return request<T>("POST", path, form, false);
}
