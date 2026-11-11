"""Pipeline: inbox → extracción → validación → carga al ERP, o cola de revisión humana.

  python -m invoice_agent.pipeline.run --extractor simulated --erp-url http://localhost:8000

Salidas en --out:
  audit.jsonl      una línea por documento: qué se extrajo, qué se validó, qué se hizo
  review/<id>.json casos derivados a una persona (lo que consumiría la UI de revisión)
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from invoice_agent.pipeline.erp_client import DuplicateError, ErpClient, ErpError, MockErpClient
from invoice_agent.pipeline.extractor import Extractor, get_extractor
from invoice_agent.pipeline.validators import InvoiceKey, invoice_key, validate

SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg", ".html", ".txt"}


def process(path: Path, extractor: Extractor, erp: ErpClient, seen: set[InvoiceKey],
            threshold: float, out: Path) -> dict:
    record: dict = {"file": path.name}
    result = extractor.extract(path)
    inv = result.invoice
    issues = validate(inv, seen)
    seen.add(invoice_key(inv))
    record.update(confidence=result.confidence, issues=issues, invoice=inv.model_dump(mode="json"))

    reasons = list(issues)
    if result.confidence < threshold:
        reasons.append("low_confidence")

    if not reasons:
        try:
            if erp.find_supplier(inv.proveedor.cuit) is None:
                erp.create_supplier(inv.proveedor)
            key = hashlib.sha256(path.read_bytes()).hexdigest()
            record.update(status="loaded", erp_id=erp.create_invoice(inv, key))
            return record
        except DuplicateError:
            reasons.append("duplicate_in_erp")
        except ErpError as exc:
            reasons.append(f"erp_error:{exc.status}")

    record.update(status="review", reasons=reasons)
    review = out / "review"
    review.mkdir(parents=True, exist_ok=True)
    (review / f"{path.stem}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Procesa el inbox y carga al ERP")
    p.add_argument("--inbox", type=Path, default=Path("data/inbox"))
    p.add_argument("--truth", type=Path, default=Path("data/truth"), help="solo para --extractor simulated")
    p.add_argument("--extractor", choices=["simulated", "claude"], default="simulated")
    p.add_argument("--erp-url", default="http://localhost:8000")
    p.add_argument("--threshold", type=float, default=0.85, help="confianza mínima para carga automática")
    p.add_argument("--out", type=Path, default=Path("out"))
    a = p.parse_args(argv)

    a.out.mkdir(parents=True, exist_ok=True)
    extractor, erp = get_extractor(a.extractor, a.truth), MockErpClient(a.erp_url)
    seen: set[InvoiceKey] = set()
    stats: Counter = Counter()
    with (a.out / "audit.jsonl").open("w", encoding="utf-8") as audit:
        for path in sorted(a.inbox.iterdir()):
            if path.suffix.lower() not in SUPPORTED:
                continue
            rec = process(path, extractor, erp, seen, a.threshold, a.out)
            stats[rec["status"]] += 1
            audit.write(json.dumps(rec, ensure_ascii=False) + "\n")

    total = sum(stats.values())
    print(f"{total} documentos: {stats['loaded']} cargados automáticamente, {stats['review']} a revisión humana")
    if total:
        print(f"Tasa de automatización: {stats['loaded'] / total:.0%}")


if __name__ == "__main__":
    main()
