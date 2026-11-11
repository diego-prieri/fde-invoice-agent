"""API de la cola de revisión humana.

Lee los casos que el pipeline dejó en <out>/review/*.json y permite aprobarlos (con
correcciones) o rechazarlos. Aprobar valida de nuevo y carga el comprobante al ERP.

  uvicorn invoice_agent.review_api.app:app --port 8100
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from invoice_agent.common.models import Invoice
from invoice_agent.pipeline.erp_client import DuplicateError, ErpClient, ErpError, MockErpClient
from invoice_agent.pipeline.validators import validate

ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class Rejection(BaseModel):
    reason: str = ""


def create_app(out: Path | None = None, inbox: Path | None = None, erp: ErpClient | None = None) -> FastAPI:
    out = out or Path(os.environ.get("REVIEW_OUT", "out"))
    inbox = inbox or Path(os.environ.get("REVIEW_INBOX", "data/inbox"))
    erp = erp or MockErpClient(os.environ.get("ERP_URL", "http://localhost:8000"))
    review_dir = out / "review"
    app = FastAPI(title="Review API")

    def path_for(review_id: str) -> Path:
        if not ID_RE.match(review_id):
            raise HTTPException(400, "id inválido")
        p = review_dir / f"{review_id}.json"
        if not p.exists():
            raise HTTPException(404, "caso no encontrado")
        return p

    def load(review_id: str) -> dict:
        return {"id": review_id, **json.loads(path_for(review_id).read_text(encoding="utf-8"))}

    def save(review_id: str, record: dict) -> None:
        record = {k: v for k, v in record.items() if k != "id"}
        path_for(review_id).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def audit(entry: dict) -> None:
        out.mkdir(parents=True, exist_ok=True)
        with (out / "review_audit.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    @app.get("/api/reviews")
    def list_reviews(status: str = "review") -> list[dict]:
        items = []
        for p in sorted(review_dir.glob("*.json")) if review_dir.exists() else []:
            rec = json.loads(p.read_text(encoding="utf-8"))
            if status != "all" and rec.get("status") != status:
                continue
            inv = rec["invoice"]
            items.append({"id": p.stem, "file": rec["file"], "status": rec.get("status"),
                          "reasons": rec.get("reasons", []), "confidence": rec.get("confidence"),
                          "proveedor": inv["proveedor"]["razon_social"], "total": inv["total"]})
        return items

    @app.get("/api/reviews/{review_id}")
    def get_review(review_id: str) -> dict:
        return load(review_id)

    @app.get("/api/reviews/{review_id}/document")
    def get_document(review_id: str) -> FileResponse:
        doc = inbox / Path(load(review_id)["file"]).name
        if not doc.exists():
            raise HTTPException(404, "documento no encontrado")
        headers = {"X-Content-Type-Options": "nosniff"}
        # El HTML es contenido no confiable: se sirve sandboxeado. No se aplica a PDF/imágenes porque
        # Chrome bloquea el visor de PDF dentro de un documento con CSP sandbox.
        if doc.suffix.lower() in (".html", ".htm", ".txt"):
            headers["Content-Security-Policy"] = "sandbox"
        return FileResponse(doc, headers=headers)

    @app.post("/api/validate")
    def check(inv: Invoice) -> dict:
        return {"issues": validate(inv, set())}

    @app.post("/api/reviews/{review_id}/approve")
    def approve(review_id: str, inv: Invoice) -> dict:
        record = load(review_id)
        if record.get("status") != "review":
            raise HTTPException(409, f"el caso ya está {record.get('status')}")
        issues = validate(inv, set())
        if issues:
            raise HTTPException(422, {"message": "corregí los problemas antes de aprobar", "issues": issues})
        try:
            if erp.find_supplier(inv.proveedor.cuit) is None:
                erp.create_supplier(inv.proveedor)
            key = hashlib.sha256(f"review:{review_id}:{inv.model_dump_json()}".encode()).hexdigest()
            erp_id = erp.create_invoice(inv, key)
        except DuplicateError:
            raise HTTPException(409, {"message": "el ERP ya tiene este comprobante", "issues": ["duplicate"]})
        except ErpError as exc:
            raise HTTPException(502, {"message": f"error del ERP: {exc}", "issues": []})
        now = datetime.now(timezone.utc).isoformat()
        record.update(status="approved", erp_id=erp_id, resolved_at=now, corrected_invoice=inv.model_dump(mode="json"))
        save(review_id, record)
        audit({"id": review_id, "action": "approved", "erp_id": erp_id, "at": now,
               "changed": inv.model_dump(mode="json") != record["invoice"]})
        return {"status": "approved", "erp_id": erp_id}

    @app.post("/api/reviews/{review_id}/reject")
    def reject(review_id: str, body: Rejection) -> dict:
        record = load(review_id)
        if record.get("status") != "review":
            raise HTTPException(409, f"el caso ya está {record.get('status')}")
        now = datetime.now(timezone.utc).isoformat()
        record.update(status="rejected", resolved_at=now, reject_reason=body.reason)
        save(review_id, record)
        audit({"id": review_id, "action": "rejected", "reason": body.reason, "at": now})
        return {"status": "rejected"}

    return app


app = create_app()
