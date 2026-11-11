import { useEffect, useState } from "react";
import { api, ApiError } from "./api";
import { DISCRIMINA_IVA, reasonLabel } from "./types";
import type { Invoice, Item, ReviewDetail, Tipo } from "./types";

interface Props {
  detail: ReviewDetail;
  onResolved: (message: string) => void;
}

const TIPOS: Tipo[] = ["A", "B", "C", "NC_A"];
const EMPTY_ITEM: Item = { descripcion: "", cantidad: 1, precio_unit: 0, iva_pct: 21 };

function Field({ label, changed, children }: { label: string; changed?: boolean; children: React.ReactNode }) {
  return (
    <label className={`field${changed ? " changed" : ""}`}>
      <span>{label}</span>
      {children}
    </label>
  );
}

function NumInput({
  value,
  onChange,
  disabled,
  step = "0.01",
}: {
  value: number | null;
  onChange: (v: number | null) => void;
  disabled?: boolean;
  step?: string;
}) {
  return (
    <input
      type="number"
      step={step}
      disabled={disabled}
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
    />
  );
}

export default function ReviewForm({ detail, onResolved }: Props) {
  const original = detail.invoice;
  const readOnly = detail.status !== "review";
  const [draft, setDraft] = useState<Invoice>(detail.corrected_invoice ?? original);
  const [issues, setIssues] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [rejectReason, setRejectReason] = useState("");

  // Validación en vivo contra el mismo código que usa el pipeline.
  useEffect(() => {
    if (readOnly) return;
    const t = setTimeout(() => {
      api
        .validate(draft)
        .then((r) => setIssues(r.issues))
        .catch(() => setIssues([]));
    }, 250);
    return () => clearTimeout(t);
  }, [draft, readOnly]);

  const discrimina = DISCRIMINA_IVA.includes(draft.tipo);
  const set = <K extends keyof Invoice>(key: K, value: Invoice[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const setProv = (key: "razon_social" | "cuit", value: string) =>
    setDraft((d) => ({ ...d, proveedor: { ...d.proveedor, [key]: value } }));
  const setItem = (i: number, patch: Partial<Item>) =>
    setDraft((d) => ({ ...d, items: d.items.map((it, idx) => (idx === i ? { ...it, ...patch } : it)) }));
  const changed = (a: unknown, b: unknown) => JSON.stringify(a) !== JSON.stringify(b);

  async function approve() {
    setBusy(true);
    setError(null);
    try {
      const body: Invoice = discrimina ? draft : { ...draft, neto: null, iva: null };
      const r = await api.approve(detail.id, body);
      onResolved(`Cargado en el ERP (id ${r.erp_id})`);
    } catch (e) {
      if (e instanceof ApiError) {
        setError(e.message);
        if (e.issues.length) setIssues(e.issues);
      } else setError("No se pudo conectar con la API de revisión");
    } finally {
      setBusy(false);
    }
  }

  async function reject() {
    setBusy(true);
    setError(null);
    try {
      await api.reject(detail.id, rejectReason.trim());
      onResolved("Caso rechazado");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo conectar con la API de revisión");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form" onSubmit={(e) => e.preventDefault()}>
      <div className="chips">
        {detail.reasons.map((r) => (
          <span key={r} className="chip warn">
            {reasonLabel(r)}
          </span>
        ))}
        {detail.confidence !== null && <span className="chip">Confianza {Math.round(detail.confidence * 100)}%</span>}
      </div>

      <div className="grid">
        <Field label="Tipo" changed={changed(draft.tipo, original.tipo)}>
          <select disabled={readOnly} value={draft.tipo} onChange={(e) => set("tipo", e.target.value as Tipo)}>
            {TIPOS.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </Field>
        <Field label="Fecha" changed={changed(draft.fecha, original.fecha)}>
          <input type="date" disabled={readOnly} value={draft.fecha} onChange={(e) => set("fecha", e.target.value)} />
        </Field>
        <Field label="Punto de venta" changed={changed(draft.punto_venta, original.punto_venta)}>
          <NumInput step="1" disabled={readOnly} value={draft.punto_venta} onChange={(v) => set("punto_venta", v ?? 0)} />
        </Field>
        <Field label="Número" changed={changed(draft.numero, original.numero)}>
          <NumInput step="1" disabled={readOnly} value={draft.numero} onChange={(v) => set("numero", v ?? 0)} />
        </Field>
        <Field label="Razón social" changed={changed(draft.proveedor.razon_social, original.proveedor.razon_social)}>
          <input disabled={readOnly} value={draft.proveedor.razon_social} onChange={(e) => setProv("razon_social", e.target.value)} />
        </Field>
        <Field label="CUIT" changed={changed(draft.proveedor.cuit, original.proveedor.cuit)}>
          <input
            disabled={readOnly}
            className={issues.includes("cuit_invalid") ? "invalid" : ""}
            value={draft.proveedor.cuit}
            onChange={(e) => setProv("cuit", e.target.value)}
          />
        </Field>
        {discrimina && (
          <>
            <Field label="Neto" changed={changed(draft.neto, original.neto)}>
              <NumInput disabled={readOnly} value={draft.neto} onChange={(v) => set("neto", v)} />
            </Field>
            <Field label="IVA" changed={changed(draft.iva, original.iva)}>
              <NumInput disabled={readOnly} value={draft.iva} onChange={(v) => set("iva", v)} />
            </Field>
          </>
        )}
        <Field label="Total" changed={changed(draft.total, original.total)}>
          <NumInput
            disabled={readOnly}
            value={draft.total}
            onChange={(v) => set("total", v ?? 0)}
          />
        </Field>
      </div>

      <h3>Ítems</h3>
      <table className="items">
        <thead>
          <tr>
            <th>Descripción</th>
            <th>Cant.</th>
            <th>P. unit.</th>
            <th>IVA %</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {draft.items.map((it, i) => (
            <tr key={i}>
              <td>
                <input disabled={readOnly} value={it.descripcion} onChange={(e) => setItem(i, { descripcion: e.target.value })} />
              </td>
              <td>
                <NumInput disabled={readOnly} value={it.cantidad} onChange={(v) => setItem(i, { cantidad: v ?? 0 })} />
              </td>
              <td>
                <NumInput disabled={readOnly} value={it.precio_unit} onChange={(v) => setItem(i, { precio_unit: v ?? 0 })} />
              </td>
              <td>
                <NumInput disabled={readOnly} value={it.iva_pct} onChange={(v) => setItem(i, { iva_pct: v ?? 0 })} />
              </td>
              <td>
                {!readOnly && (
                  <button type="button" className="ghost" aria-label="Quitar ítem" onClick={() => set("items", draft.items.filter((_, idx) => idx !== i))}>
                    ✕
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!readOnly && (
        <button type="button" className="ghost" onClick={() => set("items", [...draft.items, EMPTY_ITEM])}>
          + Agregar ítem
        </button>
      )}

      {readOnly ? (
        <p className="resolved">
          {detail.status === "approved"
            ? `Aprobado y cargado en el ERP (id ${detail.erp_id}).`
            : `Rechazado${detail.reject_reason ? `: ${detail.reject_reason}` : "."}`}
        </p>
      ) : (
        <div className="actions">
          {issues.length > 0 && (
            <div className="chips" role="status">
              {issues.map((r) => (
                <span key={r} className="chip bad">
                  {reasonLabel(r)}
                </span>
              ))}
            </div>
          )}
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {rejecting ? (
            <div className="row">
              <input
                autoFocus
                placeholder="Motivo del rechazo (opcional)"
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
              />
              <button type="button" className="danger" disabled={busy} onClick={reject}>
                Confirmar rechazo
              </button>
              <button type="button" className="ghost" onClick={() => setRejecting(false)}>
                Cancelar
              </button>
            </div>
          ) : (
            <div className="row">
              <button type="button" className="primary" disabled={busy || issues.length > 0} onClick={approve}>
                Aprobar y cargar
              </button>
              <button type="button" className="ghost" disabled={busy} onClick={() => setRejecting(true)}>
                Rechazar
              </button>
            </div>
          )}
        </div>
      )}
    </form>
  );
}
