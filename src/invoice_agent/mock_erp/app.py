"""ERP simulado: reglas reales, datos falsos.

Rechaza CUIT inválido (422), proveedor inexistente (422) y comprobantes duplicados (409);
soporta Idempotency-Key e inyección de fallos (ERP_FAIL_RATE) para probar reintentos.

  uvicorn invoice_agent.mock_erp.app:app --port 8000
"""
from __future__ import annotations

import os
import random
import sqlite3

from fastapi import FastAPI, Header, HTTPException, Query

from invoice_agent.common.cuit import digits, is_valid
from invoice_agent.common.models import Invoice, Supplier

SCHEMA = """
CREATE TABLE IF NOT EXISTS proveedores (cuit TEXT PRIMARY KEY, razon_social TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS comprobantes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT, punto_venta INTEGER, numero INTEGER,
  cuit TEXT, payload TEXT NOT NULL, UNIQUE (cuit, tipo, punto_venta, numero));
CREATE TABLE IF NOT EXISTS idempotency (key TEXT PRIMARY KEY, comprobante_id INTEGER NOT NULL);
"""


def create_app(db_path: str | None = None, fail_rate: float | None = None) -> FastAPI:
    db_path = db_path or os.environ.get("ERP_DB", "mock_erp.db")
    fail_rate = float(os.environ.get("ERP_FAIL_RATE", "0")) if fail_rate is None else fail_rate
    app = FastAPI(title="Mock ERP")

    def db() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    with db() as conn:
        conn.executescript(SCHEMA)

    def maybe_fail() -> None:
        if fail_rate and random.random() < fail_rate:
            raise HTTPException(503, "servicio no disponible (fallo inyectado)")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/proveedores")
    def find_suppliers(cuit: str = Query(...)) -> list[dict]:
        maybe_fail()
        with db() as conn:
            rows = conn.execute("SELECT cuit, razon_social FROM proveedores WHERE cuit = ?", (digits(cuit),)).fetchall()
        return [dict(r) for r in rows]

    @app.post("/proveedores", status_code=201)
    def create_supplier(s: Supplier) -> dict:
        maybe_fail()
        if not is_valid(s.cuit):
            raise HTTPException(422, "cuit_invalido")
        with db() as conn:
            try:
                conn.execute("INSERT INTO proveedores VALUES (?, ?)", (digits(s.cuit), s.razon_social))
            except sqlite3.IntegrityError:
                raise HTTPException(409, "proveedor_existente")
        return {"cuit": digits(s.cuit), "razon_social": s.razon_social}

    @app.post("/comprobantes", status_code=201)
    def create_invoice(inv: Invoice, idempotency_key: str | None = Header(default=None)) -> dict:
        maybe_fail()
        cuit = digits(inv.proveedor.cuit)
        if not is_valid(cuit):
            raise HTTPException(422, "cuit_invalido")
        with db() as conn:
            if idempotency_key:
                prev = conn.execute("SELECT comprobante_id FROM idempotency WHERE key = ?", (idempotency_key,)).fetchone()
                if prev:
                    return {"id": prev["comprobante_id"], "status": "already_created"}
            if not conn.execute("SELECT 1 FROM proveedores WHERE cuit = ?", (cuit,)).fetchone():
                raise HTTPException(422, "proveedor_inexistente")
            try:
                cur = conn.execute(
                    "INSERT INTO comprobantes (tipo, punto_venta, numero, cuit, payload) VALUES (?, ?, ?, ?, ?)",
                    (inv.tipo, inv.punto_venta, inv.numero, cuit, inv.model_dump_json()),
                )
            except sqlite3.IntegrityError:
                raise HTTPException(409, "comprobante_duplicado")
            if idempotency_key:
                conn.execute("INSERT INTO idempotency VALUES (?, ?)", (idempotency_key, cur.lastrowid))
        return {"id": cur.lastrowid, "status": "created"}

    @app.get("/comprobantes")
    def list_invoices() -> list[dict]:
        with db() as conn:
            rows = conn.execute("SELECT id, tipo, punto_venta, numero, cuit FROM comprobantes ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    @app.get("/comprobantes/{invoice_id}")
    def get_invoice(invoice_id: int) -> dict:
        with db() as conn:
            row = conn.execute("SELECT id, payload FROM comprobantes WHERE id = ?", (invoice_id,)).fetchone()
        if not row:
            raise HTTPException(404, "no_encontrado")
        return {"id": row["id"], "comprobante": Invoice.model_validate_json(row["payload"]).model_dump(mode="json")}

    return app


app = create_app()
