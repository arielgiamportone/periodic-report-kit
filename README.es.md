# periodic-report-kit

[English version](https://github.com/arielgiamportone/periodic-report-kit/blob/main/README.md)

Informes periódicos declarativos: datos tabulares de entrada, Word / PDF / PPTX con marca de
salida, con portada a sangre completa, índice como campo real de Word, gráficos condicionales y
huecos para el comentario humano. Caso de estudio clean-room construido a partir de una
especificación escrita, solo con datos sintéticos.

[![CI](https://github.com/arielgiamportone/periodic-report-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/arielgiamportone/periodic-report-kit/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/periodic-report-kit.svg)](https://pypi.org/project/periodic-report-kit/)
![Python 3.11 | 3.12](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)

Instalación: `pip install periodic-report-kit` (el paquete importable y la CLI son `reportkit`).

## El problema

En muchos servicios de inspección o control recurrente, el informe periódico se ensambla a mano:
alguien exporta hojas de cálculo del sistema de campo, recalcula totales en tablas dinámicas,
pega cifras y gráficos en un Word con membrete y rehace la portada cada mes. El proceso cuesta
horas, las cifras del resumen contradicen a las de los capítulos y regenerar el documento
destruye los comentarios que una persona ya había redactado.

## Restricciones

- La entrada es lo que exporta el sistema de campo: Excel o CSV, carpetas y ficheros con nombres
  inconsistentes, hojas-resumen hechas a mano junto a la hoja de registros, borradores y ficheros
  de bloqueo en la misma carpeta.
- La salida debe llevar el membrete del cliente, una portada seleccionable, un índice que Word
  actualice y un PDF cuya portada quede fuera de la numeración.
- Tiene que correr en servidores Linux y en CI sin Office.
- Todo porcentaje declara su base, nada se lee como cero en silencio y el comentario escrito por
  una persona sobrevive a la regeneración.
- Repositorio público: sin datos reales, sin nombres de cliente, sin rutas internas. Todo lo que
  usan los tests y la demo se genera.

## Arquitectura

```
 Excel / CSV crudos
      │  loaders: traducen, no interpretan; lo desconocido -> cuarentena + aviso tipado
      ▼
 ╔═ MODELO CANÓNICO ═════════════════════════════════════════════════╗
 ║ un DataFrame largo, una fila por ítem evaluado                       ║
 ║ periodo · grupo · control · elemento · dims… · categoría · ítem ·    ║
 ║ resultado ∈ {ok, fail, na} · comentario · fecha · origen · unidad    ║
 ║ ← frontera: por encima nadie sabe de qué fichero vino el dato        ║
 ╚═════════════════════════════════╤═════════════════════════════════╝
                                   ▼
 métricas: cinco definiciones, dos tasas con nombre fijo, cortes por cualquier dimensión
      │                     │                      │
      ▼                     ▼                      ▼
 gráficos (matplotlib)   tablas               comentarios humanos (YAML por periodo)
 declaran nivel, métrica listas para volcar   hueco con pistas si no hay texto
 y condición
      └──────────────┬───────────┴──────────────────┘
                     ▼
 composición: secciones por tipo de informe (mensual / semestral / anual) desde un catálogo
      ┌──────────────┼──────────────┐
      ▼              ▼              ▼
 render Word     render PDF     Markdown -> docx / pptx
 plantilla +     dos pasadas +  nueve bloques visuales
 kit de marca    unión pypdf    + kit de marca
                     │
                     ▼
 validador: contrasta con lo entregado, código 1 si hay discrepancias
```

Las reglas viven en configuración, no en código:

| Fichero | Gobierna |
|---|---|
| `config/data_schema.yaml` | columnas de origen con variantes, hojas válidas y prohibidas, valores crudos del resultado, zona horaria, globs tolerantes |
| `config/groups.yaml` | grupos del informe (capítulos), variantes de etiqueta, dimensión responsable, reasignaciones por elemento, motivo de bloqueo sin fuente |
| `config/items.yaml` | categoría cruda -> canónica (acentos, mayúsculas, prefijos numéricos), fusiones explícitas, síntomas de columna desplazada |
| `config/report_catalog.yaml` | secciones por tipo de informe, gráficos con su condición (`if: incidents >= 3`), periodos del eje, textos fijos |
| `brands/<marca>/brand.yaml` | paleta, paleta semántica, fuentes con respaldo, plantilla, fondo de portada, geometría de barras, pie legal |

Estructura del paquete: `src/reportkit/{schema,model,loaders,metrics,charts,tables,comments,brand,
catalog,report,render_docx,render_pdf,render_md,validator,synthetic,cli}.py`.

## Reglas de dominio (todas con test)

1. **El rango temporal es un parámetro explícito** (`--from 2026-01 --to 2026-06`). Nunca se
   deduce del nombre de carpeta ni del calendario; un semestre puede cruzar el cambio de año.
2. **Una fila con resultado vacío no es un ítem evaluado**; contarla infla el denominador. El
   cargador informa de cuántas filas apartó y de qué controles eran.
3. **Nunca se leen hojas hechas a mano.** Todo se recalcula desde la hoja de registros; las hojas
   prohibidas se declaran en el esquema.
4. **Globs tolerantes**: carpetas con o sin acento, singular o plural, `03.` o `3.`; el histórico
   no se renombra. Los duplicados se eliminan por ruta resuelta.
5. **Todo porcentaje declara su base.** Dos tasas confundibles llevan nombre fijo:
   `conformity_rate` = ok / (ok + fallo) sobre ítems y `clean_rate` = controles limpios /
   controles. La variante con «no aplica» en el denominador no existe a propósito.
6. **Sumar volumen, promediar solo lo comparable.** Las actuaciones totales suman todas las
   unidades (controles, encuestas…); las tasas y densidades usan solo controles de la misma unidad.
7. **La tasa de casos limpios sobre fuentes agregadas es una cota inferior sobre el total de
   visitas**, una base que existe en los ficheros del cliente, en lugar de una base restringida que
   fabrica tendencia.
8. **Las fechas se convierten a la zona local declarada antes de derivar el periodo.** Una
   exportación UTC a las 23:30Z del día 1 cae en el día 2.
9. **La normalización de nombres solo corrige espacios** (repetidos, duros, antes de coma) y
   registra cada fusión; conceptos distintos nunca se fusionan salvo lista explícita.
10. **El comentario humano es un hueco, no se redacta.** `[[COMENTARIO]]` con las cifras
    actuales; un comentario guardado se publica y se avisa si sus cifras difieren de las actuales.
    Una propuesta automática nunca se publica.
11. **Lo no calculable es `[[PENDIENTE]]`**, nunca cero; los totales lo ignoran.
12. **Dos niveles de agrupación que no se mezclan**: categoría (reparto) e ítem (top-N); un ítem
    repetido en varias categorías se cualifica «ítem (categoría)».
13. **No se sobrescriben entregables**: cada ejecución escribe en
    `out/<tipo>_<desde>_<hasta>/vNNN/`, y un periodo cuenta como entregado solo si tiene PDF.
14. **No se confía en la dimensión declarada de una hoja**: se cuentan las filas en el XML y se
    reintentan los errores de E/S antes de concluir «vacío».

## Decisiones y alternativas descartadas

| Decisión | Descartada | Motivo |
|---|---|---|
| HTML -> PDF en dos pasadas unidas con pypdf | `@page` con nombre en un solo HTML | el motor objetivo las ignora; una portada sin márgenes y un cuerpo numerado no caben en una plantilla de página |
| python-docx más XML puntual | automatizar Word por COM | debe correr en Linux y en CI sin Office; COM es frágil y no reproducible |
| TOC por nivel de esquema (`\o "1-2"`), nivel en el párrafo | TOC por nombre de estilo | el conmutador por estilo usa un separador que cambia con el idioma de Word y falla como índice vacío; en el párrafo, el título «Contenidos» queda fuera de su propio índice |
| Portada como texto de Word sobre fondo anclado detrás a 0,0 | PNG completo compuesto con Pillow | el texto no era seleccionable y la fuente ausente caía al bitmap sin avisar; el PNG sobrevive solo para el PDF |
| Reglas en YAML con tests | `if` en el código | un criterio que cambia debe ser una línea de catálogo, no un despliegue |
| Modelo canónico largo como frontera | métricas leyendo Excel directamente | cambiar la fuente (una API) solo toca el cargador |
| Comentarios en YAML por periodo | texto dentro del `.docx` | regeneración idempotente y reutilización entre mensual y semestral |
| Tasa de limpios como cota inferior sobre el total | base restringida a una visita | la base debe existir en los ficheros del cliente |
| Portada fuera de la numeración del PDF | postprocesar el pie | natural con dos pasadas |
| Evaluador cerrado de condiciones de gráfico | `eval` | el catálogo es YAML editable; `None` es falso, nunca cero |
| Un gráfico con serie vacía «no aplica» | dibujarlo vacío | un grupo de solo encuestas cumple `periods >= 2` pero no tiene tasa |

El registro completo de decisiones propias está en [`docs/DECISIONES.md`](https://github.com/arielgiamportone/periodic-report-kit/blob/main/docs/DECISIONES.md).

## Qué se midió y cómo reproducirlo

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest            # 72 tests, unos 40 s
ruff check . && ruff format --check .
```

```bash
reportkit demo --out out/demo --months 6
```

La demo escribe seis meses de ficheros crudos sintéticos (con las trampas para las que existe
cada regla: borradores, ficheros de bloqueo, etiquetas de mes erróneas, resultados en blanco,
ficheros mixtos, controles duplicados, una hoja que miente sobre su tamaño, una exportación UTC) y
genera un informe mensual y uno semestral, marcados «DATOS SINTÉTICOS» en el nombre y en la portada.

| Medida | Resultado |
|---|---|
| Informe mensual (5 grupos, 50 controles, 1 500 ítems) | 15 páginas, docx + pdf |
| Informe semestral (6 meses) | 22 páginas, 17 gráficos, 22 tablas |
| Demo de principio a fin (datos + dos informes con PDF) | unos 16 s |
| Contraste del mensual generado con su propio modelo | 0 discrepancias, código 0 |
| Guarda de fugas | árbol y `git log -p` limpios |

Otros comandos:

```bash
reportkit generate --type monthly --from 2026-03 --to 2026-03 --data out/demo/data --out out --pdf
```

```bash
reportkit comments --period 2026-03 --data out/demo/data --out out/comments
```

```bash
reportkit validate --period 2026-03 --delivered out/.../Informe_monthly_2026-03_2026-03.docx --data out/demo/data
```

```bash
reportkit md examples/demo_deck.md --docx --pptx --out out/md
```

API Python (los nombres coinciden con las exportaciones públicas de `reportkit`):

```python
from reportkit import load_range, summarize, build_report, contrast, md_to_pptx
```

## Límites conocidos

- El fondo de portada de la marca de demostración se dibuja desde la geometría declarada; el
  camino que rasteriza un membrete real (`scripts/build_brand_kit.py --from-template`) necesita
  LibreOffice.
- Las fuentes no se incrustan en el `.docx`; se escribe en los estilos el nombre de la familia
  resuelta.
- Solo entradas `.xlsx`, `.xlsm` y `.csv`.
- Las paletas se toman de `brand.yaml` tal cual; el kit no valida contraste ni separación para
  daltonismo, por eso los gráficos añaden siempre etiquetas directas y leyenda.
- La geometría de portada se verificó renderizando con LibreOffice en Linux.

## Cómo se construyó

Clean room en tres fases: se escribió una especificación a partir del trabajo original, sin
código; este repositorio se implementó en una sesión aparte sin acceso a ese código, desde la
especificación y la documentación pública de OOXML, python-docx, python-pptx, matplotlib,
xhtml2pdf y pypdf; una tercera fase revisa el resultado contra la fuente antes de publicar. Un
test guarda de fugas con lista ofuscada corre en CI sobre el árbol y el historial de git.

## Atribución

Patrones desarrollados durante mi trabajo en Intervalor Data y publicados con autorización. Implementación independiente (clean-room) con datos sintéticos; no contiene código ni datos de la empresa ni de sus clientes.

Licencia: MIT.
