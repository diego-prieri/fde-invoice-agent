"""Extractores: de un documento (PDF/imagen/HTML) a un `Invoice` con confianza.

- `ClaudeExtractor`: usa la API de Claude con tool use forzado (requiere extra 'claude' y ANTHROPIC_API_KEY).
- `SimulatedExtractor`: SIMULACIÓN para correr todo offline. Lee el ground truth y le inyecta ruido
  determinista. Sirve para desarrollar y probar el pipeline; sus métricas NO miden ningún modelo real.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import re
from datetime import timedelta
from pathlib import Path
from typing import Protocol

from invoice_agent.common.cuit import digits
from invoice_agent.common.models import ExtractionResult, Invoice


class Extractor(Protocol):
    def extract(self, path: Path) -> ExtractionResult: ...


SYSTEM = (
    "Sos un asistente que extrae datos de comprobantes de compra argentinos (facturas A/B/C y notas de crédito A). "
    "Registrá exactamente lo que dice el documento, sin corregir ni inferir: si un CUIT o un total parece "
    "inconsistente, copialo igual y bajá la confianza. Los importes pueden venir como 1.234,56 o 1,234.56. "
    "Las facturas B y C no discriminan IVA: dejá neto e iva en null. Para notas de crédito usá tipo NC_A."
)
TOOL_NAME = "registrar_comprobante"


class ClaudeExtractor:
    def __init__(self, model: str | None = None, cache_dir: Path = Path(".cache/extractions")):
        import anthropic  # extra opcional: pip install '.[claude]'

        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("INVOICE_AGENT_MODEL", "claude-sonnet-5-5")
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _content(self, path: Path) -> list[dict]:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            block = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                    "data": base64.b64encode(path.read_bytes()).decode()}}
        elif suffix in (".png", ".jpg", ".jpeg"):
            media = "image/png" if suffix == ".png" else "image/jpeg"
            block = {"type": "image", "source": {"type": "base64", "media_type": media,
                                                 "data": base64.b64encode(path.read_bytes()).decode()}}
        else:
            raw = path.read_text(encoding="utf-8", errors="replace")
            text = re.sub(r"\s+", " ", re.sub(r"<style.*?</style>|<[^>]+>", " ", raw, flags=re.S)).strip()
            block = {"type": "text", "text": text}
        return [block, {"type": "text", "text": "Extraé los datos de este comprobante."}]

    def extract(self, path: Path) -> ExtractionResult:
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        cached = self.cache_dir / f"{sha}.json"
        if cached.exists():
            return ExtractionResult.model_validate_json(cached.read_text())
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=SYSTEM,
            tools=[{"name": TOOL_NAME, "description": "Registra los datos extraídos del comprobante.",
                    "input_schema": ExtractionResult.model_json_schema()}],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=[{"role": "user", "content": self._content(path)}],
        )
        block = next(b for b in resp.content if b.type == "tool_use")
        result = ExtractionResult.model_validate(block.input)
        cached.write_text(result.model_dump_json(indent=2))
        return result


class SimulatedExtractor:
    def __init__(self, truth_dir: Path, error_rate: float = 0.04, seed: int = 42):
        self.truth_dir, self.error_rate, self.seed = truth_dir, error_rate, seed

    def extract(self, path: Path) -> ExtractionResult:
        truth = json.loads((self.truth_dir / f"{path.stem}.json").read_text(encoding="utf-8"))
        inv = Invoice.model_validate(truth["invoice"])
        rng = random.Random(f"{self.seed}:{path.stem}")
        corrupted = False
        update: dict = {}
        if rng.random() < self.error_rate:
            update["total"] = round(inv.total * rng.choice([10, 0.1]) if rng.random() < 0.5 else inv.total + 1000, 2)
            corrupted = True
        if rng.random() < self.error_rate:
            d = digits(inv.proveedor.cuit)
            i = rng.randrange(10)
            update["proveedor"] = inv.proveedor.model_copy(update={"cuit": d[:i] + str((int(d[i]) + 1) % 10) + d[i + 1:]})
            corrupted = True
        if rng.random() < self.error_rate:
            update["fecha"] = inv.fecha + timedelta(days=rng.choice([-1, 1, 30]))
            corrupted = True
        if rng.random() < self.error_rate:
            update["numero"] = inv.numero + rng.choice([-1, 1])
            corrupted = True
        confidence = round(rng.uniform(0.5, 0.7), 2) if corrupted and rng.random() < 0.7 else round(rng.uniform(0.9, 0.99), 2)
        return ExtractionResult(invoice=inv.model_copy(update=update), confidence=confidence)


def get_extractor(name: str, truth_dir: Path) -> Extractor:
    if name == "claude":
        return ClaudeExtractor()
    if name == "simulated":
        return SimulatedExtractor(truth_dir)
    raise ValueError(f"extractor desconocido: {name}")
