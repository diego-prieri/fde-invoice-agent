# Invoice Agent

Agente que toma comprobantes de compra (facturas A/B/C y notas de crédito), extrae los datos con un LLM, los valida con reglas de negocio argentinas y los carga en un sistema de gestión. Lo dudoso va a una cola de revisión humana con una UI. Hay evals contra un ground truth para medir qué tan bien funciona.

Es un proyecto de portfolio que simula el trabajo de un **Forward Deployed Engineer**: entrar a un cliente con un dolor real (cargar facturas a mano), integrar sistemas, poner el modelo en producción con controles y medir el resultado.

> **Alcance honesto:** los datos son sintéticos y el ERP es un mock con reglas reales. El único punto de integración real es el LLM (opcional). Para llevarlo a un cliente real se implementa un adaptador nuevo (`ErpClient`), nada más.
>
> **Todavía no hay métricas de un modelo real.** Las cifras que imprime `--extractor simulated` salen de ruido sintético y no miden nada. Ver [Estado del proyecto](#estado-del-proyecto).

## Estado del proyecto

### Hecho
- [x] **Generador de datos** con ground truth: 3 layouts de factura, formatos de número argentino/inglés, CUIT con dígito verificador válido.
- [x] **Anomalías inyectadas** en cantidades garantizadas: CUIT inválido, IVA que no cierra y duplicados.
- [x] **Documentos degradados** (`--degrade`): scan en PDF, foto con perspectiva y sombra, fax de baja resolución.
- [x] **ERP simulado** (FastAPI + SQLite): rechaza CUIT inválido, proveedor inexistente y duplicados; soporta `Idempotency-Key` y fallos 503 inyectados.
- [x] **Pipeline** con adaptadores (`Extractor`, `ErpClient`), reintentos con backoff, validaciones deterministas y log de auditoría.
- [x] **Extractor con Claude** (tool use forzado, soporta PDF, imagen y HTML, con caché por hash de archivo).
- [x] **Evals:** precisión por campo, por calidad de documento y precisión/recall de cada problema detectado; los fallos de la API cuentan como error del documento.
- [x] **UI de revisión** (React + API en FastAPI): documento original junto a lo extraído, campos corregidos resaltados, validación en vivo, aprobar (carga al ERP) o rechazar, con auditoría.
- [x] **Tests:** 33 (CUIT, validaciones, ERP, API de revisión, degradación, generador, extractor con cliente falso).

### Verificado y no verificado
| | Estado |
|---|---|
| Pipeline completo contra el ERP simulado | Verificado de punta a punta |
| UI: listar, corregir y aprobar un caso real | Verificado en el navegador |
| UI: rechazar | Solo con tests de la API |
| Visor de PDF en la UI | No verificado: el navegador de pruebas no tenía visor de PDF (el servidor lo entrega bien) |
| `ClaudeExtractor` contra la API real | **No probado.** Solo con un cliente falso: construcción de pedidos, parseo y caché |
| `docker compose` | No probado |

### Pendiente (en orden)
1. **Medir con Claude real** sobre ~100 comprobantes degradados y documentar dónde falla y por qué. Es lo que más pesa en el portfolio y lo que falta para tener cifras reales.
2. **Ajustar el prompt y el umbral de confianza** con esos resultados (hoy `--threshold` es un valor por defecto sin calibrar).
3. **Discovery real:** entrevistar a 1–2 personas que carguen facturas a mano y completar el caso de negocio con sus números (horas por semana, errores, tipos de comprobante problemáticos).
4. **Degradación más dura:** varias facturas por página, sellos o firmas encima, hojas dobladas, fotos con el dedo en el borde.
5. **Ingesta real:** hoy se lee una carpeta; agregar un webhook o Gmail API.
6. **Más reglas:** proveedor desconocido que requiere aprobación (hoy se crea solo), coherencia de ítems vs. neto, alícuotas válidas.
7. **Pulir la UI:** atajos de teclado, resaltar en el documento dónde está cada campo, filtros por motivo.
8. **Video demo de 3 minutos** y un post técnico con los números reales.

## Caso de negocio
- **Problema:** una pyme recibe facturas por mail y las carga a mano. Horas por semana, errores de CUIT e IVA, atraso en el cierre.
- **Solución:** ingesta → extracción → validación → carga automática o revisión humana.
- **Resultado:** _pendiente de medir_ (automatización, precisión por campo y por calidad de documento, horas ahorradas).

## Arquitectura

```
data/inbox/*.html|pdf|jpg|png ─► Extractor ─► validate() ─┬─► ErpClient ─► ERP (mock)
                                 (Claude |      reglas    │     reintentos + idempotencia
                                  simulado)     de negocio└─► out/review/*.json ─► UI de revisión
                                          └──────── out/audit.jsonl (trazabilidad)
```

| Módulo | Qué hace |
|---|---|
| `datagen` | Genera facturas sintéticas con ground truth, anomalías inyectadas y degradación opcional |
| `mock_erp` | ERP simulado con reglas reales, idempotencia y fallos inyectados |
| `pipeline` | `Extractor` (Claude o simulado), `validate()`, `ErpClient` con reintentos, runner con auditoría |
| `review_api` | API de la cola de revisión: listar, ver documento, validar, aprobar y rechazar |
| `evals` | Precisión por campo y por calidad de documento, precisión/recall de problemas |
| `review-ui` | UI en React + TypeScript + Vite para la revisión humana |

Decisiones de diseño:
- **Adaptadores** (`ErpClient`, `Extractor`) detrás de `Protocol`: el pipeline no sabe qué hay del otro lado.
- **El LLM extrae, el código valida.** El prompt le pide copiar sin corregir; las reglas (CUIT, IVA, duplicados) son código determinista y la UI usa el mismo código para validar en vivo.
- **Human-in-the-loop** por umbral de confianza (`--threshold`) o por cualquier problema de validación.
- **Idempotencia:** la clave es el hash del archivo, así un reintento no duplica el comprobante.
- **Contenido no confiable:** el documento se muestra en un iframe con `sandbox` sin `allow-scripts`.

## Uso

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # extras: ".[claude]" para la API, ".[images]" para degradar, ".[pdf]" para PDF limpios
pytest

# 1. Dataset (100 comprobantes + ground truth)
python -m invoice_agent.datagen.generate --n 100 --degrade

# 2. ERP simulado (otra terminal)
ERP_FAIL_RATE=0.05 uvicorn invoice_agent.mock_erp.app:app --port 8000

# 3. Pipeline y evals (sin API key, con el extractor simulado)
python -m invoice_agent.pipeline.run --extractor simulated
python -m invoice_agent.evals.run_evals --extractor simulated
```

### Documentos degradados
`--degrade` (extra `images`) hace que una parte del dataset llegue como lo haría en la vida real, en vez de HTML limpio:

| Perfil | Formato | Qué simula |
|---|---|---|
| `html` | .html | documento digital limpio |
| `scan` | .pdf (solo imagen) | escáner de oficina: rotación leve, ruido, motas, grises |
| `photo` | .jpg | foto con el celular: perspectiva, sombra desigual, desenfoque, compresión JPEG |
| `fax` | .png | baja resolución y binarizado con ruido |

```bash
python -m invoice_agent.datagen.generate --n 100 --degrade --mix "scan:1,photo:2,fax:1"   # sin HTML limpio
```

Para una misma seed los datos de cada comprobante son los mismos con o sin `--degrade`; solo cambia cómo se ve. El ground truth guarda el perfil y `run_evals` reporta la precisión por perfil. Hace falta una fuente TTF con tildes (Arial en macOS, DejaVu en Linux; `INVOICE_AGENT_FONT` para forzar una).

### UI de revisión
Los campos corregidos se resaltan, las validaciones corren en vivo y **Aprobar y cargar** queda bloqueado mientras haya problemas. Al aprobar se carga en el ERP y se registra en `out/review_audit.jsonl`.

```bash
# con el ERP corriendo en el puerto 8000 y el pipeline ya ejecutado
uvicorn invoice_agent.review_api.app:app --port 8100     # usa ERP_URL, REVIEW_OUT, REVIEW_INBOX
cd review-ui && npm install && npm run dev               # http://localhost:5173 (proxy a :8100)
```

### Medir con Claude
```bash
pip install -e ".[claude,images]"
export ANTHROPIC_API_KEY=...                       # tu clave; no la guardes en el repo
python -m invoice_agent.evals.run_evals --extractor claude --limit 10   # prueba chica primero
python -m invoice_agent.evals.run_evals --extractor claude              # corrida completa (~1 llamada por documento)
python -m invoice_agent.pipeline.run --extractor claude
```
Cada documento se extrae una sola vez: el resultado se cachea en `.cache/extractions/` por hash del archivo, así que repetir la corrida no vuelve a llamar a la API. Si cambiás el prompt o el modelo (`INVOICE_AGENT_MODEL`), borrá esa carpeta. Una llamada fallida o una salida inválida cuenta como error de ese documento y queda en `extraction_failures` del reporte (`reports/eval.json`).

Qué mirar al leer el resultado:
- **Por calidad del documento:** cuánto cae la precisión de `html` a `photo`/`fax`.
- **Campos débiles:** suelen ser `total`/`neto` (formato `1.234,56` vs `1,234.56`) y `numero`.
- **Detección de problemas:** el modelo copia lo que ve, así que `cuit_invalid` e `iva_mismatch` dependen de que no "corrija" el documento.
- **Umbral de confianza:** compará la confianza declarada con los errores reales antes de fijar `--threshold`.

### Sobre el extractor `simulated`
Lee el ground truth y le inyecta ruido determinista (~4% por campo) para desarrollar y probar todo offline. **Sus métricas no miden ningún modelo**, y la tabla por calidad de documento sale pareja porque el ruido no depende del perfil. Lo que sí mide con validez es la sección "Detección de problemas", porque evalúa las validaciones y no el extractor.

Con Docker: `docker compose up mock-erp` y `docker compose --profile run run --rm pipeline` (no probado).
