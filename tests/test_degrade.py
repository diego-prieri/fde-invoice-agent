import json
import random
from datetime import date

import pytest

pytest.importorskip("PIL")

from fastapi.testclient import TestClient  # noqa: E402

from invoice_agent.common.models import Invoice, Supplier  # noqa: E402
from invoice_agent.datagen import degrade as D  # noqa: E402
from invoice_agent.datagen.generate import fmt_ar, generate  # noqa: E402
from invoice_agent.evals.run_evals import evaluate  # noqa: E402
from invoice_agent.pipeline.extractor import SimulatedExtractor  # noqa: E402
from invoice_agent.review_api.app import create_app  # noqa: E402


def sample() -> Invoice:
    return Invoice(tipo="A", punto_venta=1, numero=7, fecha=date(2025, 3, 1),
                   proveedor=Supplier(razon_social="Logística Ñandú S.A.", cuit="30500010912"),
                   neto=100.0, iva=21.0, total=121.0)


def test_parse_mix():
    assert D.parse_mix("html:1,scan:3") == (["html", "scan"], [1.0, 3.0])
    with pytest.raises(ValueError):
        D.parse_mix("polaroid:1")
    with pytest.raises(ValueError):
        D.parse_mix("html:0,scan:0")


def test_perspective_identity():
    quad = [(0, 0), (100, 0), (100, 50), (0, 50)]
    coeffs = D._perspective_coeffs(quad, quad)
    assert coeffs == pytest.approx([1, 0, 0, 0, 1, 0, 0, 0], abs=1e-9)


def test_profiles_write_expected_formats_and_are_deterministic(tmp_path):
    img = D.render_image(sample(), 0, fmt_ar)
    assert img.size == D.PAGE
    out = {p: D.save_degraded(img, p, tmp_path / p, random.Random(5)) for p in ("scan", "photo", "fax")}
    assert out["scan"].suffix == ".pdf" and out["scan"].read_bytes().startswith(b"%PDF")
    assert out["photo"].suffix == ".jpg" and out["fax"].suffix == ".png"
    again = D.save_degraded(img, "fax", tmp_path / "fax2", random.Random(5))
    assert again.read_bytes() == out["fax"].read_bytes()
    with pytest.raises(ValueError):
        D.save_degraded(img, "html", tmp_path / "x", random.Random(1))


def test_generate_degrade_mix_and_truth(tmp_path):
    counts = generate(30, tmp_path, seed=3, as_pdf=False, degrade=True, mix="scan:1,photo:1,fax:1")
    inbox = list((tmp_path / "inbox").iterdir())
    assert len(inbox) == sum(counts.values()) and "html" not in counts
    assert {p.suffix for p in inbox} <= {".pdf", ".jpg", ".png"}
    truths = [json.loads(p.read_text()) for p in (tmp_path / "truth").glob("*.json")]
    assert {t["degradation"] for t in truths} == set(counts)


def test_generate_without_degrade_keeps_base_data_for_a_seed(tmp_path):
    generate(20, tmp_path / "a", seed=9, as_pdf=False)
    generate(20, tmp_path / "b", seed=9, as_pdf=False, degrade=True)
    for p in (tmp_path / "a" / "truth").glob("*.json"):
        a, b = json.loads(p.read_text()), json.loads((tmp_path / "b" / "truth" / p.name).read_text())
        assert a["invoice"] == b["invoice"]  # degradar no cambia los datos


def test_regenerating_cleans_stale_files(tmp_path):
    generate(10, tmp_path, seed=1, as_pdf=False)
    generate(10, tmp_path, seed=1, as_pdf=False, degrade=True, mix="fax:1")
    assert not list((tmp_path / "inbox").glob("*.html"))


def test_eval_reports_by_degradation(tmp_path):
    generate(20, tmp_path, seed=2, as_pdf=False, degrade=True, mix="html:1,fax:1")
    report = evaluate(tmp_path / "inbox", tmp_path / "truth", SimulatedExtractor(tmp_path / "truth"), None)
    assert set(report["by_degradation"]) == {"html", "fax"}
    assert all(0 <= m["field_accuracy"] <= 1 for m in report["by_degradation"].values())


def test_review_api_sandboxes_html_but_not_pdf(tmp_path):
    out, inbox = tmp_path / "out", tmp_path / "inbox"
    (out / "review").mkdir(parents=True)
    inbox.mkdir()
    (inbox / "a.html").write_text("<p>x</p>")
    (inbox / "b.pdf").write_bytes(b"%PDF-1.4")
    for stem, f in (("a", "a.html"), ("b", "b.pdf")):
        rec = {"file": f, "status": "review", "invoice": sample().model_dump(mode="json")}
        (out / "review" / f"{stem}.json").write_text(json.dumps(rec))
    api = TestClient(create_app(out, inbox, erp=None))  # type: ignore[arg-type]
    assert api.get("/api/reviews/a/document").headers["content-security-policy"] == "sandbox"
    assert "content-security-policy" not in api.get("/api/reviews/b/document").headers
