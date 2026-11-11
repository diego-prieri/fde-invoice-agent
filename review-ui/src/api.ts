import type { Invoice, ReviewDetail, ReviewStatus, ReviewSummary } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public issues: string[] = [],
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!resp.ok) {
    let message = resp.statusText;
    let issues: string[] = [];
    try {
      const body = await resp.json();
      const d = body.detail;
      if (typeof d === "string") message = d;
      else if (d && typeof d === "object" && !Array.isArray(d)) {
        message = d.message ?? message;
        issues = d.issues ?? [];
      } else if (Array.isArray(d)) {
        message = "Datos inválidos: revisá los campos del formulario";
      }
    } catch {
      /* cuerpo no JSON */
    }
    throw new ApiError(resp.status, message, issues);
  }
  return resp.json() as Promise<T>;
}

const post = (path: string, body: unknown) =>
  request<never>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  list: (status: ReviewStatus) => request<ReviewSummary[]>(`/api/reviews?status=${status}`),
  get: (id: string) => request<ReviewDetail>(`/api/reviews/${id}`),
  documentUrl: (id: string) => `/api/reviews/${id}/document`,
  validate: (inv: Invoice) => post("/api/validate", inv) as Promise<{ issues: string[] }>,
  approve: (id: string, inv: Invoice) => post(`/api/reviews/${id}/approve`, inv) as Promise<{ erp_id: string }>,
  reject: (id: string, reason: string) => post(`/api/reviews/${id}/reject`, { reason }),
};
