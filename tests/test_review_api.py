import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from invoice_agent.common.models import Invoice, Supplier
from invoice_agent.mock_erp.app import create_app as create_erp
from invoice_agent.pipeline.erp_client import MockErpClient
from invoice_agent.review_api.app import create_app

GOOD_CUIT, BAD_CUIT = "30500010912", "30500010913"


def invoice(cuit: str = BAD_CUIT, total: float = 121.0) -> dict:
    return Invoice(tipo="A", punto_venta=1, numero=5, fecha=date(2025, 3, 1),
                   proveedor=Supplier(razon_social="Proveedor SA", cuit=cuit),
                   neto=100.0, iva=21.0, total=total).model_dump(mode="json")


@pytest.fixture
def ctx(tmp_path):
    out, inbox = tmp_path / "out", tmp_path / "inbox"
    (out / "review").mkdir(parents=True)
    inbox.mkdir()
    (inbox / "inv_0001.html").write_text("<p>factura</p>")
    record = {"file": "inv_0001.html", "status": "review", "confidence": 0.6,
              "issues": ["cuit_invalid"], "reasons": ["cuit_invalid", "low_confidence"], "invoice": invoice()}
    (out / "review" / "inv_0001.json").write_text(json.dumps(record))
    erp = MockErpClient(client=TestClient(create_erp(str(tmp_path / "erp.db"), fail_rate=0)))
    return TestClient(create_app(out, inbox, erp)), out


def test_list_and_get(ctx):
    api, _ = ctx
    items = api.get("/api/reviews").json()
    assert [i["id"] for i in items] == ["inv_0001"] and items[0]["proveedor"] == "Proveedor SA"
    assert api.get("/api/reviews/inv_0001").json()["file"] == "inv_0001.html"
    assert api.get("/api/reviews/inv_0001/document").text == "<p>factura</p>"


def test_rejects_bad_ids(ctx):
    api, _ = ctx
    assert api.get("/api/reviews/nope").status_code == 404
    assert api.get("/api/reviews/..%2Fsecret").status_code in (400, 404)


def test_approve_requires_fixing_issues(ctx):
    api, _ = ctx
    resp = api.post("/api/reviews/inv_0001/approve", json=invoice(BAD_CUIT))
    assert resp.status_code == 422 and "cuit_invalid" in resp.json()["detail"]["issues"]


def test_approve_with_correction_loads_to_erp_and_resolves(ctx):
    api, out = ctx
    resp = api.post("/api/reviews/inv_0001/approve", json=invoice(GOOD_CUIT))
    assert resp.status_code == 200 and resp.json()["status"] == "approved"
    assert api.get("/api/reviews").json() == []
    assert api.get("/api/reviews?status=approved").json()[0]["id"] == "inv_0001"
    assert api.post("/api/reviews/inv_0001/approve", json=invoice(GOOD_CUIT)).status_code == 409
    assert json.loads((out / "review_audit.jsonl").read_text().splitlines()[0])["changed"] is True


def test_reject(ctx):
    api, _ = ctx
    assert api.post("/api/reviews/inv_0001/reject", json={"reason": "no es una factura"}).status_code == 200
    assert api.get("/api/reviews/inv_0001").json()["status"] == "rejected"


def test_validate_endpoint(ctx):
    api, _ = ctx
    assert api.post("/api/validate", json=invoice(GOOD_CUIT)).json() == {"issues": []}
    assert "iva_mismatch" in api.post("/api/validate", json=invoice(GOOD_CUIT, total=5.0)).json()["issues"]
