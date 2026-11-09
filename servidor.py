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
from proto1_objetivos import candidatos_ciencia              # noqa: E402
from proto1_planificador import planear_mision               # noqa: E402
from eva import ESFUERZO_MAX, RADIO_M, distancia_a, mejor_centroide, planear_eva  # noqa: E402
from replaneo import distancia_acumulada                     # noqa: E402

NOMBRES = {1: "Olivine", 2: "Mg-Carbonate", 3: "Fe/Mg-Smectite", 4: "Olivine+Smectite",
           5: "Olv.Smect+2.2um", 6: "Carb.+2.2um", 7: "High-Ca Pyroxene",
           8: "Low-Ca Pyroxene", 9: "Kaolinite", 10: "Mg-Smectite 2"}
AJUSTE_MAX_M = 300.0    # si un punto cae en obstaculo, se mueve a la celda libre mas cercana

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


def resumen_mision(mision):
    camino = mision["camino"]
    return {"plan": a_xy(camino), "waypoints": a_xy(mision["waypoints"]),
            "costo": round(mision["costo_total"]),
            "km": round(float(distancia_acumulada(camino)[-1]) / 1000, 2)}


# Peticiones
class PedidoRuta(BaseModel):
    puntos: list[tuple[float, float]] = Field(min_length=2, max_length=10)  # [[x, y], ...] m


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
    for paso, v in enumerate(r["visitados"], start=1):
        x, y = a_xy([v["celda"]])[0]
        datos["objetivos"].append({"parada": paso, "x": x, "y": y,
                                   "mineral": NOMBRES.get(v["mineral"], str(v["mineral"])),
                                   "area_ha": round(v["area_ha"], 1), "puntaje": round(v["puntaje"])})
    return datos