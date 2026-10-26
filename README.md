# Visor 3D · Cráter Jezero

Visualización 3D en el navegador del cráter Jezero (Marte) para el reto **Marswalk** del hackathon de NASA.
Muestra el relieve real del cráter con la imagen orbital encima, la ruta planeada por nuestro
planificador (A\* sobre un mapa de costos de transitabilidad), los objetivos científicos que eligió
y, como referencia, la ruta real que recorrió el rover Perseverance.

Hecho con [Three.js](https://threejs.org/) y [Vite](https://vite.dev/). Los datos se preparan con Python.

## Qué muestra

- **Terreno**: modelo de elevación CTX de 20 m (20 × 20 km alrededor de 18.43° N, 77.43° E) con la
  ortoimagen CTX encima, en tono marciano. Exageración vertical de 3× por defecto.
- **Plan propio** (rojo): ruta calculada con A\* que visita objetivos científicos con un presupuesto de costo.
- **Objetivos** (amarillo): zonas de interés mineral detectadas en el mapa CRISM.
- **Inicio / meta** (verde / morado): el primer y el último punto de la ruta real de Perseverance.
- **Ruta real de Perseverance** (blanco): para comparar con el plan.
- **Rover**: modelo 3D de Perseverance de NASA recorriendo el plan.

> El rover se muestra **60 veces más grande** que su tamaño real para que se vea a esta escala
> (a escala real mediría menos de un píxel).

## Requisitos

- [Node.js](https://nodejs.org/) en versión LTS reciente (probado con 24).
- Python 3.10+ (solo para regenerar los datos).

## Cómo correrlo

```bash
npm install
npm run dev
```

Abre la dirección que aparece (normalmente http://localhost:5173).

Controles: **arrastrar** = girar · **rueda** = zoom · **clic derecho** = mover la vista.

> En Windows PowerShell, si `npm` marca un error de "ejecución de scripts deshabilitada",
> usa `npm.cmd` (por ejemplo `npm.cmd run dev`) o la terminal `cmd`.

Para generar la versión de producción (carpeta `dist/`):

```bash
npm run build
```

## Regenerar los datos

Los archivos de `public/data/` ya están incluidos, así que el visor funciona sin Python.
Solo hace falta regenerarlos si cambian las capas o el planificador:

```bash
pip install -r requirements.txt
python exportar_terrenos.py   # dem.bin, meta.json, textura.jpg
python exportar_rutas.py      # rutas.json
```

Estos scripts leen archivos **fuera de esta carpeta**, del proyecto principal:

- `../data/processed/` — capas alineadas en una malla de 1000 × 1000 celdas de 20 m.
- `../prototipo_uno/` — mapa de costos, selección de objetivos y A\* (`exportar_rutas.py` los importa).

## Estructura

```
visor_3d/
├── index.html              # lienzo y carga del módulo principal
├── src/
│   ├── main.js             # une todos los módulos y el bucle de animación
│   ├── escena.js           # renderer, cámara, luces, cielo, niebla y sombras
│   ├── terreno.js          # malla del DEM, textura y conversión metros -> escena
│   ├── rutas.js            # tubos de las rutas y marcadores
│   └── rover.js            # carga del modelo y recorrido sobre la ruta
├── public/
│   ├── data/               # generado por los scripts de Python
│   │   ├── dem.bin         # alturas float32, 400 × 400, fila 0 = Norte
│   │   ├── meta.json       # tamaño de la malla, extensión y rango de elevación
│   │   ├── textura.jpg     # ortoimagen CTX coloreada, 1024 × 1024
│   │   └── rutas.json      # plan, objetivos y ruta real (metros: x = Este, y = Norte)
│   └── modelos/
│       └── perseverance.glb
├── exportar_terrenos.py
├── exportar_rutas.py
├── requirements.txt
└── package.json
```

## Sistema de coordenadas

- Los datos usan **metros locales**: `x` hacia el Este, `y` hacia el Norte, con el centro del mapa en (0, 0).
- En la escena, **1 unidad = 100 m**, así que el mapa va de −100 a 100.
- Three.js usa **y hacia arriba**: x de la escena = Este, y = altura, z = Sur.
  La conversión está en `terreno.aEscena(x, y)`, que además coloca el punto sobre el terreno.

## Datos y créditos

| Dato | Fuente |
|---|---|
| Elevación (DTM CTX 20 m) y ortoimagen CTX | Mars 2020 Terrain Relative Navigation, USGS Astrogeology (MRO CTX) |
| Mineralogía CRISM (para elegir objetivos) | Parente, Itoh y Saranathan, UMass — [Zenodo 5575824](https://zenodo.org/records/5575824), licencia **CC-BY 4.0** |
| Unidades geológicas (para el mapa de costos) | Sun y Stack, USGS SIM 3464 — Mapa geológico de Jezero y Nili Planum |
| Ruta real de Perseverance | Waypoints de la misión Mars 2020 (NASA), vía [stiles/mars-perseverance-waypoints](https://github.com/stiles/mars-perseverance-waypoints) |
| Modelo 3D de Perseverance | NASA/JPL-Caltech — [Mars Perseverance Rover, 3D Model](https://science.nasa.gov/resource/mars-perseverance-rover-3d-model/) |

Los objetivos científicos y el plan son resultado de **nuestro** planificador; el valor asignado a
cada mineral es un criterio del equipo, no una valoración de NASA.

## Pendiente

- Panel de controles: capas, exageración vertical, pausa y cámara que sigue al rover.
- Rendimiento: sombras precalculadas y versión optimizada del modelo del rover.
- Información de cada objetivo al hacer clic y panel de métricas (distancia, costo, presupuesto).
- Capas de CRISM y del mapa de costos sobre el terreno.
