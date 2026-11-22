# Informe de cierre de la fase 2 — periodic-report-kit

Fecha: 2026-11-20 · Paquete: `reportkit` 0.1.0 · Rama: `claude/keen-mendel-q7ctle`

## 1. Qué se implementó de la especificación

| Sección de la spec | Estado | Dónde |
|---|---|---|
| 3.1 Capas y modelo canónico largo | Completo | `model.py`, `loaders.py` |
| 3.2 Cinco ficheros de configuración | Completo (nombres en inglés) | `src/reportkit/data/config/*.yaml`, `src/reportkit/data/brands/nordal/brand.yaml` |
| 3.3 Flujo de datos de un mes (globs, fila a fila, cuarentena, periodo por fecha, copias, caché, rango) | Completo | `loaders.py` |
| 4 Reglas de dominio 1–14 | Completo, cada una con test | `tests/test_loaders.py`, `tests/test_metrics.py`, `tests/test_report.py` |
| 5 Render Word (plantilla, portada texto sobre fondo anclado, TOC `\o`, primera página con membrete, tablas, gráficos, huecos, cabecera) | Completo | `render_docx.py`, `tests/test_render_docx.py` |
| 6 Render PDF (dos pasadas + unión, 150 dpi, numeración solo del cuerpo, respaldo CSS, `data:` URI, anexo apaisado) | Completo | `render_pdf.py`, `tests/test_render_pdf.py` |
| 7 Markdown → docx / pptx con los nueve bloques | Completo en ambos formatos | `render_md.py`, `examples/demo_deck.md` |
| 8 Validación y contraste | Completo | `validator.py`, `tests/test_validator.py` |
| 9 API pública y CLI | Completo (nombres en inglés) | `__init__.py`, `cli.py` |
| 10 Casos de prueba (20) | Los 20 tienen test | ver tabla siguiente |
| 11 Decisiones de diseño | Implementadas y explicadas en el README | `README.md`, `docs/DECISIONES.md` |
| 12 Palabras prohibidas | Guarda con lista ofuscada en base64 | `tests/test_no_leaks.py` |

Correspondencia de los veinte casos de prueba de la especificación:

| Caso | Test |
|---|---|
| Control limpio solo si todos sus ítems lo son | `test_metrics::test_clean_control_only_if_every_item_is_clean` |
| Cumplimiento excluye no aplica (62,5 %, base 8) | `test_metrics::test_conformity_excludes_not_applicable` |
| Fila sin resultado no es ítem (8 + aviso 2) | `test_loaders::test_blank_result_is_not_an_item` |
| Etiqueta de mes errónea | `test_loaders::test_wrong_month_label_row_is_ignored_and_period_comes_from_date` |
| Fichero mixto | `test_loaders::test_mixed_file_resolves_group_row_by_row` |
| Copias discrepantes | `test_loaders::test_duplicate_control_keeps_copy_with_most_items` |
| Dimensión declarada falsa | `test_loaders::test_lying_dimension_is_counted_in_xml` |
| UTC → local | `test_loaders::test_utc_timestamp_moves_to_next_local_day` y `…_period_is_derived_from_local_date` |
| Fusión de nombres | `test_loaders::test_name_merge_is_reported` |
| Volumen vs tasa | `test_metrics::test_volume_sums_every_unit_but_rates_only_controls` |
| Gráfico condicional | `test_charts_tables_comments::test_group_with_zero_incidents_gets_no_chart`, `test_report::test_group_without_incidents_gets_sentence_instead_of_chart` |
| Pendiente no es cero | `test_metrics::test_with_total_sums_counts_recomputes_rates_and_ignores_pending`, `test_charts_tables_comments::test_summary_marks_blocked_group_pending…` |
| Comentario desfasado | `test_charts_tables_comments::test_stored_comment_is_published_and_drift_is_reported` |
| Portada texto | `test_render_docx` (acentos, `behindDoc` a 0,0, sección 1 sin márgenes, sección 2 con membrete, interlineado exacto) |
| Índice | `test_render_docx::test_toc_is_a_field_by_outline_level_and_excludes_its_title` |
| PDF 4 páginas, pie solo en contenido | `test_render_pdf::test_cover_plus_three_pages_numbered_only_in_content` |
| PDF sin PNG | `test_render_pdf::test_without_png_single_pass_css_cover` |
| Markdown bloques | `test_render_md::test_md_to_docx_and_pptx_render_all_nine_blocks` |
| Contraste prosa ≠ tabla, código 1 | `test_validator::test_prose_differing_from_table_is_flagged` |
| Sintético en nombre y portada | `test_report::test_monthly_report_structure`, `test_cli` |

## 2. Qué quedó fuera y por qué

- **Regeneración del PNG de fondo con LibreOffice en CI.** El camino existe (`scripts/build_brand_kit.py --from-template`) y se probó a mano en esta sesión, pero la CI no instala una suite ofimática; el fondo versionado se dibuja con Pillow desde la geometría declarada.
- **Validación de la paleta de la marca.** Las paletas se cargan tal cual desde `brand.yaml`; el kit no comprueba contraste ni separación para daltonismo. Los gráficos añaden etiquetas directas y leyenda para que la identidad no dependa solo del color.
- **Lectura de `.xls` antiguo y de hojas protegidas.** Solo `.xlsx`/`.xlsm`/`.csv`.
- **Fuente aislada en el `.docx`.** python-docx no incrusta fuentes; el kit fija el nombre de la fuente resuelta en los estilos y deja la sustitución a Word.
- **Posición exacta en Windows.** La geometría de portada se verificó con LibreOffice en Linux; en Word para Windows no se ha abierto el fichero en esta fase.
- Todo lo declarado fuera de alcance en la v1 de la especificación (conectores, dashboards, firma, nube, OCR).

## 3. Decisiones propias

Veinte decisiones registradas en `docs/DECISIONES.md` con su alternativa y motivo. Las más
relevantes: nombres de módulo y claves YAML en inglés; columna `unit` en el modelo para separar
volumen de tasa; nombres fijos `conformity_rate` / `clean_rate` con base en la cabecera; evaluador
de condiciones cerrado; un gráfico con serie vacía no aplica; salida versionada `vNNN`; frase
sustitutoria solo para gráficos que la declaran; fondo del PDF en marco estático; guarda de fugas
con códigos sensibles a mayúsculas.

## 4. Resultados

- Suite: 72 tests en verde (Python 3.13 local; la CI corre 3.11 y 3.12), unos 37 s en el contenedor de la sesión.
- `ruff check` y `ruff format --check` limpios.
- Guarda de fugas en verde sobre el árbol y sobre `git log -p --all`.
- Demostración (`reportkit demo --months 6`): 18 ficheros sintéticos, informe mensual de 15 páginas e informe semestral de 22 páginas con PDF, en unos 16 s. `reportkit validate` sobre el mensual generado: sin discrepancias, código 0.
- Tamaño: unas 5 100 líneas en `src/reportkit` y 1 400 en `tests`.

## 5. Qué revisar en la fase 3

1. **Historial de commits.** Los mensajes llevan los avances de la sesión de construcción; confirmar que no contienen nada de la lista prohibida (la guarda ya barre `git log -p`, pero conviene lectura humana de los mensajes).
2. **Identificadores coincidentes.** La guarda no puede detectar nombres de la fuente que no estén en la lista; comparar `src/reportkit` contra la fuente buscando identificadores no triviales y fragmentos de cinco o más líneas.
3. **Constantes.** 150 dpi, 170 dpi, 1241×1754 px, factor 72/dpi y `\o "1-2"` vienen de la especificación o de normas públicas (A4 a 150 dpi); revisar que ninguna otra constante coincida con la fuente sin venir de una norma.
4. **Binarios.** Solo `src/reportkit/data/brands/nordal/template.docx` y `src/reportkit/data/brands/nordal/cover_background.png`, ambos generados por `scripts/build_brand_kit.py`; no hay CSV ni Excel versionados.
5. **Atribución y licencia.** README en ambos idiomas con la atribución literal; `LICENSE` MIT desde el primer commit.
6. **Textos fijos de metodología** en `src/reportkit/data/config/report_catalog.yaml`: redactados de nuevo para esta implementación; comprobar que no reproducen frases de los informes originales.
