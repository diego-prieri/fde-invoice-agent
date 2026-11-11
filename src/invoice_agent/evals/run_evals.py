"""Evals: precisión por campo contra el ground truth y detección de problemas.

  python -m invoice_agent.evals.run_evals --extractor simulated
  python -m invoice_agent.evals.run_evals --extractor claude --limit 30

No toca el ERP: mide solo extracción + validaciones.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from invoice_agent.common.cuit import digits
from invoice_agent.common.models import Invoice
from invoice_agent.pipeline.extractor import get_extractor
from invoice_agent.pipeline.run import SUPPORTED
from invoice_agent.pipeline.validators import InvoiceKey, invoice_key, validate

FIELDS: dict[str, Any] = {
    "tipo": lambda i: i.tipo,
    "punto_venta": lambda i: i.punto_venta,
    "numero": lambda i: i.numero,
    "fecha": lambda i: i.fecha,
    "cuit": lambda i: digits(i.proveedor.cuit),
    "razon_social": lambda i: i.proveedor.razon_social.strip().casefold(),
    "neto": lambda i: i.neto,
    "iva": lambda i: i.iva,
    "total": lambda i: i.total,
}


def same(a: Any, b: Any) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return a is not None and b is not None and abs(a - b) < 0.01
    return a == b


def evaluate(inbox: Path, truth_dir: Path, extractor, limit: int | None) -> dict:
    hits: dict[str, int] = defaultdict(int)
    totals: dict[str, int] = defaultdict(int)
    prof_hits: dict[str, int] = defaultdict(int)  # por perfil de degradación: campos correctos / comparados
    prof_totals: dict[str, int] = defaultdict(int)
    prof_docs: dict[str, int] = defaultdict(int)
    prof_perfect: dict[str, int] = defaultdict(int)  # documentos con todos los campos correctos
    failures: list[dict] = []
    issue_tp: dict[str, int] = defaultdict(int)
    issue_fp: dict[str, int] = defaultdict(int)
    issue_fn: dict[str, int] = defaultdict(int)
    seen: set[InvoiceKey] = set()
    files = [p for p in sorted(inbox.iterdir()) if p.suffix.lower() in SUPPORTED]
    files = files[:limit] if limit else files

    for path in files:
        truth = json.loads((truth_dir / f"{path.stem}.json").read_text(encoding="utf-8"))
        expected_inv = Invoice.model_validate(truth["invoice"])
        profile = truth.get("degradation", "html")
        prof_docs[profile] += 1
        try:
            got: Invoice | None = extractor.extract(path).invoice
        except Exception as exc:  # una falla de API o una salida inválida del modelo cuenta como error del documento
            got = None
            failures.append({"file": path.name, "profile": profile, "error": f"{type(exc).__name__}: {exc}"[:300]})
        doc_ok = True
        for name, getter in FIELDS.items():
            want = getter(expected_inv)
            if want is None:
                continue
            ok = got is not None and same(getter(got), want)
            totals[name] += 1
            hits[name] += ok
            prof_totals[profile] += 1
            prof_hits[profile] += ok
            doc_ok &= ok
        prof_perfect[profile] += doc_ok
        if got is None:  # sin extracción no hay validación que medir
            continue
        found = set(validate(got, seen))
        seen.add(invoice_key(got))
        expected = set(truth["expected_issues"])
        for code in found | expected:
            if code in found and code in expected:
                issue_tp[code] += 1
            elif code in found:
                issue_fp[code] += 1
            else:
                issue_fn[code] += 1

    fields = {f: {"accuracy": hits[f] / totals[f], "n": totals[f]} for f in totals}
    issues = {}
    for code in sorted(set(issue_tp) | set(issue_fp) | set(issue_fn)):
        tp, fp, fn = issue_tp[code], issue_fp[code], issue_fn[code]
        issues[code] = {"tp": tp, "fp": fp, "fn": fn,
                        "precision": tp / (tp + fp) if tp + fp else None,
                        "recall": tp / (tp + fn) if tp + fn else None}
    by_degradation = {p: {"documents": prof_docs[p], "field_accuracy": prof_hits[p] / prof_totals[p],
                          "perfect_documents": prof_perfect[p] / prof_docs[p]} for p in sorted(prof_docs)}
    return {"documents": len(files), "fields": fields, "by_degradation": by_degradation, "issues": issues,
            "extraction_failures": failures}


def print_report(report: dict) -> None:
    print(f"\n{report['documents']} documentos\n\nPrecisión por campo")
    for name, m in report["fields"].items():
        print(f"  {name:<14} {m['accuracy']:>6.1%}  (n={m['n']})")
    print("\nPor calidad del documento (campos correctos / documentos 100% correctos)")
    for name, m in report["by_degradation"].items():
        print(f"  {name:<8} {m['field_accuracy']:>6.1%}  /  {m['perfect_documents']:>6.1%}  (n={m['documents']})")
    if report["extraction_failures"]:
        print(f"\nFallos de extracción: {len(report['extraction_failures'])} (cuentan como error; detalle en el JSON)")
        for f in report["extraction_failures"][:5]:
            print(f"  {f['file']} [{f['profile']}] {f['error']}")
    print("\nDetección de problemas")
    for code, m in report["issues"].items():
        p = "n/a" if m["precision"] is None else f"{m['precision']:.0%}"
        r = "n/a" if m["recall"] is None else f"{m['recall']:.0%}"
        print(f"  {code:<18} precision {p:>4}  recall {r:>4}  (tp={m['tp']} fp={m['fp']} fn={m['fn']})")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Evals de extracción y validaciones")
    p.add_argument("--inbox", type=Path, default=Path("data/inbox"))
    p.add_argument("--truth", type=Path, default=Path("data/truth"))
    p.add_argument("--extractor", choices=["simulated", "claude"], default="simulated")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--report", type=Path, default=Path("reports/eval.json"))
    a = p.parse_args(argv)

    report = evaluate(a.inbox, a.truth, get_extractor(a.extractor, a.truth), a.limit)
    report["extractor"] = a.extractor
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print_report(report)
    if a.extractor == "simulated":
        print("\nAviso: 'simulated' inyecta ruido sintético; estas métricas no miden ningún modelo real.")


if __name__ == "__main__":
    main()
