import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import ReviewForm from "./ReviewForm";
import type { ReviewDetail, ReviewStatus, ReviewSummary } from "./types";
import { reasonLabel } from "./types";

const TABS: { status: ReviewStatus; label: string }[] = [
  { status: "review", label: "Pendientes" },
  { status: "approved", label: "Aprobados" },
  { status: "rejected", label: "Rechazados" },
];

function DocumentViewer({ id, file }: { id: string; file: string }) {
  const url = api.documentUrl(id);
  const [html, setHtml] = useState<string | null>(null);
  const isHtml = /\.(html?|txt)$/i.test(file);

  useEffect(() => {
    if (!isHtml) return;
    let cancelled = false;
    fetch(url)
      .then((r) => r.text())
      .then((t) => !cancelled && setHtml(t))
      .catch(() => !cancelled && setHtml("<p>No se pudo cargar el documento.</p>"));
    return () => {
      cancelled = true;
    };
  }, [url, isHtml]);

  if (/\.(png|jpe?g)$/i.test(file)) return <img className="doc" src={url} alt={`Comprobante ${file}`} />;
  if (!isHtml) return <iframe className="doc" src={url} title={`Comprobante ${file}`} />; // PDF
  // El documento es contenido no confiable. El sandbox sin `allow-scripts` impide ejecutar cualquier
  // JavaScript del documento, así que `allow-same-origin` es inocuo (solo permite leer el DOM propio).
  return <iframe className="doc" srcDoc={html ?? ""} title={`Comprobante ${file}`} sandbox="allow-same-origin" />;
}

export default function App() {
  const [tab, setTab] = useState<ReviewStatus>("review");
  const [items, setItems] = useState<ReviewSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(async (status: ReviewStatus, keep?: string | null) => {
    try {
      const list = await api.list(status);
      setItems(list);
      setLoadError(null);
      setSelected(keep && list.some((i) => i.id === keep) ? keep : (list[0]?.id ?? null));
    } catch {
      setLoadError("No se pudo conectar con la API de revisión (puerto 8100).");
      setItems([]);
    }
  }, []);

  useEffect(() => {
    void refresh(tab);
  }, [tab, refresh]);

  useEffect(() => {
    setDetail(null);
    if (!selected) return;
    let cancelled = false;
    api.get(selected).then((d) => !cancelled && setDetail(d)).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [selected]);

  function resolved(message: string) {
    setToast(message);
    setTimeout(() => setToast(null), 3500);
    void refresh(tab);
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <h1>Revisión</h1>
        <nav className="tabs" aria-label="Estado">
          {TABS.map((t) => (
            <button key={t.status} className={t.status === tab ? "tab active" : "tab"} onClick={() => setTab(t.status)}>
              {t.label}
            </button>
          ))}
        </nav>
        {loadError && <p className="error">{loadError}</p>}
        {!loadError && items.length === 0 && <p className="empty">No hay casos en esta lista.</p>}
        <ul className="list">
          {items.map((i) => (
            <li key={i.id}>
              <button className={i.id === selected ? "item active" : "item"} onClick={() => setSelected(i.id)}>
                <strong>{i.proveedor}</strong>
                <span className="muted">
                  {i.file} · $ {i.total.toLocaleString("es-AR", { minimumFractionDigits: 2 })}
                </span>
                {i.reasons.length > 0 && <span className="muted">{i.reasons.map(reasonLabel).join(" · ")}</span>}
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <main className="main">
        {toast && (
          <div className="toast" role="status">
            {toast}
          </div>
        )}
        {detail ? (
          <div className="split">
            <section className="pane">
              <h2>Documento original</h2>
              <DocumentViewer key={detail.id} id={detail.id} file={detail.file} />
              <p className="muted">
                {detail.file} ·{" "}
                <a href={api.documentUrl(detail.id)} target="_blank" rel="noreferrer">
                  Abrir en una pestaña nueva
                </a>
              </p>
            </section>
            <section className="pane">
              <h2>Datos extraídos</h2>
              <ReviewForm key={detail.id} detail={detail} onResolved={resolved} />
            </section>
          </div>
        ) : (
          <p className="empty">{selected ? "Cargando…" : "Elegí un caso de la lista."}</p>
        )}
      </main>
    </div>
  );
}
