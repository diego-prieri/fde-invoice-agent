"""Modelo de dominio compartido por datagen, mock ERP, pipeline y evals."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

TipoComprobante = Literal["A", "B", "C", "NC_A"]

TIPO_LABEL: dict[str, str] = {"A": "FACTURA A", "B": "FACTURA B", "C": "FACTURA C", "NC_A": "NOTA DE CRÉDITO A"}

# Tipos que discriminan neto e IVA en el comprobante.
DISCRIMINA_IVA: tuple[str, ...] = ("A", "NC_A")


class Supplier(BaseModel):
    razon_social: str
    cuit: str


class Item(BaseModel):
    descripcion: str
    cantidad: float
    precio_unit: float
    iva_pct: float


class Invoice(BaseModel):
    tipo: TipoComprobante
    punto_venta: int
    numero: int
    fecha: date
    proveedor: Supplier
    items: list[Item] = Field(default_factory=list)
    neto: float | None = Field(default=None, description="Solo si el tipo discrimina IVA (A, NC_A)")
    iva: float | None = Field(default=None, description="Solo si el tipo discrimina IVA (A, NC_A)")
    total: float


class ExtractionResult(BaseModel):
    invoice: Invoice
    confidence: float = Field(ge=0, le=1, description="Confianza global de la extracción, 0 a 1")
