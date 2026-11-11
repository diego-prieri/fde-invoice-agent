"""Utilidades de CUIT/CUIL argentino (11 dígitos, dígito verificador módulo 11)."""
from __future__ import annotations

import random

_WEIGHTS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)


def digits(value: str) -> str:
    return "".join(c for c in value if c.isdigit())


def check_digit(base10: str) -> int | None:
    """Dígito verificador para los primeros 10 dígitos; None si no existe (resto 10)."""
    total = sum(int(d) * w for d, w in zip(base10, _WEIGHTS))
    r = 11 - (total % 11)
    if r == 11:
        return 0
    if r == 10:
        return None
    return r


def is_valid(cuit: str) -> bool:
    d = digits(cuit)
    return len(d) == 11 and check_digit(d[:10]) == int(d[10])


def format_cuit(cuit: str) -> str:
    d = digits(cuit)
    return f"{d[:2]}-{d[2:10]}-{d[10]}"


def random_cuit(rng: random.Random) -> str:
    while True:
        base = rng.choice(("20", "27", "30", "33")) + f"{rng.randrange(10**8):08d}"
        dv = check_digit(base)
        if dv is not None:
            return base + str(dv)


def corrupt_cuit(cuit: str, rng: random.Random) -> str:
    """Devuelve un CUIT con el mismo formato pero dígito verificador inválido."""
    d = digits(cuit)
    while True:
        bad = d[:10] + str(rng.randrange(10))
        if not is_valid(bad):
            return bad
