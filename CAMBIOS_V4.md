# Marswalk v4: cambios al planificador

Rama `marswalk-v4`. Sale de una evaluación independiente del planificador v3 con cuatro partes: 50 pruebas de corrección, comparación contra el óptimo exacto, auditoría física y de datos, y encaje con la demo.

**Resumen de la evaluación de v3:**
- El núcleo era correcto: Dijkstra coincide exactamente con networkx.
- El optimizador es casi óptimo: llega al óptimo exacto en 20 de 20 semillas y en 268 de 273 subinstancias.
- Los datos están alineados al metro con USGS y JPL.
- Fallaba el modelo del mundo: no veía la arena de Séítah y el astronauta no tenía modelo de oxígeno ni de regreso.

Todos los cambios mantienen la API anterior.

## 1. Arena a escala de rover (lo que hace que reproduzca Séítah)
- **Capa nueva `arena_textura`.** Detecta campos de ondulaciones **solo con la textura** de la ortoimagen HiRISE ESP_045994: banda de paso de 4–12 m, anisotropía (crestas paralelas), percentil 65 y suavizado a 50 m. No se dibujó nada a mano y la ruta de Perseverance no se usó para construirla.
- **Entra al costo con `w_arena = 10`.**
- **Por qué hacía falta:** la "duna" de v3 (unidad eólica de SIM 3464, mapa a 1:75k) no registra Séítah como arena, y su peso no cambiaba ninguna ruta con ningún valor (0.5, 2, 5, 10 o ∞).

**Validación** (`python validar_seitah.py`): distancia media simétrica entre la ruta del planificador y la ruta real de Perseverance, en modo rover.

| Tramo | v3 original | **v4** | Odómetro real |
|---|---|---|---|
| A (sol 13–248, calibración) | 154 m | **51 m** | 2.66 km |
| **B (sol 362–477, rodeo de Séítah, reservado)** | 498 m (cruza Séítah) | **125 m (rodea por el norte)** | 6.97 km |
| C (sol 502–565, calibración) | 139 m | **42 m** | 1.03 km |

- **Cómo se eligió la configuración:** se probaron 12 combinaciones (w_arena 5, 10 o 20; pendiente CTX o p95 HiRISE; umbrales 20° o 15/30°) y se eligió **solo con A y C**.
- **Robustez:** en B, las 12 combinaciones quedan entre **118 y 125 m**.
- **Límite:** la orto cubre solo el 5 % de la malla. Fuera de ella, `arena_cobertura = 0` indica que la arena **no está evaluada**; ahí debe entrar la IA.

## 2. Pendiente fina
- Donde hay HiRISE (64 % de la malla) se usa `max(pendiente CTX 20 m, p95 de la pendiente HiRISE a 5 m)`.
- **Por qué:** la pendiente a 20 m escondía escarpes. 1.8 % de las celdas "seguras" tienen píxeles de más de 20° a 5 m.
- **`P_ROVER`** (riesgo ≥15°, bloqueado ≥30°): los conductores de Perseverance evitan inclinaciones de más de 30°, y con la pendiente fina el umbral de 20° bloqueaba celdas por donde el rover sí pasó. `P` (10° y 20°) queda para el astronauta. **Se aplica con `parametros(agente)`**: `Mapa.desde_capas(L, p=parametros(ROVER))` (lo usan el exportador y `validar_seitah.py`). Con `P` y la pendiente fina quedaría bloqueado el 4.0 % de las celdas de la ruta real de Perseverance; con `P_ROVER`, 0 %. La tabla de Séítah no cambia (los tramos no pasan por pendientes de 20–30°).
- **El mensaje de "no hay camino" usa el umbral real del mapa** (`Mapa.params`), no un 20° fijo.
- **`replanear_tramo` nunca bloquea los extremos del tramo:** el vehículo ya está ahí.

## 3. La IA duda, el robot verifica
```python
mapa = Mapa.desde_capas(L, prob_arena=p_ia, verificadas={(f, c): "arena" | "firme"})
mapa.incierto   # celdas con 0.4 <= p <= 0.6 aún sin verificar -> a dónde mandar al robot
mapa.origen     # por celda: 0 ORBIT, 1 HIRISE_TEXTURE, 2 AI, 3 SCOUT_VERIFIED (panel "¿por qué creerle?")
r = replanear_tramo(mapa, a, b, ROVER)   # ~0.1 s: ruta nueva en vivo cuando el robot marca una celda
```
Lo que verificó el robot manda sobre la IA, y la IA manda sobre la textura.

## 4. Astronauta con modelo metabólico
- **`ASTRONAUTA` usa ahora Pandolf + corrección de Santee** (la forma de Kim et al., IEEE EMBC 2024, NASA JSC, NTRS 20240001423), escalado a 0.38 g. Parámetros por defecto:
  - persona de 80 kg y traje de 104 kg (máximo recomendado para Marte, NASA ICES 2026);
  - kit de 10 kg (`kit_kg`, el control del dashboard);
  - η = 1.2 en regolito y η = 2.1 en arena.
- **`wh` del astronauta = energía metabólica** (no batería; el visor debe etiquetarlo así). El O₂ sale de `wh × 0.179` L (equivalente calórico de 20.1 kJ por litro). Cada parada de estudio gasta 150 W.
- **`costo_regreso(mapa, base)`** calcula la energía mínima y el tiempo mínimo para volver a la base desde cada celda. Es un Dijkstra inverso; tarda 0.13 s en un radio de 3 km.
- **`regreso_mision(...)`** da, a lo largo de la misión, la energía gastada, la que falta para volver, el margen y el **punto de no retorno**.
- **Ejemplo en Jezero** (EVA de 6 h con 1,408 Wh metabólicos y radio de 2.5 km): la misión de más ciencia gasta 776 Wh (~139 L de O₂). Con la mitad del presupuesto, el punto de no retorno cae en el paso 39 de 79.
- **Signo de Santee (corregido 14 nov):** en bajada se usa `M = MP − CF`, como la ecuación 1 de Kim et al. 2024 (NTRS 20240001423). La primera versión lo sumaba y subestimaba el costo de las bajadas fuertes.
- **Límites:**
  - el escalado a 0.38 g es lineal (es una cota baja);
  - no modela la caminata en pareja ni la termorregulación;
  - con trajes de más de 104 kg, Pandolf sale de su rango validado.

## 5. Correcciones de la evaluación
| ID | Qué pasaba | Arreglo |
|---|---|---|
| B1 | `simplificar` podía unir puntos de paso con rectas que cruzaban celdas bloqueadas | Supercover exacto (`_celdas_segmento`), costo integrado por fracción de longitud y regla de esquinas |
| B2 | Con un presupuesto justo se devolvía una misión infactible sin aviso | Se marca `factible=False` y `plan["aviso"]`; el exportador lo escribe |
| B3 | El resultado dependía de la velocidad de la máquina (tiempo límite) | `timeout_s=None` por defecto: para por generaciones o paciencia |
| B4 | `KeyError` en `camino_mision` con una misión cerrada vacía | Se manejan los tramos a → a |
| B5 | `radio_m` se ignoraba en misiones abiertas | `ValueError` |
| Punto ciego | Un conjunto que solo cabe con rutas "seguras" (más rápidas) nunca se encontraba (hasta 18 % de ciencia perdida) | `_perfil_minimo`: por tramo, el perfil que menos gasta |
| Nuevo | `_rugosidad` dividía entre 0 con pendiente uniforme y el costo quedaba NaN | Rugosidad 0 en ese caso |
| Energía del rover | 0.25 Wh/m, unas 5 veces bajo | 1.3 Wh/m (<200 W a ≤152 m/h, NASA) |

## 6. Otros cambios
- **Exportador:** salida también en **lon/lat** (`salida["lonlat"]`, esfera de Marte) para MapLibre, más el aviso de misión infactible.
- **`herramientas/preparar_capas_marswalk.py`:** regenera las capas nuevas desde los productos públicos de USGS y JPL (~1 min).
- **`tests/`:** 61 pruebas (pytest + hypothesis + networkx). Correr con `cd tests && python -m pytest -q`.

## Pendiente (no incluido)
- Capas de NE Syrtis y escenarios de EVA-1 y EVA-2; clase de serpentina en la ciencia.
- Riesgo continuo por pendiente (hoy el frente casi no distingue entre misiones por riesgo).
- Replaneo incremental de la misión completa (~1 s; prototipo en la evaluación).
- Subir el límite de 15 candidatos: pierde 3–7 % de ciencia.
- Presupuesto del rover por sol; tipos de objetivo (teledetección contra muestreo).
