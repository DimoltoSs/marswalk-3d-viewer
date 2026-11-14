"""servidor.py - API local del planificador para el visor 3D.

Carga el mapa de costos una sola vez y responde rutas con A*.
Las misiones libre (A -> B) y EVA usan el planificador v3 + Marswalk v4 (mision_v3.py): arena de Séítah,
pendiente HiRISE, un mapa por agente y astronauta con modelo metabólico (oxígeno). Devuelven el frente de Pareto completo y cuatro
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
from eva import RADIO_M, distancia_a, mejor_centroide         # noqa: E402
from replaneo import distancia_acumulada                     # noqa: E402
import mision_v3 as v3                                       # noqa: E402

AJUSTE_MAX_M = 300.0    # si un punto cae en obstaculo, se mueve a la celda libre mas cercana
MAX_CANDIDATOS = 15     # candidatos que entran a la matriz de tramos de una mision
HORAS_EVA = 8.0         # soporte vital primario del traje EMU de la NASA: 8 h
O2_TRAJE_L = 380.0      # tanque primario del EMU: 0.54 kg de O2 ~ 380 L (estandar); la reserva de emergencia no se planea
RESERVA_O2 = 0.10       # limite duro: al volver debe quedar >= 10 % del tanque (si no, la mision se descarta)
ALERTA_O2 = 0.15        # < 15 % del tanque al volver = "poco" (rojo); las misiones con nombre exigen >= 15 %
HOLGADO_O2 = 0.25       # > 25 % = "de sobra" (verde); entre 15 y 25 % = "justo" (amarillo)
INTENSIDAD_MAX_LH = 85  # ~1600 BTU/h: maximo que el EMU alcanza a enfriar; arriba de eso, tramo marcado
PRIORIDADES = ("equilibrada", "ciencia", "rapida", "segura")

# ---- Se carga una vez al arrancar (tarda unos segundos) ----
L = cargar()
COSTO = construir_costo(L)["costo"]
# Marswalk v4: un mapa por agente. Rover: riesgo >= 15°, bloqueo >= 30° (P_ROVER). Astronauta: 10° y 20° (P).
# Ambos incluyen la arena de Séítah (textura HiRISE) y la pendiente fina HiRISE.
MAPAS = {"rover": v3.Mapa.desde_capas(L, p=v3.parametros(v3.ROVER)),
         "astronauta": v3.Mapa.desde_capas(L, p=v3.parametros(v3.ASTRONAUTA))}
CANDIDATOS = {k: v3.candidatos_ciencia(m, L) for k, m in MAPAS.items()}
MAPA, CANDIDATOS_V3 = MAPAS["rover"], CANDIDATOS["rover"]    # nombres de antes (rover)

app = FastAPI(title="Planificador Marswalk")


# Conversiones y validacion

def a_xy(celdas):
    """[(fila, col), ...] -> [[x, y], ...] en metros."""
    a = np.asarray(celdas)
    x, y = rc_a_xy(a[:, 0], a[:, 1])
    return np.round(np.c_[x, y], 1).tolist()


def celda_libre_cercana(celda, max_m=AJUSTE_MAX_M, res=20.0, costo=None):
    """Celda transitable mas cercana a `celda` dentro de max_m, o None."""
    costo = COSTO if costo is None else costo
    k = int(max_m // res)
    f0, c0 = celda
    n, m = costo.shape
    f1, f2, c1, c2 = max(0, f0 - k), min(n, f0 + k + 1), max(0, c0 - k), min(m, c0 + k + 1)
    ff, cc = np.mgrid[f1:f2, c1:c2]
    d = res * np.hypot(ff - f0, cc - c0)
    d[~np.isfinite(costo[f1:f2, c1:c2]) | (d > max_m)] = np.inf
    i = np.unravel_index(np.argmin(d), d.shape)
    if not np.isfinite(d[i]):
        return None
    return (int(ff[i]), int(cc[i])), float(d[i])


def a_celda(x, y, avisos, costo=None):
    """Punto en metros -> celda transitable (ajustada si hace falta). Error 422 si no se puede.
    `costo`: mapa con el que se valida (por defecto el de A*; las misiones v3 pasan el del agente)."""
    costo = COSTO if costo is None else costo
    f, c = xy_a_rc(np.array([x]), np.array([y]))
    f, c = int(f[0]), int(c[0])
    if not (0 <= f < COSTO.shape[0] and 0 <= c < COSTO.shape[1]):
        raise HTTPException(422, f"El punto ({x:.0f}, {y:.0f}) esta fuera del mapa.")
    if np.isfinite(costo[f, c]):
        return f, c
    ajuste = celda_libre_cercana((f, c), costo=costo)
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


def metricas_v3(m, agente):
    r = {"ciencia": round(m["ciencia"], 3), "horas": round(m["h"], 1),
         "wh": round(m["wh"]), "km": round(m["km"], 2),
         "riesgo_km": round(m["riesgo_km"], 3), "pend_max": round(m["pend_max"], 1),
         "esfuerzo": round(m["costo"])}
    if agente.metabolico:                 # astronauta: wh = energía metabólica -> oxígeno del traje
        r["o2_L"] = round(m["wh"] * v3.O2_L_POR_WH, 1)
    return r


def respuesta_v3(plan, prioridad, mapa, agente, con_waypoints=PRIORIDADES):
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
            "waypoints": a_xy(v3.simplificar(mapa, camino)) if i in con_wp else None,
            "objetivos": objetivos_v3(plan, m),
            "tramos_seguros": sum(p == "seguro" for p in m["perfiles"]),
            "metricas": metricas_v3(m, agente),
        })
    elegida = frente[plan["nombradas"][prioridad]]
    return {**elegida, "prioridad": prioridad, "frente": frente, "nombradas": plan["nombradas"],
            "presupuesto": {k: round(float(v), 1) for k, v in plan["presupuesto"].items()},
            "candidatos": len(plan["candidatos"]), "generaciones": plan["generaciones"],
            "segundos": plan["seg_total"], "km": elegida["metricas"]["km"],
            "umbrales": {"riesgo": mapa.params["pend_riesgo"], "bloqueo": mapa.params["pend_max"]},
            "energia": "metabolica" if agente.metabolico else "bateria",
            "aviso_plan": plan.get("aviso")}


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
    o2_L: float = Field(O2_TRAJE_L, gt=0, le=2000)       # oxigeno del traje (L); por defecto, el del EMU
    horas: float = Field(HORAS_EVA, gt=0, le=24)
    prioridad: str = Field("equilibrada", pattern="^(equilibrada|ciencia|rapida|segura)$")


@app.get("/api/salud")
def salud():
    return {"ok": True, "forma": list(COSTO.shape), "candidatos": {k: len(v) for k, v in CANDIDATOS.items()}}


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
    a = a_celda(*p.inicio, avisos, MAPAS["rover"].costo)
    b = a_celda(*p.fin, avisos, MAPAS["rover"].costo)
    if a == b:
        raise HTTPException(422, "El inicio y el final caen en la misma celda.")
    try:
        plan = v3.planear(MAPAS["rover"], CANDIDATOS["rover"], a, b, v3.ROVER, factor=p.factor,
                          max_candidatos=MAX_CANDIDATOS)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if len(plan["frente"]) == 1 and not plan["frente"][0]["seq"]:
        avisos.append("Ningun objetivo cabe en el presupuesto: ruta directa.")
    if plan.get("aviso"):
        avisos.append(plan["aviso"])
    return {**respuesta_v3(plan, p.prioridad, MAPAS["rover"], v3.ROVER), "inicio": a_xy([a])[0], "fin": a_xy([b])[0],
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
    """EVA de astronautas: sale del habitat, no pasa del radio y regresa (planificador v3 + Marswalk v4).
    Recursos de una persona: oxigeno del traje (sale del gasto metabolico) y horas de soporte vital.
    Ademas, en cada punto de la ruta: margen de O2 para volver al habitat e intensidad del esfuerzo."""
    avisos = []
    mapa, cands_v3 = MAPAS["astronauta"], CANDIDATOS["astronauta"]
    if p.habitat is None:
        cands = [{"celda": c["celda"], "puntaje": c["ciencia"]} for c in cands_v3]
        habitat, _ = mejor_centroide(mapa.costo, cands, p.radio_m)
        avisos.append("Habitat en el mejor centroide (mas ciencia dentro del radio).")
    else:
        habitat = a_celda(*p.habitat, avisos, mapa.costo)
    tanque_wh = p.o2_L / v3.O2_L_POR_WH
    plan = v3.planear(mapa, cands_v3, habitat, None, v3.ASTRONAUTA,
                      presupuesto={"h": p.horas, "wh": tanque_wh}, radio_m=p.radio_m,
                      max_candidatos=MAX_CANDIDATOS)
    datos = {"habitat": a_xy([habitat])[0], "radio_m": p.radio_m, "horas_max": p.horas,
             "o2_tanque_L": p.o2_L, "o2_usable_L": round(p.o2_L * (1 - RESERVA_O2), 1),
             "intensidad_max_ok_Lh": INTENSIDAD_MAX_LH, "avisos": avisos, "objetivos": [], "frente": []}
    if not plan["frente"]:
        avisos.append("Ningun objetivo alcanzable dentro del radio, las horas y el oxigeno.")
        return datos
    regreso = v3.costo_regreso(mapa, habitat, v3.ASTRONAUTA, radio_m=p.radio_m + 500)
    seg = [seguridad_eva(mapa, plan, m, regreso, tanque_wh, p.o2_L) for m in plan["frente"]]
    # La vida primero: las 4 misiones con nombre se eligen solo entre las que vuelven con >= 15 % del tanque.
    seguras = [i for i, s in enumerate(seg) if s["seguridad"]["tanque_final_pct"] >= 100 * ALERTA_O2]
    if seguras:
        sub = v3.nombrar([plan["frente"][i] for i in seguras])
        plan["nombradas"] = {k: seguras[i] for k, i in sub.items()}
    else:
        avisos.append("Ninguna mision vuelve con 15 % de oxigeno: se muestran las que dejan entre 10 y 15 %.")
    r = respuesta_v3(plan, p.prioridad, mapa, v3.ASTRONAUTA)
    hx, hy = datos["habitat"]
    for m_json, s in zip(r["frente"], seg):
        xy = np.asarray(m_json["plan"])
        m_json["metricas"]["max_alejamiento_m"] = round(float(np.hypot(xy[:, 0] - hx, xy[:, 1] - hy).max()))
        m_json.update(s)
        m_json["metricas"]["intensidad_max_Lh"] = max(m_json["intensidad_Lh"], default=0)
        m_json["metricas"]["tanque_final_pct"] = s["seguridad"]["tanque_final_pct"]
    datos["descartadas_justas"] = len(seg) - len(seguras)
    elegida = r["frente"][plan["nombradas"][p.prioridad]]
    r.update(elegida)                     # respuesta_v3 copio la elegida antes de agregarle la seguridad
    r["presupuesto"] = {"h": p.horas, "o2_L": datos["o2_usable_L"]}
    datos.update(r)
    if datos["no_retorno"] is not None:
        avisos.append("PELIGRO: hay un punto de la ruta desde el que ya no alcanza el oxigeno para volver.")
    datos["max_alejamiento_m"] = datos["metricas"]["max_alejamiento_m"]
    return datos


def seguridad_eva(mapa, plan, m, regreso, tanque_wh, tanque_L):
    """Por punto del camino: margen de O2 [L] = usable - (gastado + lo que cuesta volver al habitat desde ahi),
    e intensidad de la caminata [L/h de O2].
    punto_critico = el punto desde donde volver directo al habitat cuesta mas O2 (el mas comprometido).
    no_retorno = primer punto con margen negativo: desde ahi ya no alcanza para volver (None = nunca)."""
    rg = v3.regreso_mision(mapa, plan["tramos"], plan["problema"], m, regreso, tanque_wh, RESERVA_O2)
    margen = np.asarray(rg["margen_wh"], float) * v3.O2_L_POR_WH
    margen = np.where(np.isfinite(margen), margen, -1.0)
    a = np.asarray(rg["camino"])
    ag = v3.ASTRONAUTA
    dz = np.diff(mapa.dem[a[:, 0], a[:, 1]])
    dh = np.maximum(20.0 * np.hypot(*np.diff(a, axis=0).T), 1e-6)
    lento = (mapa.riesgo | mapa.duna)[a[1:, 0], a[1:, 1]]
    vel = np.where(lento, ag.vel_riesgo_m_h, ag.vel_seguro_m_h)
    arena = mapa.arena[a[1:, 0], a[1:, 1]] if mapa.arena is not None else np.zeros(len(dh), bool)
    eta = np.where(arena, ag.eta_arena, ag.eta_terreno)
    intensidad = v3.pandolf_w(ag, vel / 3600, 100 * dz / dh, eta) * v3.O2_L_POR_WH     # W -> L/h de O2
    volver = np.nan_to_num(np.asarray(rg["regreso_wh"], float)) * v3.O2_L_POR_WH
    critico = int(np.argmax(volver))
    tramo = np.hypot(dh, dz)
    # % del tanque que quedaria si desde cada punto se volviera directo al habitat (margen + reserva de 10 %)
    tanque_pct = 100 * (margen + RESERVA_O2 * tanque_L) / tanque_L
    return {"margen_L": np.round(margen, 1).tolist(), "tanque_pct": np.round(tanque_pct, 1).tolist(),
            "intensidad_Lh": np.round(intensidad, 1).tolist(),
            "punto_critico": critico, "no_retorno": rg["punto_no_retorno"],
            "seguridad": {"o2_volver_critico_L": round(float(volver[critico]), 1),
                          "margen_critico_L": round(float(margen[critico]), 1),
                          "sobrante_L": round(float(margen[-1] + RESERVA_O2 * tanque_L), 1),
                          "tanque_final_pct": round(float(tanque_pct[-1]), 1),
                          "tanque_min_pct": round(float(tanque_pct.min()), 1),
                          "intenso_pct": round(float(100 * tramo[intensidad > INTENSIDAD_MAX_LH].sum()
                                                     / max(tramo.sum(), 1e-9)), 1)}}
