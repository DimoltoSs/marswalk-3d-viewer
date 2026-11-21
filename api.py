"""api.py - Servicio HTTP del planificador v3 (la "estación base").

La Raspberry Pi (rover) no corre el genético: manda su posición y destino y recibe waypoints.
El mapa y los candidatos se cargan UNA vez al arrancar; cada plan tarda ~5-20 s.

Arrancar (desde esta carpeta):
    uvicorn api:app --host 0.0.0.0 --port 8000
o con Docker:
    docker compose up -d --build

Coordenadas: metros locales (x, y) del mapa de Jezero, las mismas de rutas_v3.json
(x = este, y = norte, origen en 18.43N 77.43E).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from collections import OrderedDict
from typing import Literal

import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from proto1_capas import cargar, rc_a_xy, xy_a_rc  # noqa: E402

import mision_v3 as v3  # noqa: E402

API_KEY = os.environ.get("API_KEY", "")          # vacío = sin clave (red local de confianza)
MAX_CACHE = 32
AGENTES = {"rover": v3.ROVER, "astronauta": v3.ASTRONAUTA}

# ------------------------------------------------------------------ estado global (se carga 1 vez)
print("cargando capas y mapa de costos...", flush=True)
_t0 = time.perf_counter()
L = cargar()


def _params(agente):
    # Marswalk v4: el rover usa P_ROVER (bloqueo 30°) y el astronauta P (20°). Antes de v4 solo existe P.
    return v3.parametros(agente) if hasattr(v3, "parametros") else v3.P


MAPAS, CANDIDATOS = {}, {}
for _nombre, _ag in AGENTES.items():
    MAPAS[_nombre] = v3.Mapa.desde_capas(L, p=_params(_ag))
    CANDIDATOS[_nombre] = v3.candidatos_ciencia(MAPAS[_nombre], L)
MAPA = MAPAS["rover"]
FILAS, COLS = MAPA.forma
print(f"listo en {time.perf_counter() - _t0:.1f} s · " +
      " · ".join(f"{k}: {len(v)} candidatos" for k, v in CANDIDATOS.items()), flush=True)

_candado = threading.Lock()      # un plan a la vez: el genético usa un núcleo completo
_cache: OrderedDict[str, dict] = OrderedDict()

app = FastAPI(title="Planificador Marswalk v3", version="1.0")


# ------------------------------------------------------------------ modelos de entrada
class Pedido(BaseModel):
    inicio: tuple[float, float] = Field(..., description="posición actual (x, y) en metros")
    meta: tuple[float, float] | None = Field(None, description="destino (x, y); null = ida y vuelta")
    agente: Literal["rover", "astronauta"] = "rover"
    prioridad: Literal["ciencia", "rapida", "segura", "equilibrada", "pesos"] = "equilibrada"
    factor: float | None = Field(2.0, gt=1.0, description="presupuesto = factor x ruta directa (A->B)")
    horas: float | None = Field(None, gt=0, description="presupuesto en horas (obligatorio si meta es null)")
    radio_m: float | None = Field(None, gt=0, description="radio máximo en misión de ida y vuelta")
    max_candidatos: int = Field(15, ge=1, le=30)
    semilla: int = 42
    camino_completo: bool = Field(False, description="incluir todas las celdas además de los waypoints")


class Replaneo(Pedido):
    visitados: list[tuple[float, float]] = Field(default_factory=list,
                                                 description="objetivos ya estudiados (x, y): no se repiten")


# ------------------------------------------------------------------ utilidades
def _clave(_x_api_key: str | None = Header(None, alias="X-API-Key")):
    if API_KEY and _x_api_key != API_KEY:
        raise HTTPException(401, "X-API-Key inválida")


def _a_celda(xy, nombre, mapa=None):
    mapa = mapa or MAPA
    f, c = (int(v) for v in xy_a_rc(xy[0], xy[1]))
    if not (0 <= f < FILAS and 0 <= c < COLS):
        raise HTTPException(422, f"{nombre} {xy} está fuera del mapa")
    if mapa.bloqueado[f, c]:
        pmax = (getattr(mapa, "params", None) or v3.P)["pend_max"]
        raise HTTPException(422, f"{nombre} {xy} cae en terreno bloqueado (pendiente >= {pmax:g}°)")
    return f, c


def _a_xy(celdas):
    a = np.asarray(celdas)
    x, y = rc_a_xy(a[:, 0], a[:, 1])
    return np.round(np.c_[x, y], 1).tolist()


O2_L_POR_WH = getattr(v3, "O2_L_POR_WH", 3600 / 20100)   # 20.1 kJ por litro de O2 (Marswalk v4)


def _es_metabolico(agente):
    return getattr(agente, "metabolico", False)


def _resumen(m, agente=None):
    r = {"ciencia": round(float(m["ciencia"]), 3), "horas": round(float(m["h"]), 1),
         "wh": round(float(m["wh"])), "km": round(float(m["km"]), 2),
         "riesgo_km": round(float(m["riesgo_km"]), 3), "pend_max": round(float(m["pend_max"]), 1),
         "objetivos": len(m["seq"])}
    if _es_metabolico(agente):          # astronauta: lo que limita la EVA es el oxígeno del traje
        r["o2_L"] = round(float(m["wh"]) * O2_L_POR_WH, 1)
    return r


def _planear(p: Pedido, excluir=()):
    mapa, agente = MAPAS[p.agente], AGENTES[p.agente]
    inicio = _a_celda(p.inicio, "inicio", mapa)
    meta = _a_celda(p.meta, "meta", mapa) if p.meta is not None else None
    if meta is None and p.horas is None:
        raise HTTPException(422, "una misión de ida y vuelta (meta = null) necesita 'horas'")

    excluir = {tuple(int(v) for v in xy_a_rc(xy[0], xy[1])) for xy in excluir}
    cands = [c for c in CANDIDATOS[p.agente]
             if not any(abs(c["celda"][0] - f) <= 2 and abs(c["celda"][1] - k) <= 2 for f, k in excluir)]

    clave = hashlib.sha1(json.dumps([p.model_dump(), sorted(excluir)], sort_keys=True,
                                    default=str).encode()).hexdigest()
    if clave in _cache:
        _cache.move_to_end(clave)
        return {**_cache[clave], "cache": True}

    try:
        plan = v3.planear(mapa, cands, inicio, meta, agente,
                          presupuesto={"h": p.horas} if p.horas else None,
                          factor=p.factor if meta is not None else None,
                          radio_m=p.radio_m, max_candidatos=p.max_candidatos,
                          op=v3.OpcionesGA(semilla=p.semilla))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e

    T, pb, frente = plan["tramos"], plan["problema"], plan["frente"]
    if not frente:
        raise HTTPException(422, plan.get("aviso") or "ninguna misión cabe en el presupuesto")
    if p.prioridad == "pesos":
        i = v3.elegir(frente, {"ciencia": 0.5, "tiempo": 0.3, "riesgo": 0.2})
    else:
        i = plan["nombradas"][p.prioridad]
    m = frente[i]
    camino = v3.camino_mision(T, pb, m)

    resp = {
        "prioridad": p.prioridad,
        "waypoints": _a_xy(v3.simplificar(mapa, camino)),
        "objetivos": [{"parada": n + 1, "x": xy[0], "y": xy[1], "mineral": c["mineral"],
                       "ciencia": round(float(c["ciencia"]), 3)}
                      for n, k in enumerate(m["seq"])
                      for c in [plan["candidatos"][k - pb.primer]]
                      for xy in [_a_xy([c["celda"]])[0]]],
        "metricas": _resumen(m, agente),
        "energia": "metabolica (Wh); oxigeno en o2_L" if _es_metabolico(agente) else "bateria (Wh)",
        "aviso": plan.get("aviso"),
        "presupuesto": {k: round(float(v), 1) for k, v in plan["presupuesto"].items()},
        "alternativas": {n: _resumen(frente[j], agente) for n, j in plan["nombradas"].items()},
        "planificador": {"generaciones": plan["generaciones"], "segundos": plan["seg_total"],
                         "frente": len(frente)},
    }
    if _es_metabolico(agente) and "wh" in resp["presupuesto"]:
        resp["presupuesto"]["o2_L"] = round(resp["presupuesto"]["wh"] * O2_L_POR_WH, 1)
    if p.camino_completo:
        resp["camino"] = _a_xy(camino)

    _cache[clave] = resp
    if len(_cache) > MAX_CACHE:
        _cache.popitem(last=False)
    return {**resp, "cache": False}


# ------------------------------------------------------------------ endpoints
@app.get("/salud")
def salud():
    return {"ok": True, "ocupado": _candado.locked(), "candidatos": {k: len(v) for k, v in CANDIDATOS.items()},
            "mapa": {"filas": FILAS, "columnas": COLS, "res_m": float(L["res_m"])}}


@app.post("/planear", dependencies=[Depends(_clave)])
def planear(p: Pedido):
    # FastAPI corre las funciones normales (def) en un hilo aparte: el servidor sigue respondiendo /salud
    with _candado:
        return _planear(p)


@app.post("/replanear", dependencies=[Depends(_clave)])
def replanear(p: Replaneo):
    """Igual que /planear, desde la posición actual y sin repetir objetivos ya estudiados."""
    with _candado:
        return _planear(p, excluir=p.visitados)


@app.get("/ejemplo")
def ejemplo():
    """Inicio y meta de la ruta real de Perseverance, para probar sin conocer coordenadas."""
    ini, fin = L["ruta_xy_m"][0], L["ruta_xy_m"][-1]
    return {"inicio": [round(float(ini[0]), 1), round(float(ini[1]), 1)],
            "meta": [round(float(fin[0]), 1), round(float(fin[1]), 1)]}
