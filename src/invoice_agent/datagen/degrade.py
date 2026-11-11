"""Renderiza un comprobante como imagen y lo degrada como llegaría en la vida real.

Perfiles:
  html   documento digital limpio (no pasa por este módulo)
  scan   escáner de oficina: leve rotación, ruido, escala de grises  → PDF de solo imagen
  photo  foto con el celular: perspectiva, sombra, desenfoque, JPEG  → .jpg
  fax    baja resolución y binarizado con ruido                      → .png

Requiere el extra 'images' (Pillow + numpy). Todo es determinista dado el `random.Random` que se pase.
"""
from __future__ import annotations

import math
import os
import random
import sys
import unicodedata
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from invoice_agent.common.cuit import format_cuit
from invoice_agent.common.models import TIPO_LABEL, Invoice

PROFILES = ("html", "scan", "photo", "fax")
PAGE = (1240, 1754)  # A4 a 150 dpi


def parse_mix(spec: str) -> tuple[list[str], list[float]]:
    names, weights = [], []
    for part in spec.split(","):
        name, _, w = part.partition(":")
        if name not in PROFILES:
            raise ValueError(f"perfil desconocido: {name!r} (válidos: {', '.join(PROFILES)})")
        names.append(name)
        weights.append(float(w or 1))
    if not any(weights):
        raise ValueError("el mix no puede tener todos los pesos en cero")
    return names, weights


_FONT_CANDIDATES = {
    False: ["/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "C:/Windows/Fonts/arial.ttf"],
    True: ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
           "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"],
}
_warned = False


def _font(size: int, bold: bool = False) -> tuple[ImageFont.FreeTypeFont, bool]:
    """Devuelve (fuente, tiene_tildes). Hace falta una TTF con Latin-1: la fuente por defecto de Pillow
    dibuja cuadrados en lugar de í/ó/ñ, lo que falsearía el ground truth. INVOICE_AGENT_FONT la fuerza."""
    global _warned
    override = os.environ.get("INVOICE_AGENT_FONT")
    for path in ([override] if override else []) + _FONT_CANDIDATES[bold]:
        if path and Path(path).exists():
            return ImageFont.truetype(path, size), True
    if not _warned:
        print("aviso: no se encontró una fuente TTF con tildes (instalá DejaVu o definí INVOICE_AGENT_FONT); "
              "se dibujará sin acentos", file=sys.stderr)
        _warned = True
    return ImageFont.load_default(size=size), False


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def render_image(inv: Invoice, style: int, fmt) -> Image.Image:
    """Dibuja el comprobante con el mismo contenido y variantes de encabezado que la versión HTML."""
    w, h = PAGE
    img = Image.new("RGB", PAGE, "white")
    d = ImageDraw.Draw(img)
    m = 90

    def text(x: int, y: int, s: str, size: int = 30, bold: bool = False) -> None:
        font, accents = _font(size, bold)
        d.text((x, y), s if accents else _strip_accents(s), font=font, fill="black")

    pv, nro = f"{inv.punto_venta:04d}", f"{inv.numero:08d}"
    fecha_ar = inv.fecha.strftime("%d/%m/%Y")
    label = TIPO_LABEL[inv.tipo]
    if style == 0:
        lines = [(label, 52, True), (f"Punto de Venta: {pv}     Comp. Nro: {nro}", 30, False),
                 (f"Fecha de Emisión: {fecha_ar}", 30, False), (inv.proveedor.razon_social, 34, True),
                 (f"CUIT: {format_cuit(inv.proveedor.cuit)}", 30, False)]
    elif style == 1:
        lines = [(f"{inv.proveedor.razon_social} — C.U.I.T. {inv.proveedor.cuit}", 32, True),
                 (f"Comprobante {inv.tipo.split('_')[-1]} Nº {pv}-{nro}", 44, True),
                 (f"{label.title()} · Emitida el {fecha_ar}", 30, False)]
    else:
        lines = [(inv.proveedor.razon_social, 42, True),
                 (f"{label.title()} | PV {inv.punto_venta} | N° {inv.numero} | {inv.fecha.isoformat()}", 30, False),
                 (f"CUIT {inv.proveedor.cuit}", 30, False)]
    y = m
    for s, size, bold in lines:
        text(m, y, s, size, bold)
        y += int(size * 1.6)

    y += 30
    cols = [m, 520, 640, 820, 920, w - m]  # descripción | cant | p.unit | iva | subtotal
    heads = ["Descripción", "Cant.", "P. Unit.", "IVA", "Subtotal"]
    row_h = 58

    def row(y0: int, cells: list[str], bold: bool = False) -> None:
        for i, c in enumerate(cells):
            d.rectangle([cols[i], y0, cols[i + 1], y0 + row_h], outline="black", width=2)
            text(cols[i] + 10, y0 + 12, c, 28, bold)

    row(y, heads, bold=True)
    for it in inv.items:
        y += row_h
        row(y, [it.descripcion, f"{it.cantidad:g}", fmt(it.precio_unit), f"{it.iva_pct:g}%", fmt(it.cantidad * it.precio_unit)])
    y += row_h + 40
    if inv.neto is not None and inv.iva is not None:
        text(m, y, f"Importe Neto Gravado: $ {fmt(inv.neto)}", 30)
        y += 50
        text(m, y, f"IVA: $ {fmt(inv.iva)}", 30)
        y += 50
    text(m, y, f"Importe Total: $ {fmt(inv.total)}", 34, bold=True)
    return img


def _np_rng(rng: random.Random) -> np.random.Generator:
    return np.random.default_rng(rng.randrange(2**32))


def _add_noise(img: Image.Image, sigma: float, nrng: np.random.Generator) -> Image.Image:
    arr = np.asarray(img, dtype=np.float32)
    noise = nrng.normal(0, sigma, arr.shape[:2])
    arr = arr + (noise[..., None] if arr.ndim == 3 else noise)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def _perspective_coeffs(dst_quad: list[tuple[float, float]], src_quad: list[tuple[float, float]]) -> list[float]:
    """Coeficientes de PIL (salida → entrada) para llevar src_quad sobre dst_quad."""
    a, b = [], []
    for (x, y), (sx, sy) in zip(dst_quad, src_quad):
        a += [[x, y, 1, 0, 0, 0, -sx * x, -sx * y], [0, 0, 0, x, y, 1, -sy * x, -sy * y]]
        b += [sx, sy]
    return list(np.linalg.solve(np.array(a, dtype=float), np.array(b, dtype=float)))


def scan(img: Image.Image, rng: random.Random) -> Image.Image:
    nrng = _np_rng(rng)
    img = img.convert("L").rotate(rng.uniform(-1.2, 1.2), resample=Image.BICUBIC, expand=True, fillcolor=255)
    img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.4, 0.9)))
    arr = 255 - (255 - np.asarray(img, dtype=np.float32)) * rng.uniform(0.82, 0.95)  # tinta algo gris
    img = _add_noise(Image.fromarray(arr.astype(np.uint8)), rng.uniform(5, 10), nrng)
    draw = ImageDraw.Draw(img)
    for _ in range(rng.randint(60, 200)):  # motas de polvo
        x, y, r = rng.randrange(img.width), rng.randrange(img.height), rng.randint(1, 3)
        draw.ellipse([x, y, x + r, y + r], fill=rng.randint(60, 140))
    return img.convert("RGB")


def photo(img: Image.Image, rng: random.Random) -> Image.Image:
    nrng = _np_rng(rng)
    w, h = img.size
    pad = 160
    cw, ch = w + 2 * pad, h + 2 * pad
    ang = math.radians(rng.uniform(-4, 4))
    cx, cy = cw / 2, ch / 2
    jit = 0.06
    quad = []
    for x, y in [(pad, pad), (pad + w, pad), (pad + w, pad + h), (pad, pad + h)]:
        x += rng.uniform(-jit, jit) * w
        y += rng.uniform(-jit, jit) * h
        dx, dy = x - cx, y - cy
        quad.append((cx + dx * math.cos(ang) - dy * math.sin(ang), cy + dx * math.sin(ang) + dy * math.cos(ang)))
    desk = (rng.randint(70, 130), rng.randint(55, 100), rng.randint(40, 80))
    coeffs = _perspective_coeffs(quad, [(0, 0), (w, 0), (w, h), (0, h)])
    out = img.transform((cw, ch), Image.PERSPECTIVE, coeffs, Image.BICUBIC, fillcolor=desk)

    arr = np.asarray(out, dtype=np.float32)  # iluminación desigual
    gx = np.linspace(rng.uniform(0.7, 1.0), rng.uniform(0.85, 1.05), cw)[None, :]
    gy = np.linspace(rng.uniform(0.75, 1.0), rng.uniform(0.85, 1.05), ch)[:, None]
    out = Image.fromarray(np.clip(arr * (gx * gy)[..., None], 0, 255).astype(np.uint8))
    out = out.filter(ImageFilter.GaussianBlur(rng.uniform(0.8, 1.8)))
    out = _add_noise(out, rng.uniform(4, 9), nrng)
    target_w = 1400
    return out.resize((target_w, round(target_w * ch / cw)), Image.LANCZOS)


def fax(img: Image.Image, rng: random.Random) -> Image.Image:
    nrng = _np_rng(rng)
    scale = rng.uniform(0.45, 0.6)
    small = img.convert("L").resize((round(img.width * scale), round(img.height * scale)), Image.BILINEAR)
    small = small.rotate(rng.uniform(-0.8, 0.8), resample=Image.BILINEAR, fillcolor=255)
    arr = np.asarray(small, dtype=np.float32) + nrng.normal(0, 25, (small.height, small.width))
    return Image.fromarray(np.where(arr > 150, 255, 0).astype(np.uint8)).convert("RGB")


def save_degraded(img: Image.Image, profile: str, dest_stem: Path, rng: random.Random) -> Path:
    """Aplica el perfil y guarda; devuelve el archivo escrito (pdf / jpg / png)."""
    if profile == "scan":
        out = dest_stem.with_suffix(".pdf")
        scan(img, rng).save(out, "PDF", resolution=150.0)
    elif profile == "photo":
        out = dest_stem.with_suffix(".jpg")
        photo(img, rng).save(out, "JPEG", quality=rng.randint(35, 65))
    elif profile == "fax":
        out = dest_stem.with_suffix(".png")
        fax(img, rng).save(out, "PNG")
    else:
        raise ValueError(f"perfil no degradado: {profile}")
    return out
