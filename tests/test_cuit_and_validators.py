import random
from datetime import date

from invoice_agent.common.cuit import corrupt_cuit, is_valid, random_cuit
from invoice_agent.common.models import Invoice, Supplier
from invoice_agent.pipeline.validators import invoice_key, validate


def make(cuit: str, total: float = 121.0, tipo: str = "A", neto=100.0, iva=21.0) -> Invoice:
    return Invoice(tipo=tipo, punto_venta=1, numero=7, fecha=date(2025, 3, 1),
                   proveedor=Supplier(razon_social="X SA", cuit=cuit), neto=neto, iva=iva, total=total)


def test_known_valid_cuit():
    assert is_valid("30-50001091-2")  # AFIP
    assert not is_valid("30-50001091-3")
    assert not is_valid("123")


def test_random_and_corrupt_cuit():
    rng = random.Random(1)
    for _ in range(50):
        c = random_cuit(rng)
        assert is_valid(c)
        assert not is_valid(corrupt_cuit(c, rng))


def test_clean_invoice_has_no_issues():
    assert validate(make("30500010912"), set()) == []


def test_detects_issues():
    assert "cuit_invalid" in validate(make("30500010913"), set())
    assert "iva_mismatch" in validate(make("30500010912", total=999.0), set())
    assert "missing_field" in validate(make("30500010912", neto=None), set())


def test_b_invoice_does_not_need_iva_breakdown():
    assert validate(make("30500010912", tipo="B", neto=None, iva=None), set()) == []


def test_duplicate():
    inv = make("30500010912")
    seen = {invoice_key(inv)}
    assert "duplicate" in validate(inv, seen)
