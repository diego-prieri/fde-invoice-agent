"""El extractor de Claude y su uso en los evals, con un cliente falso (sin red ni API key)."""
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("anthropic")

from invoice_agent.datagen.generate import generate  # noqa: E402
from invoice_agent.evals.run_evals import evaluate  # noqa: E402
from invoice_agent.pipeline import extractor as ex  # noqa: E402


def make_extractor(tmp_path, truth_dir, fail_stems=()):
    """ClaudeExtractor real (construcción de pedido, caché, parseo) con el cliente HTTP reemplazado.
    El "modelo" falso devuelve el ground truth, como si acertara todo."""
    import os

    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-offline-test")
    x = ex.ClaudeExtractor(cache_dir=tmp_path / "cache")
    state = SimpleNamespace(calls=0, last=None, current_stem=None)

    def create(**kwargs):
        state.calls += 1
        state.last = kwargs
        if state.current_stem in fail_stems:
            raise RuntimeError("API caída")
        truth = json.loads((truth_dir / f"{state.current_stem}.json").read_text())
        block = SimpleNamespace(type="tool_use", input={"invoice": truth["invoice"], "confidence": 0.9})
        return SimpleNamespace(content=[block])

    x.client = SimpleNamespace(messages=SimpleNamespace(create=create))
    original = x.extract

    def extract(path):
        state.current_stem = path.stem
        return original(path)

    x.extract = extract  # type: ignore[method-assign]
    return x, state


def test_request_shape_and_cache(tmp_path):
    generate(8, tmp_path, seed=4, as_pdf=False, degrade=True, mix="scan:1,photo:1,fax:1,html:1")
    x, state = make_extractor(tmp_path, tmp_path / "truth")
    for path in sorted((tmp_path / "inbox").iterdir())[:4]:
        res = x.extract(path)
        assert res.confidence == 0.9
        kw = state.last
        assert kw["tool_choice"] == {"type": "tool", "name": ex.TOOL_NAME}
        assert kw["model"] == "claude-sonnet-5-5"
        kinds = {".pdf": "document", ".jpg": "image", ".png": "image", ".html": "text"}
        assert kw["messages"][0]["content"][0]["type"] == kinds[path.suffix]
    calls = state.calls
    x.extract(sorted((tmp_path / "inbox").iterdir())[0])  # segunda vez: sale de la caché
    assert state.calls == calls


def test_eval_counts_failures_instead_of_crashing(tmp_path):
    generate(10, tmp_path, seed=6, as_pdf=False)
    x, _ = make_extractor(tmp_path, tmp_path / "truth", fail_stems={"inv_0002"})
    report = evaluate(tmp_path / "inbox", tmp_path / "truth", x, None)
    assert [f["file"] for f in report["extraction_failures"]] == ["inv_0002.html"]
    assert "API caída" in report["extraction_failures"][0]["error"]
    assert report["fields"]["total"]["accuracy"] == pytest.approx((report["documents"] - 1) / report["documents"])
