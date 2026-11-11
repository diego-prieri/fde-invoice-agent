from datetime import date

import pytest
from fastapi.testclient import TestClient

from invoice_agent.common.models import Invoice, Supplier
from invoice_agent.mock_erp.app import create_app
from invoice_agent.pipeline.erp_client import DuplicateError, ErpError, MockErpClient

SUP = Supplier(razon_social="Proveedor SA", cuit="30500010912")


def invoice(numero: int = 1, cuit: str = SUP.cuit) -> Invoice:
    return Invoice(tipo="A", punto_venta=1, numero=numero, fecha=date(2025, 3, 1),
                   proveedor=Supplier(razon_social="Proveedor SA", cuit=cuit), neto=100.0, iva=21.0, total=121.0)


@pytest.fixture
def erp(tmp_path):
    return MockErpClient(client=TestClient(create_app(str(tmp_path / "erp.db"), fail_rate=0)))


def test_supplier_must_exist(erp):
    with pytest.raises(ErpError) as e:
        erp.create_invoice(invoice(), "k1")
    assert e.value.status == 422


def test_create_find_and_duplicate(erp):
    assert erp.find_supplier(SUP.cuit) is None
    erp.create_supplier(SUP)
    assert erp.find_supplier(SUP.cuit).razon_social == "Proveedor SA"
    erp.create_invoice(invoice(), "k1")
    with pytest.raises(DuplicateError):
        erp.create_invoice(invoice(), "k2")


def test_idempotency_key_returns_same_id(erp):
    erp.create_supplier(SUP)
    first = erp.create_invoice(invoice(), "same-key")
    assert erp.create_invoice(invoice(), "same-key") == first


def test_invalid_cuit_rejected(erp):
    with pytest.raises(ErpError) as e:
        erp.create_invoice(invoice(cuit="30500010913"), "k")
    assert e.value.status == 422


def test_retries_on_5xx_then_gives_up(tmp_path):
    flaky = MockErpClient(client=TestClient(create_app(str(tmp_path / "e.db"), fail_rate=1.0)),
                          retries=2, backoff=0)
    with pytest.raises(ErpError) as e:
        flaky.find_supplier(SUP.cuit)
    assert e.value.status == 503
