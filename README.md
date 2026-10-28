# Visor 3D · Cráter Jezero

Visualización 3D en el navegador del cráter Jezero (Marte) para el reto **Marswalk** del hackathon de NASA.
Muestra el relieve real del cráter con la imagen orbital encima, la ruta planeada por nuestro
planificador (A\* sobre un mapa de costos de transitabilidad), los objetivos científicos que eligió
y, como referencia, la ruta real que recorrió el rover Perseverance.

Hecho con [Three.js](https://threejs.org/) y [Vite](https://vite.dev/). Los datos se preparan con Python.

## Qué muestra

- **Terreno**: modelo de elevación CTX de 20 m (20 × 20 km alrededor de 18.43° N, 77.43° E) con la
  ortoimagen CTX encima, en tono marciano. Exageración vertical de 3× por defecto.
- **Plan propio** (rojo): misión del notebook `planificador_v2` (A\* + NSGA-II) que visita objetivos
  científicos dentro de un presupuesto de tiempo y energía. Con el selector se puede ver también el plan v1.
- **Objetivos** (amarillo): zonas de interés mineral detectadas en el mapa CRISM. Clic en un pin = ficha
  con mineral, área y puntaje de ciencia.
- **Inicio / meta** (verde / morado): el primer y el último punto de la ruta real de Perseverance.
- **Ruta real de Perseverance** (blanco): para comparar con el plan.
- **Rover**: modelo 3D de Perseverance de NASA recorriendo el plan.
- **Capas sobre el terreno**: minerales CRISM o mapa de costos, con opacidad ajustable.
- **Panel de métricas**: ciencia, tiempo y energía de la misión, y comparación con la ruta real de
  Perseverance (misión completa y tramo a tramo).

> El rover se muestra **60 veces más grande** que su tamaño real para que se vea a esta escala
> (a escala real mediría menos de un píxel).

## Requisitos

- [Git](https://git-scm.com/) para descargar el repositorio.
- [Node.js](https://nodejs.org/) en versión LTS reciente (probado con 24). Incluye `npm`.
  Para comprobar que está instalado: `node -v` y `npm -v` en una terminal.
- Python 3.10+ **solo** si se quieren regenerar los datos (no hace falta para ver el visor).

## Cómo probarlo

Abre una terminal (en Windows: PowerShell, `cmd` o la terminal de VS Code) y ejecuta:

```bash
# 1. Descargar el repositorio (solo la primera vez)
git clone https://github.com/DimoltoSs/marswalk-3d-viewer.git

# 2. Entrar a la carpeta del proyecto: los demás comandos se corren AQUÍ
cd marswalk-3d-viewer

# 3. Instalar las dependencias (Three.js y Vite). Solo la primera vez; crea node_modules/
npm install

# 4. Iniciar el servidor de desarrollo
npm run dev
```

La terminal mostrará algo como `Local: http://localhost:5173/`. Abre esa dirección en el navegador
(Chrome, Edge, Brave o Firefox).

- **Deja la terminal abierta** mientras usas el visor: es el servidor. Para detenerlo, `Ctrl + C`.
- La próxima vez basta con entrar a la carpeta (`cd marswalk-3d-viewer`) y correr `npm run dev`.
- Para traer los últimos cambios del repositorio: `git pull` dentro de la carpeta.
- Abrir `index.html` con doble clic **no funciona**: el visor carga sus datos con `fetch`, y eso
  necesita el servidor de `npm run dev`.

> **Windows PowerShell:** si `npm` marca *"la ejecución de scripts está deshabilitada"*,
> usa `npm.cmd` en su lugar (`npm.cmd install`, `npm.cmd run dev`) o abre la terminal `cmd`.

### Controles

- **Ratón**: arrastrar = girar · rueda = zoom · clic derecho = mover la vista · clic en un pin amarillo = ficha del objetivo.
- **Panel izquierdo**: plan v1/v2, capas de rutas, exageración del relieve, capa sobre el terreno
  (CRISM / costos), velocidad y pausa del rover, cámara que sigue al rover. Clic en el título para plegarlo.
- **Panel derecho**: métricas de la misión y comparación con Perseverance.

### Si algo falla

| Síntoma | Causa probable |
|---|---|
| `npm` no se reconoce como comando | Falta instalar Node.js, o hay que cerrar y volver a abrir la terminal después de instalarlo. |
| Error de "scripts deshabilitados" en PowerShell | Usa `npm.cmd` (ver arriba). |
| `Could not read package.json` | No estás dentro de la carpeta del proyecto: haz `cd marswalk-3d-viewer`. |
| Página en blanco o aviso rojo abajo | Recarga con `Ctrl + F5`; el aviso dice qué archivo de `public/data/` falta. |
| Va lento | Cierra otras pestañas pesadas; en laptops, conecta el cargador (la GPU baja de potencia con batería). |

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
python exportar_rutas.py      # rutas.json (plan v1)
```

El plan v2 y lo demás lo genera el notebook `../notebooks/planificador_v2.ipynb`:

- Sección 12 → `rutas_v2.json` (misión, objetivos y métricas).
- Sección 13.4 → comparación con Perseverance dentro de `rutas_v2.json`, `capa_crism.png`,
  `capa_costo.png` y `capas.json`.

Estos scripts leen archivos **fuera de esta carpeta**, del proyecto principal:

- `../data/processed/` — capas alineadas en una malla de 1000 × 1000 celdas de 20 m.
- `../prototipo_uno/` — mapa de costos, selección de objetivos y A\* (`exportar_rutas.py` los importa).
- `../notebooks/planificador_v2.ipynb` — planificador v2 (mapa de costos, A\*, NSGA-II y comparación con NASA).

## Estructura

```
visor_3d/
├── index.html              # lienzo y carga del módulo principal
├── src/
│   ├── main.js             # une todos los módulos y el bucle de animación
│   ├── escena.js           # renderer, cámara, luces, cielo, niebla y sombras
│   ├── terreno.js          # malla del DEM, textura y conversión metros -> escena
│   ├── rutas.js            # tubos de las rutas y marcadores
│   ├── rover.js            # carga del modelo y recorrido sobre la ruta
│   ├── interfaz.js         # panel de controles (solo conecta eventos)
│   ├── seleccion.js        # clic en un pin -> ficha del objetivo
│   ├── metricas.js         # panel de métricas y comparación con Perseverance
│   └── capas.js            # capas CRISM / costos encima del terreno
├── public/
│   ├── data/               # generado por los scripts de Python y el notebook
│   │   ├── dem.bin         # alturas float32, 400 × 400, fila 0 = Norte
│   │   ├── meta.json       # tamaño de la malla, extensión y rango de elevación
│   │   ├── textura.jpg     # ortoimagen CTX coloreada, 1024 × 1024
│   │   ├── rutas.json      # plan v1, objetivos y ruta real (metros: x = Este, y = Norte)
│   │   ├── rutas_v2.json   # misión v2 + métricas + comparación con Perseverance
│   │   ├── capa_crism.png  # minerales CRISM (RGBA, 1000 × 1000)
│   │   ├── capa_costo.png  # mapa de costos (RGBA, 1000 × 1000)
│   │   └── capas.json      # leyendas de las capas
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

- Publicar en GitHub Pages para verlo sin instalar nada.
- Versión optimizada del modelo del rover (menos triángulos y texturas comprimidas).
