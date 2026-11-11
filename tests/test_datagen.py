import json
from collections import Counter

import pytest

from invoice_agent.datagen.generate import ANOMALIA_MIN, generate


def issue_counts(out) -> Counter:
    c: Counter = Counter()
    for p in (out / "truth").glob("*.json"):
        c.update(json.loads(p.read_text())["expected_issues"])
    return c


@pytest.mark.parametrize("seed", [1, 7, 42, 123])
def test_every_anomaly_has_a_guaranteed_minimum(tmp_path, seed):
    generate(100, tmp_path, seed=seed, as_pdf=False)
    counts = issue_counts(tmp_path)
    for code in ("cuit_invalid", "iva_mismatch", "duplicate"):
        assert counts[code] >= ANOMALIA_MIN, (seed, dict(counts))


def test_small_datasets_do_not_crash(tmp_path):
    generate(3, tmp_path, seed=5, as_pdf=False)
    assert len(list((tmp_path / "inbox").iterdir())) >= 3


def test_duplicates_come_after_their_original(tmp_path):
    generate(50, tmp_path, seed=8, as_pdf=False)
    seen = set()
    for p in sorted((tmp_path / "truth").glob("*.json")):
        t = json.loads(p.read_text())
        inv = t["invoice"]
        key = (inv["proveedor"]["cuit"], inv["tipo"], inv["punto_venta"], inv["numero"])
        if "duplicate" in t["expected_issues"]:
            assert key in seen
        seen.add(key)
