"""servidor.py - API local del planificador para el visor 3D.

Carga el mapa de costos una sola vez y responde rutas con A*.
Arrancar (desde visor_3d):  python -m uvicorn servidor:app --port 8000
Probar a mano:              http://localhost:8000/docs
"""
import os
import sys

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "prototipo_uno"))
from proto1_capas import cargar, rc_a_xy, xy_a_rc            # noqa: E402
from proto1_mapa_costos import construir_costo               # noqa: E402
from proto1_objetivos import candidatos_ciencia, elegir_objetivos  # noqa: E402
from proto1_planificador import matriz_costos, planear_mision  # noqa: E402
from eva import ESFUERZO_MAX, RADIO_M, distancia_a, mejor_centroide, planear_eva  # noqa: E402
from replaneo import distancia_acumulada                     # noqa: E402

NOMBRES = {1: "Olivine", 2: "Mg-Carbonate", 3: "Fe/Mg-Smectite", 4: "Olivine+Smectite",
           5: "Olv.Smect+2.2um", 6: "Carb.+2.2um", 7: "High-Ca Pyroxene",
           8: "Low-Ca Pyroxene", 9: "Kaolinite", 10: "Mg-Smectite 2"}
AJUSTE_MAX_M = 300.0    # si un punto cae en obstaculo, se mueve a la celda libre mas cercana
MAX_CANDIDATOS = 12     # candidatos que entran a la matriz de costos de la mision libre

# ---- Se carga una vez al arrancar (tarda unos segundos) ----
L = cargar()
COSTO = construir_costo(L)["costo"]
CANDIDATOS = candidatos_ciencia(L, COSTO, max_candidatos=1000)

app = FastAPI(title="Planificador Marswalk")


# Conversiones y validacion

def a_xy(celdas):
    """[(fila, col), ...] -> [[x, y], ...] en metros."""
    a = np.asarray(celdas)
    x, y = rc_a_xy(a[:, 0], a[:, 1])
    return np.round(np.c_[x, y], 1).tolist()


def celda_libre_cercana(celda, max_m=AJUSTE_MAX_M, res=20.0):
    """Celda transitable mas cercana a `celda` dentro de max_m, o None."""
    k = int(max_m // res)
    f0, c0 = celda
    n, m = COSTO.shape
    f1, f2, c1, c2 = max(0, f0 - k), min(n, f0 + k + 1), max(0, c0 - k), min(m, c0 + k + 1)
    ff, cc = np.mgrid[f1:f2, c1:c2]
    d = res * np.hypot(ff - f0, cc - c0)
    d[~np.isfinite(COSTO[f1:f2, c1:c2]) | (d > max_m)] = np.inf
    i = np.unravel_index(np.argmin(d), d.shape)
    if not np.isfinite(d[i]):
        return None
    return (int(ff[i]), int(cc[i])), float(d[i])


def a_celda(x, y, avisos):
    """Punto en metros -> celda transitable (ajustada si hace falta). Error 422 si no se puede."""
    f, c = xy_a_rc(np.array([x]), np.array([y]))
    f, c = int(f[0]), int(c[0])
    if not (0 <= f < COSTO.shape[0] and 0 <= c < COSTO.shape[1]):
        raise HTTPException(422, f"El punto ({x:.0f}, {y:.0f}) esta fuera del mapa.")
    if np.isfinite(COSTO[f, c]):
        return f, c
    ajuste = celda_libre_cercana((f, c))
    if ajuste is None:
        raise HTTPException(422, f"El punto ({x:.0f}, {y:.0f}) cae en terreno bloqueado "
                                 f"y no hay terreno libre a menos de {AJUSTE_MAX_M:.0f} m.")
    celda, d = ajuste
    avisos.append(f"El punto ({x:.0f}, {y:.0f}) caia en terreno bloqueado: se movio {d:.0f} m.")
    return celda


def objetivos_json(visitados):
    """Candidatos visitados -> lista para el visor (misma forma que rutas.json)."""
    salida = []
    for paso, v in enumerate(visitados, start=1):
        x, y = a_xy([v["celda"]])[0]
        salida.append({"parada": paso, "x": x, "y": y,
                       "mineral": NOMBRES.get(v["mineral"], str(v["mineral"])),
                       "area_ha": round(v["area_ha"], 1), "puntaje": round(v["puntaje"])})
    return salida


def resumen_mision(mision):
    camino = mision["camino"]
    return {"plan": a_xy(camino), "waypoints": a_xy(mision["waypoints"]),
            "costo": round(mision["costo_total"]),
            "km": round(float(distancia_acumulada(camino)[-1]) / 1000, 2)}


# Peticiones
class PedidoRuta(BaseModel):
    puntos: list[tuple[float, float]] = Field(min_length=2, max_length=10)  # [[x, y], ...] m


class PedidoLibre(BaseModel):
    inicio: tuple[float, float]                         # A [x, y] m
    fin: tuple[float, float]                            # B [x, y] m
    factor: float = Field(1.5, ge=1.0, le=3.0)          # presupuesto = factor x costo directo


class PedidoEva(BaseModel):
    habitat: tuple[float, float] | None = None        # None = el mejor centroide
    radio_m: float = Field(RADIO_M, gt=0, le=10000)
    esfuerzo: float = Field(ESFUERZO_MAX, gt=0, le=50000)


@app.get("/api/salud")
def salud():
    return {"ok": True, "forma": list(COSTO.shape), "candidatos": len(CANDIDATOS)}


@app.post("/api/ruta")
def ruta(p: PedidoRuta):
    """Une los puntos en orden con A* (como planear_mision)."""
    avisos = []
    celdas = [a_celda(x, y, avisos) for x, y in p.puntos]
    try:
        mision = planear_mision(COSTO, celdas)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {**resumen_mision(mision), "puntos": a_xy(celdas), "avisos": avisos}


@app.post("/api/libre")
def libre(p: PedidoLibre):
    """Mision libre A -> B: la ruta segura que pasa por la mayor ciencia sin pasarse del presupuesto
    (el mismo flujo que proto1_plan_estrategico.py, con A y B elegidos en el visor)."""
    avisos = []
    a = a_celda(*p.inicio, avisos)
    b = a_celda(*p.fin, avisos)
    if a == b:
        raise HTTPException(422, "El inicio y el final caen en la misma celda.")

    # Solo candidatos dentro de la elipse d(A,c) + d(c,B) <= factor * d(A,B), en linea recta:
    # los demas no caben en el presupuesto (el costo por metro casi nunca baja de 1).
    d_ab = 20.0 * np.hypot(a[0] - b[0], a[1] - b[1])
    def dentro(c):
        f, k = c["celda"]
        return 20.0 * (np.hypot(f - a[0], k - a[1]) + np.hypot(f - b[0], k - b[1])) <= p.factor * d_ab
    cerca = [c for c in CANDIDATOS if dentro(c)][:MAX_CANDIDATOS]   # ya vienen por puntaje

    nodos = [a, b] + [c["celda"] for c in cerca]
    M = matriz_costos(COSTO, nodos)
    if not np.isfinite(M[0, 1]):
        raise HTTPException(422, "No hay camino seguro entre A y B (pendientes de 20° o mas).")
    puntajes = [c["puntaje"] if np.isfinite(M[0, k + 2]) and np.isfinite(M[k + 2, 1]) else 0.0
                for k, c in enumerate(cerca)]
    M = np.where(np.isfinite(M), M, 1e12)                    # inalcanzable = carisimo
    orden, _, presupuesto = elegir_objetivos(M, puntajes, p.factor)
    mision = planear_mision(COSTO, [nodos[k] for k in orden])
    return {**resumen_mision(mision), "inicio": a_xy([a])[0], "fin": a_xy([b])[0],
            "objetivos": objetivos_json([cerca[k - 2] for k in orden[1:-1]]),
            "presupuesto": round(presupuesto), "costo_directo": round(float(M[0, 1])),
            "candidatos": len(cerca), "avisos": avisos}


@app.get("/api/aleatorios")
def aleatorios(n: int = 4, radio_m: float = RADIO_M, semilla: int | None = None):
    """n puntos al azar en terreno transitable, a menos de radio_m del aterrizaje.
    (Con todo el mapa las rutas pasan de 30 km y A* en Python tarda mas de 20 s.)"""
    if not 2 <= n <= 10:
        raise HTTPException(422, "n debe estar entre 2 y 10.")
    centro = tuple(int(v) for v in L["ruta_rc"][0])
    libres = np.argwhere(np.isfinite(COSTO) & (distancia_a(COSTO.shape, centro) <= radio_m))
    elegidas = np.random.default_rng(semilla).choice(len(libres), n, replace=False)
    return {"puntos": a_xy(libres[elegidas])}


@app.post("/api/eva")
def eva(p: PedidoEva):
    """Mision del astronauta: sale del habitat, no pasa del radio y regresa."""
    avisos = []
    if p.habitat is None:
        habitat, _ = mejor_centroide(COSTO, CANDIDATOS, p.radio_m)
        avisos.append("Habitat en el mejor centroide (mas ciencia dentro del radio).")
    else:
        habitat = a_celda(*p.habitat, avisos)
    r = planear_eva(COSTO, CANDIDATOS, habitat, p.radio_m, p.esfuerzo)
    datos = {"habitat": a_xy([habitat])[0], "radio_m": p.radio_m,
             "esfuerzo_max": p.esfuerzo, "avisos": avisos, "objetivos": []}
    if r["mision"] is None:
        avisos.append("Ningun objetivo alcanzable dentro del radio y el esfuerzo.")
        return datos
    camino = r["mision"]["camino"]
    datos.update(resumen_mision(r["mision"]))
    datos["esfuerzo"] = round(r["costo"])
    datos["max_alejamiento_m"] = round(max(20 * np.hypot(f - habitat[0], c - habitat[1])
                                           for f, c in camino))
    datos["objetivos"] = objetivos_json(r["visitados"])
    return datos