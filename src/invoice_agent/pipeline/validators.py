"""Reglas de negocio aplicadas a lo extraído, antes de tocar el ERP."""
from __future__ import annotations

from datetime import date

from invoice_agent.common.cuit import digits, is_valid
from invoice_agent.common.models import DISCRIMINA_IVA, Invoice

InvoiceKey = tuple[str, str, int, int]


def invoice_key(inv: Invoice) -> InvoiceKey:
    return (digits(inv.proveedor.cuit), inv.tipo, inv.punto_venta, inv.numero)


def validate(inv: Invoice, seen: set[InvoiceKey]) -> list[str]:
    """Devuelve códigos de problema. El llamador agrega la clave a `seen` después."""
    issues: list[str] = []
    if not is_valid(inv.proveedor.cuit):
        issues.append("cuit_invalid")
    if inv.tipo in DISCRIMINA_IVA:
        if inv.neto is None or inv.iva is None:
            issues.append("missing_field")
        elif abs(inv.neto + inv.iva - inv.total) > 0.01:
            issues.append("iva_mismatch")
    if inv.fecha > date.today():
        issues.append("future_date")
    if inv.total <= 0:
        issues.append("non_positive_total")
    if invoice_key(inv) in seen:
        issues.append("duplicate")
    return issues
