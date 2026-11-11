"""Adaptador al sistema de gestión.

El pipeline solo conoce `ErpClient`. Para llevarlo a un cliente real se implementa
un adaptador nuevo (ver `RealErpClient`); nada más cambia.
"""
from __future__ import annotations

import time
from typing import Protocol

import httpx

from invoice_agent.common.cuit import digits
from invoice_agent.common.models import Invoice, Supplier


class ErpError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"{status}: {detail}")
        self.status, self.detail = status, detail


class DuplicateError(ErpError):
    pass


class ErpClient(Protocol):
    def find_supplier(self, cuit: str) -> Supplier | None: ...
    def create_supplier(self, supplier: Supplier) -> Supplier: ...
    def create_invoice(self, invoice: Invoice, idempotency_key: str) -> str: ...


class MockErpClient:
    """Habla con `invoice_agent.mock_erp`. Reintenta 5xx y errores de red con backoff exponencial."""

    def __init__(self, base_url: str = "http://localhost:8000", retries: int = 3,
                 backoff: float = 0.2, client: httpx.Client | None = None):
        self.client = client or httpx.Client(base_url=base_url, timeout=10)
        self.retries, self.backoff = retries, backoff

    def _request(self, method: str, path: str, **kw) -> httpx.Response:
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                resp = self.client.request(method, path, **kw)
                if resp.status_code < 500:
                    return resp
                last = ErpError(resp.status_code, resp.text)
            except httpx.TransportError as exc:
                last = exc
            if attempt < self.retries:
                time.sleep(self.backoff * 2**attempt)
        raise ErpError(503, f"ERP no disponible tras {self.retries + 1} intentos: {last}")

    @staticmethod
    def _raise(resp: httpx.Response) -> None:
        detail = resp.json().get("detail", resp.text) if resp.content else ""
        cls = DuplicateError if resp.status_code == 409 else ErpError
        raise cls(resp.status_code, str(detail))

    def find_supplier(self, cuit: str) -> Supplier | None:
        resp = self._request("GET", "/proveedores", params={"cuit": digits(cuit)})
        if resp.status_code != 200:
            self._raise(resp)
        rows = resp.json()
        return Supplier(**rows[0]) if rows else None

    def create_supplier(self, supplier: Supplier) -> Supplier:
        resp = self._request("POST", "/proveedores", json=supplier.model_dump())
        if resp.status_code != 201:
            self._raise(resp)
        return Supplier(**resp.json())

    def create_invoice(self, invoice: Invoice, idempotency_key: str) -> str:
        resp = self._request("POST", "/comprobantes", json=invoice.model_dump(mode="json"),
                             headers={"Idempotency-Key": idempotency_key})
        if resp.status_code not in (200, 201):
            self._raise(resp)
        return str(resp.json()["id"])


class RealErpClient:
    """Esqueleto del adaptador a un ERP real: no se usa en este repo (sin credenciales ni API)."""

    def find_supplier(self, cuit: str) -> Supplier | None:
        raise NotImplementedError

    def create_supplier(self, supplier: Supplier) -> Supplier:
        raise NotImplementedError

    def create_invoice(self, invoice: Invoice, idempotency_key: str) -> str:
        raise NotImplementedError
