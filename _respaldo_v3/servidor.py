"""servidor.py - API local del planificador para el visor 3D.

Carga el mapa de costos una sola vez y responde rutas con A*.
Las misiones libre (A -> B) y EVA usan el planificador v3 (mision_v3.py): modelo del notebook v2
(tiempo, energía, riesgo) + NSGA-II mejorado. Devuelven el frente de Pareto completo y cuatro
misiones con nombre (ciencia, rápida, segura, equilibrada) para elegir en el visor.
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
from proto1_planificador import planear_mision              # noqa: E402
from eva import ESFUERZO_MAX, RADIO_M, distancia_a, mejor_centroide  # noqa: E402
from replaneo import distancia_acumulada                     # noqa: E402
import mision_v3 as v3                                       # noqa: E402

AJUSTE_MAX_M = 300.0    # si un punto cae en obstaculo, se mueve a la celda libre mas cercana
MAX_CANDIDATOS = 15     # candidatos que entran a la matriz de tramos de una mision
HORAS_EVA = 8.0         # supuesto: duracion maxima de una salida a pie
PRIORIDADES = ("equilibrada", "ciencia", "rapida", "segura")

# ---- Se carga una vez al arrancar (tarda unos segundos) ----
L = cargar()
COSTO = construir_costo(L)["costo"]
MAPA = v3.Mapa.desde_capas(L)                 # mapa de costos v2 (sin ciencia) + riesgo y dunas
CANDIDATOS_V3 = v3.candidatos_ciencia(MAPA, L)

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


def objetivos_v3(plan, mision):
    """Objetivos de una mision v3 en orden de visita (misma forma que rutas_v2.json)."""
    pb = plan["problema"]
    salida = []
    for paso, k in enumerate(mision["seq"], start=1):
        c = plan["candidatos"][k - pb.primer]
        x, y = a_xy([c["celda"]])[0]
        salida.append({"parada": paso, "x": x, "y": y, "mineral": c["mineral"],
                       "area_ha": c["area_ha"], "ciencia": c["ciencia"],
                       "puntaje": round(100 * c["ciencia"])})
    return salida


def respuesta_v3(plan, prioridad, con_waypoints=PRIORIDADES):
    """Frente de Pareto -> JSON para el visor. Arriba van los datos de la mision `prioridad`
    (asi el visor viejo sigue funcionando); en "frente" van todas, para cambiar sin recalcular."""
    T, pb = plan["tramos"], plan["problema"]
    con_wp = {plan["nombradas"][n] for n in con_waypoints if n in plan["nombradas"]}
    frente = []
    for i, m in enumerate(plan["frente"]):
        camino = v3.camino_mision(T, pb, m)
        frente.append({
            "id": i,
            "plan": a_xy(camino),
            "waypoints": a_xy(v3.simplificar(MAPA, camino)) if i in con_wp else None,
            "objetivos": objetivos_v3(plan, m),
            "tramos_seguros": sum(p == "seguro" for p in m["perfiles"]),
            "metricas": {"ciencia": round(m["ciencia"], 3), "horas": round(m["h"], 1),
                         "wh": round(m["wh"]), "km": round(m["km"], 2),
                         "riesgo_km": round(m["riesgo_km"], 3), "pend_max": round(m["pend_max"], 1),
                         "esfuerzo": round(m["costo"])},
        })
    elegida = frente[plan["nombradas"][prioridad]]
    return {**elegida, "prioridad": prioridad, "frente": frente, "nombradas": plan["nombradas"],
            "presupuesto": {k: round(float(v), 1) for k, v in plan["presupuesto"].items()},
            "candidatos": len(plan["candidatos"]), "generaciones": plan["generaciones"],
            "segundos": plan["seg_total"], "km": elegida["metricas"]["km"]}


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
    factor: float = Field(1.5, ge=1.0, le=3.0)          # presupuesto = factor x (horas y Wh) directo
    prioridad: str = Field("equilibrada", pattern="^(equilibrada|ciencia|rapida|segura)$")


class PedidoEva(BaseModel):
    habitat: tuple[float, float] | None = None        # None = el mejor centroide
    radio_m: float = Field(RADIO_M, gt=0, le=10000)
    esfuerzo: float = Field(ESFUERZO_MAX, gt=0, le=50000)
    horas: float = Field(HORAS_EVA, gt=0, le=24)
    prioridad: str = Field("equilibrada", pattern="^(equilibrada|ciencia|rapida|segura)$")


@app.get("/api/salud")
def salud():
    return {"ok": True, "forma": list(COSTO.shape), "candidatos": len(CANDIDATOS_V3)}


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
    """Mision libre A -> B del rover: frente de Pareto (ciencia, tiempo, riesgo) que cabe en
    factor x (horas y energia) de la ruta directa. Planificador v3 (mision_v3.py)."""
    avisos = []
    a = a_celda(*p.inicio, avisos)
    b = a_celda(*p.fin, avisos)
    if a == b:
        raise HTTPException(422, "El inicio y el final caen en la misma celda.")
    try:
        plan = v3.planear(MAPA, CANDIDATOS_V3, a, b, v3.ROVER, factor=p.factor,
                          max_candidatos=MAX_CANDIDATOS)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if len(plan["frente"]) == 1 and not plan["frente"][0]["seq"]:
        avisos.append("Ningun objetivo cabe en el presupuesto: ruta directa.")
    return {**respuesta_v3(plan, p.prioridad), "inicio": a_xy([a])[0], "fin": a_xy([b])[0],
            "factor": p.factor, "avisos": avisos}


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
    """Mision del astronauta: sale del habitat, no pasa del radio y regresa (planificador v3)."""
    avisos = []
    if p.habitat is None:
        cands = [{"celda": c["celda"], "puntaje": c["ciencia"]} for c in CANDIDATOS_V3]
        habitat, _ = mejor_centroide(MAPA.costo, cands, p.radio_m)
        avisos.append("Habitat en el mejor centroide (mas ciencia dentro del radio).")
    else:
        habitat = a_celda(*p.habitat, avisos)
    plan = v3.planear(MAPA, CANDIDATOS_V3, habitat, None, v3.ASTRONAUTA,
                      presupuesto={"h": p.horas, "costo": p.esfuerzo}, radio_m=p.radio_m,
                      max_candidatos=MAX_CANDIDATOS)
    datos = {"habitat": a_xy([habitat])[0], "radio_m": p.radio_m, "esfuerzo_max": p.esfuerzo,
             "horas_max": p.horas, "avisos": avisos, "objetivos": [], "frente": []}
    if not plan["frente"]:
        avisos.append("Ningun objetivo alcanzable dentro del radio, las horas y el esfuerzo.")
        return datos
    r = respuesta_v3(plan, p.prioridad)
    for m in r["frente"]:
        xy = np.asarray(m["plan"])
        hx, hy = datos["habitat"]
        m["metricas"]["max_alejamiento_m"] = round(float(np.hypot(xy[:, 0] - hx, xy[:, 1] - hy).max()))
    datos.update(r)
    datos["esfuerzo"] = r["metricas"]["esfuerzo"]
    datos["max_alejamiento_m"] = r["metricas"]["max_alejamiento_m"]
    return datos
