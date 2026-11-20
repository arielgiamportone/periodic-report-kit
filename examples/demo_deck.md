# Plan de modernización del servicio de informes

Documento de ejemplo con los nueve bloques visuales. Datos sintéticos.

---

## Situación de partida

Cada mes el informe se montaba a mano a partir de hojas de cálculo.

```kpi
7 h :: horas por informe
3 :: versiones por entrega
12 :: cifras contradictorias detectadas
```

Las cifras son ilustrativas.

---

## Líneas de trabajo

```cards
Modelo canónico :: Una fila por ítem evaluado :: En producción
Kit de marca :: Paleta, fuentes y plantilla intercambiables :: En curso
Validador :: Contraste con lo entregado :: Crítico
Comentarios :: Huecos con pistas :: Pendiente
```

---

## Diagnóstico

```quad
Fortalezas | Datos de campo completos ;; Equipo con criterio
Debilidades | Proceso manual ;; Cifras inconsistentes
Oportunidades | Automatizar el 80 % ;; Reutilizar en semestral
Amenazas | Cambios de formato en origen ;; Dependencia de una persona
```

---

## Flujo propuesto

```flow
Cargar → Normalizar → Calcular → Componer → Validar
```

---

## Antes y después

```beforeafter
Tiempo | 7 horas | 20 minutos
Coherencia | Resumen ≠ capítulos | Una sola fuente
Comentarios | Se perdían al regenerar | Viven en YAML
```

---

## Decisiones

```decisions
Reglas en YAML :: Un criterio que cambia es una línea de catálogo, no un despliegue.
Portada como texto :: Seleccionable, con acentos, sobre fondo anclado detrás.
Dos pasadas de PDF :: El motor ignora las @page con nombre.
```

---

## Hoja de ruta

```roadmap
Datos | Modelo canónico: 2026-Q1-2026-Q2 | Caché: 2026-Q3-2026-Q3
Render | Word: 2026-Q2-2026-Q3 | PDF: 2026-Q3-2026-Q4
Calidad | Validador: 2026-Q4-2027-Q1
```

---

## Cartera

```bcgmatrix
Mensual :: 0.8 :: 0.7
Semestral :: 0.3 :: 0.6 :: 0.6 :: 0.8
Presentaciones :: 0.2 :: 0.2
```

---

## Fuerzas

```porter
arriba :: Nuevos entrantes :: Herramientas genéricas de BI
izquierda :: Proveedores :: Sistemas de campo
centro :: Rivalidad :: Informes a medida
derecha :: Clientes :: Servicios de inspección
abajo :: Sustitutivos :: Dashboards web
```

| Bloque | Word | PowerPoint |
|---|---|---|
| kpi | tarjetas | tarjetas con banda |
| porter | cruz | cinco cajas |
