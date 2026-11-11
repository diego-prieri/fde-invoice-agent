export type Tipo = "A" | "B" | "C" | "NC_A";

export interface Item {
  descripcion: string;
  cantidad: number;
  precio_unit: number;
  iva_pct: number;
}

export interface Invoice {
  tipo: Tipo;
  punto_venta: number;
  numero: number;
  fecha: string; // YYYY-MM-DD
  proveedor: { razon_social: string; cuit: string };
  items: Item[];
  neto: number | null;
  iva: number | null;
  total: number;
}

export type ReviewStatus = "review" | "approved" | "rejected";

export interface ReviewSummary {
  id: string;
  file: string;
  status: ReviewStatus;
  reasons: string[];
  confidence: number | null;
  proveedor: string;
  total: number;
}

export interface ReviewDetail {
  id: string;
  file: string;
  status: ReviewStatus;
  reasons: string[];
  confidence: number | null;
  invoice: Invoice;
  corrected_invoice?: Invoice;
  erp_id?: string;
  reject_reason?: string;
}

export const DISCRIMINA_IVA: Tipo[] = ["A", "NC_A"];

export const REASON_LABELS: Record<string, string> = {
  cuit_invalid: "CUIT inválido",
  iva_mismatch: "Neto + IVA ≠ total",
  missing_field: "Falta neto o IVA",
  future_date: "Fecha futura",
  non_positive_total: "Total no positivo",
  duplicate: "Comprobante duplicado",
  duplicate_in_erp: "Ya existe en el ERP",
  low_confidence: "Baja confianza del extractor",
};

export function reasonLabel(code: string): string {
  if (code.startsWith("erp_error:")) return `Error del ERP (${code.split(":")[1]})`;
  return REASON_LABELS[code] ?? code;
}
