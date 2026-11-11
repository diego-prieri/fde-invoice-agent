"""Generador de facturas sintéticas con ground truth.

Por cada comprobante escribe:
  <out>/inbox/inv_0001.html|pdf   documento que "llega por mail"
  <out>/truth/inv_0001.json       ground truth + problemas esperados

Los problemas (CUIT inválido, IVA que no cierra, duplicado) se inyectan a propósito
y se renderizan tal cual en el documento: el pipeline tiene que detectarlos.
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

from invoice_agent.common.cuit import corrupt_cuit, format_cuit, random_cuit
from invoice_agent.common.models import DISCRIMINA_IVA, TIPO_LABEL, Invoice, Item, Supplier

TIPOS = ["A", "B", "C", "NC_A"]
TIPO_PESOS = [50, 20, 20, 10]
DEFAULT_MIX = "html:0.4,scan:0.25,photo:0.25,fax:0.1"

PREFIJOS = ["Distribuidora", "Ferretería", "Servicios", "Logística", "Papelera", "Informática", "Gráfica", "Transportes"]
NOMBRES = ["Del Sur", "Los Andes", "Pampa", "Rioplatense", "Norte", "Mitre", "San Martín", "Belgrano"]
SUFIJOS = ["S.A.", "S.R.L.", "S.A.S."]
DESCRIPCIONES = [
    "Resma papel A4 75g", "Tóner impresora láser", "Servicio de flete", "Licencia de software anual",
    "Mantenimiento mensual", "Cable UTP cat6 (x100m)", "Tinta cartucho negro", "Hora de consultoría",
    "Caja de archivo", "Alquiler de equipo",
]

ANOMALIA_FRAC = 0.08  # fracción de comprobantes elegibles con cada anomalía
ANOMALIA_MIN = 4      # mínimo garantizado por tipo (con n chico, una tasa por sorteo puede dar 0 o 1)
DUPLICADO_FRAC = 0.04


def make_suppliers(rng: random.Random, n: int = 15) -> list[Supplier]:
    return [
        Supplier(
            razon_social=f"{rng.choice(PREFIJOS)} {rng.choice(NOMBRES)} {rng.choice(SUFIJOS)}",
            cuit=random_cuit(rng),
        )
        for _ in range(n)
    ]


def make_invoice(rng: random.Random, suppliers: list[Supplier]) -> Invoice:
    tipo = rng.choices(TIPOS, weights=TIPO_PESOS)[0]
    items = []
    for _ in range(rng.randint(1, 4)):
        rate = 0.0 if tipo == "C" else rng.choices([21.0, 10.5, 27.0], weights=[80, 15, 5])[0]
        items.append(
            Item(
                descripcion=rng.choice(DESCRIPCIONES),
                cantidad=rng.randint(1, 20),
                precio_unit=round(rng.uniform(500, 50000), 2),
                iva_pct=rate,
            )
        )
    lineas = [round(i.cantidad * i.precio_unit, 2) for i in items]
    neto = round(sum(lineas), 2)
    iva = round(sum(round(l * i.iva_pct / 100, 2) for l, i in zip(lineas, items)), 2)
    discrimina = tipo in DISCRIMINA_IVA
    return Invoice(
        tipo=tipo,
        punto_venta=rng.randint(1, 12),
        numero=rng.randint(1, 99999),
        fecha=date(2025, 1, 1) + timedelta(days=rng.randint(0, 668)),
        proveedor=rng.choice(suppliers),
        items=items,
        neto=neto if discrimina else None,
        iva=iva if discrimina else None,
        total=round(neto + iva, 2),
    )


def pick_anomalies(invoices: list[Invoice], rng: random.Random) -> dict[int, list[str]]:
    """Elige a qué comprobantes inyectar cada anomalía, con cantidades garantizadas (no por sorteo)."""
    def pick(eligible: list[int]) -> list[int]:
        k = min(len(eligible), max(ANOMALIA_MIN, round(ANOMALIA_FRAC * len(eligible))))
        return rng.sample(eligible, k)

    plan: dict[int, list[str]] = {}
    for i in pick(list(range(len(invoices)))):
        plan.setdefault(i, []).append("cuit_invalid")
    for i in pick([i for i, inv in enumerate(invoices) if inv.tipo in DISCRIMINA_IVA]):
        plan.setdefault(i, []).append("iva_mismatch")
    return plan


def apply_anomalies(inv: Invoice, issues: list[str], rng: random.Random) -> Invoice:
    if "cuit_invalid" in issues:
        inv = inv.model_copy(update={"proveedor": Supplier(
            razon_social=inv.proveedor.razon_social, cuit=corrupt_cuit(inv.proveedor.cuit, rng))})
    if "iva_mismatch" in issues:
        inv = inv.model_copy(update={"total": round(inv.total + rng.choice([100.0, -50.0, 1234.56]), 2)})
    return inv


def fmt_ar(x: float) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_us(x: float) -> str:
    return f"{x:,.2f}"


def render_html(inv: Invoice, style: int, fmt) -> str:
    cuit = format_cuit(inv.proveedor.cuit)
    pv, nro = f"{inv.punto_venta:04d}", f"{inv.numero:08d}"
    fecha_ar = inv.fecha.strftime("%d/%m/%Y")
    if style == 0:
        header = (f"<h1>{TIPO_LABEL[inv.tipo]}</h1><p>Punto de Venta: {pv} &nbsp; Comp. Nro: {nro}</p>"
                  f"<p>Fecha de Emisión: {fecha_ar}</p><p><b>{inv.proveedor.razon_social}</b><br>CUIT: {cuit}</p>")
    elif style == 1:
        header = (f"<p><b>{inv.proveedor.razon_social}</b> — C.U.I.T. {inv.proveedor.cuit}</p>"
                  f"<h2>Comprobante {inv.tipo.split('_')[-1]} Nº {pv}-{nro}</h2>"
                  f"<p>{TIPO_LABEL[inv.tipo].title()} · Emitida el {fecha_ar}</p>")
    else:
        header = (f"<h2>{inv.proveedor.razon_social}</h2><p>{TIPO_LABEL[inv.tipo].title()} | PV {inv.punto_venta} | "
                  f"N° {inv.numero} | {inv.fecha.isoformat()}</p><p>CUIT {inv.proveedor.cuit}</p>")
    rows = "".join(
        f"<tr><td>{i.descripcion}</td><td>{i.cantidad:g}</td><td>{fmt(i.precio_unit)}</td>"
        f"<td>{i.iva_pct:g}%</td><td>{fmt(i.cantidad * i.precio_unit)}</td></tr>"
        for i in inv.items
    )
    totales = ""
    if inv.neto is not None and inv.iva is not None:
        totales += f"<p>Importe Neto Gravado: $ {fmt(inv.neto)}</p><p>IVA: $ {fmt(inv.iva)}</p>"
    totales += f"<p><b>Importe Total: $ {fmt(inv.total)}</b></p>"
    css = ("body{font-family:sans-serif;max-width:720px;margin:24px auto}"
           "table{width:100%;border-collapse:collapse}td,th{border:1px solid #999;padding:4px}")
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{header}"
            f"<table><tr><th>Descripción</th><th>Cant.</th><th>P. Unit.</th><th>IVA</th><th>Subtotal</th></tr>"
            f"{rows}</table>{totales}</body></html>")


def write_document(html: str, dest: Path, as_pdf: bool) -> Path:
    if as_pdf:
        from weasyprint import HTML  # extra opcional: pip install '.[pdf]'

        out = dest.with_suffix(".pdf")
        HTML(string=html).write_pdf(out)
        return out
    out = dest.with_suffix(".html")
    out.write_text(html, encoding="utf-8")
    return out


def generate(n: int, out: Path, seed: int, as_pdf: bool, degrade: bool = False, mix: str = DEFAULT_MIX) -> dict[str, int]:
    """Genera `n` comprobantes (+ duplicados). Devuelve cuántos hay por perfil de degradación."""
    rng = random.Random(seed)
    inbox, truth = out / "inbox", out / "truth"
    inbox.mkdir(parents=True, exist_ok=True)
    truth.mkdir(parents=True, exist_ok=True)
    for old in [*inbox.glob("inv_*"), *truth.glob("inv_*")]:  # evita mezclar corridas con distintos formatos
        old.unlink()
    suppliers = make_suppliers(rng)

    base = [make_invoice(rng, suppliers) for _ in range(n)]
    plan = pick_anomalies(base, rng)
    generated: list[tuple[Invoice, list[str], int, str]] = []
    for i, inv in enumerate(base):
        issues = plan.get(i, [])
        generated.append((apply_anomalies(inv, issues, rng), issues, rng.randrange(3),
                          rng.choices(["ar", "us"], weights=[90, 10])[0]))

    # Duplicados: se agregan al final para que el original siempre se procese antes.
    k = min(n, max(ANOMALIA_MIN, round(DUPLICADO_FRAC * n)))
    for i in sorted(rng.sample(range(n), k)):
        inv, _, _, nf = generated[i]
        generated.append((inv, ["duplicate"], rng.randrange(3), nf))

    # La degradación usa su propio generador: no altera los datos base de una seed dada.
    deg_rng = random.Random(f"{seed}:degrade")
    names, weights = ("html",), (1.0,)
    if degrade:
        from invoice_agent.datagen.degrade import parse_mix

        names, weights = parse_mix(mix)  # type: ignore[assignment]

    counts: dict[str, int] = {}
    for idx, (inv, issues, style, nf) in enumerate(generated, start=1):
        stem = f"inv_{idx:04d}"
        fmt = fmt_ar if nf == "ar" else fmt_us
        profile = deg_rng.choices(names, weights=weights)[0]
        if profile == "html":
            write_document(render_html(inv, style, fmt), inbox / stem, as_pdf)
        else:
            from invoice_agent.datagen.degrade import render_image, save_degraded

            save_degraded(render_image(inv, style, fmt), profile, inbox / stem, deg_rng)
        counts[profile] = counts.get(profile, 0) + 1
        (truth / f"{stem}.json").write_text(
            json.dumps({"invoice": inv.model_dump(mode="json"), "expected_issues": issues,
                        "style": style, "number_format": nf, "degradation": profile},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
    return counts


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Genera facturas sintéticas + ground truth")
    p.add_argument("--n", type=int, default=100)
    p.add_argument("--out", type=Path, default=Path("data"))
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--pdf", action="store_true", help="renderizar los HTML limpios como PDF (requiere extra 'pdf')")
    p.add_argument("--degrade", action="store_true",
                   help="parte de los documentos salen como scan (PDF), foto (jpg) o fax (png); requiere extra 'images'")
    p.add_argument("--mix", default=DEFAULT_MIX, help=f"proporciones por perfil (default: {DEFAULT_MIX})")
    a = p.parse_args(argv)
    counts = generate(a.n, a.out, a.seed, a.pdf, a.degrade, a.mix)
    detail = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"{sum(counts.values())} comprobantes en {a.out}/inbox ({detail}); ground truth en {a.out}/truth")


if __name__ == "__main__":
    main()
