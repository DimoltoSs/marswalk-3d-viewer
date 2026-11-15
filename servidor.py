"""servidor.py - API local del planificador para el visor 3D.

Carga el mapa de costos una sola vez y responde rutas con A*.
Las misiones libre (A -> B) y EVA usan el planificador v3 + Marswalk v4 (mision_v3.py): arena de Séítah,
pendiente HiRISE, un mapa por agente y astronauta con modelo metabólico (oxígeno). Devuelven el frente de Pareto completo y cuatro
misiones con nombre (ciencia, rápida, segura, equilibrada) para elegir en el visor.
Varios lugares (sitios.py): cada petición lleva ?sitio=jezero|gale; todos usan el mismo modelo y los mismos scripts.
Arrancar (desde visor_3d):  python -m uvicorn servidor:app --port 8000
Probar a mano:              http://localhost:8000/docs
"""
import os
import sys
from functools import lru_cache
from types import SimpleNamespace

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "prototipo_uno"))
from proto1_capas import rc_a_xy, xy_a_rc                    # noqa: E402
from proto1_mapa_costos import construir_costo               # noqa: E402
from proto1_planificador import planear_mision              # noqa: E402
from eva import RADIO_M, distancia_a, mejor_centroide         # noqa: E402
from replaneo import distancia_acumulada                     # noqa: E402
import mision_v3 as v3                                       # noqa: E402
import sitios                                                # noqa: E402
import eva_avanzada as ea                                    # noqa: E402
from dataclasses import replace                              # noqa: E402
from datetime import date                                    # noqa: E402

AJUSTE_MAX_M = 300.0    # si un punto cae en obstaculo, se mueve a la celda libre mas cercana
MAX_CANDIDATOS = 15     # candidatos que entran a la matriz de tramos de una mision
HORAS_EVA = 8.0         # soporte vital primario del traje EMU de la NASA: 8 h
O2_TRAJE_L = 380.0      # tanque primario del EMU: 0.54 kg de O2 ~ 380 L (estandar); la reserva de emergencia no se planea
RESERVA_O2 = 0.10       # limite duro: al volver debe quedar >= 10 % del tanque (si no, la mision se descarta)
ALERTA_O2 = 0.15        # < 15 % del tanque al volver = "poco" (rojo); las misiones con nombre exigen >= 15 %
HOLGADO_O2 = 0.25       # > 25 % = "de sobra" (verde); entre 15 y 25 % = "justo" (amarillo)
INTENSIDAD_MAX_LH = 85  # ~1600 BTU/h: maximo que el EMU alcanza a enfriar; arriba de eso, tramo marcado
PRIORIDADES = ("equilibrada", "ciencia", "rapida", "segura")

# ---- Cada sitio se carga una vez, la primera vez que se pide (tarda unos segundos) ----
@lru_cache(maxsize=None)
def _cargar_sitio(nombre):
    L = sitios.cargar(nombre)
    # Marswalk v4: un mapa por agente. Rover: riesgo >= 15°, bloqueo >= 30° (P_ROVER). Astronauta: 10° y 20° (P).
    # Ambos incluyen la arena (textura HiRISE) y, donde existe, la pendiente fina HiRISE.
    mapas = {"rover": v3.Mapa.desde_capas(L, p=v3.parametros(v3.ROVER)),
             "astronauta": v3.Mapa.desde_capas(L, p=v3.parametros(v3.ASTRONAUTA))}
    # Mapa de A* (/api/ruta y puntos aleatorios): en Jezero el de prototipo_uno; en los demás, el del rover v4.
    costo = construir_costo(L)["costo"] if nombre == "jezero" else mapas["rover"].costo
    ruta = L.get("ruta_rc")
    centro = tuple(int(v) for v in ruta[0]) if ruta is not None and len(ruta) else (costo.shape[0] // 2, costo.shape[1] // 2)
    return SimpleNamespace(nombre=nombre, L=L, costo=costo, mapas=mapas, centro=centro,
                           candidatos={k: v3.candidatos_ciencia(m, L) for k, m in mapas.items()})


def datos_sitio(nombre):
    if nombre not in sitios.SITIOS:
        raise HTTPException(404, f"Sitio desconocido: {nombre}. Opciones: {', '.join(sitios.SITIOS)}.")
    return _cargar_sitio(nombre)


datos_sitio("jezero")       # Jezero queda listo al arrancar; los demás se cargan al primer uso

app = FastAPI(title="Planificador Marswalk")


# Conversiones y validacion

def a_xy(celdas):
    """[(fila, col), ...] -> [[x, y], ...] en metros."""
    a = np.asarray(celdas)
    x, y = rc_a_xy(a[:, 0], a[:, 1])
    return np.round(np.c_[x, y], 1).tolist()


def celda_libre_cercana(celda, costo, max_m=AJUSTE_MAX_M, res=20.0):
    """Celda transitable mas cercana a `celda` dentro de max_m, o None."""
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


def a_celda(x, y, avisos, costo):
    """Punto en metros -> celda transitable (ajustada si hace falta). Error 422 si no se puede.
    `costo`: mapa con el que se valida (el de A* del sitio, o el del agente en las misiones v3)."""
    f, c = xy_a_rc(np.array([x]), np.array([y]))
    f, c = int(f[0]), int(c[0])
    if not (0 <= f < costo.shape[0] and 0 <= c < costo.shape[1]):
        raise HTTPException(422, f"El punto ({x:.0f}, {y:.0f}) esta fuera del mapa.")
    if np.isfinite(costo[f, c]):
        return f, c
    ajuste = celda_libre_cercana((f, c), costo)
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


class Astronauta(BaseModel):
    masa_kg: float = Field(80.0, ge=40, le=150)          # persona, sin traje
    o2_L: float = Field(O2_TRAJE_L, gt=0, le=2000)       # oxígeno de su traje (L)


class PedidoEva(BaseModel):
    habitat: tuple[float, float] | None = None        # None = el mejor centroide
    radio_m: float = Field(RADIO_M, gt=0, le=10000)
    o2_L: float | None = Field(None, gt=0, le=2000)      # (compatibilidad) mismo O2 para los dos
    pareja: list[Astronauta] = Field(default_factory=lambda: [Astronauta(masa_kg=80), Astronauta(masa_kg=70)],
                                     min_length=2, max_length=2)
    horas: float = Field(HORAS_EVA, gt=0, le=24)
    evitar_sin_senal: bool = True                      # la ruta evita (si puede) las zonas sin radio
    fecha: date | None = None                          # día terrestre (None = hoy) -> estación de Marte
    hora_salida: float = Field(9.0, ge=0, lt=24)       # hora solar local de salida (12 = mediodía)
    prioridad: str = Field("equilibrada", pattern="^(equilibrada|ciencia|rapida|segura)$")


@app.get("/api/sitios")
def lista_sitios():
    return {"sitios": [{"id": k, **v} for k, v in sitios.SITIOS.items()]}


@app.get("/api/salud")
def salud(sitio: str = "jezero"):
    s = datos_sitio(sitio)
    return {"ok": True, "sitio": sitio, "forma": list(s.costo.shape),
            "candidatos": {k: len(v) for k, v in s.candidatos.items()}}


@app.post("/api/ruta")
def ruta(p: PedidoRuta, sitio: str = "jezero"):
    """Une los puntos en orden con A* (como planear_mision)."""
    s = datos_sitio(sitio)
    avisos = []
    celdas = [a_celda(x, y, avisos, s.costo) for x, y in p.puntos]
    try:
        mision = planear_mision(s.costo, celdas)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {**resumen_mision(mision), "puntos": a_xy(celdas), "avisos": avisos}


@app.post("/api/libre")
def libre(p: PedidoLibre, sitio: str = "jezero"):
    """Mision libre A -> B del rover: frente de Pareto (ciencia, tiempo, riesgo) que cabe en
    factor x (horas y energia) de la ruta directa. Planificador v3 (mision_v3.py)."""
    s = datos_sitio(sitio)
    mapa, cands = s.mapas["rover"], s.candidatos["rover"]
    avisos = []
    a = a_celda(*p.inicio, avisos, mapa.costo)
    b = a_celda(*p.fin, avisos, mapa.costo)
    if a == b:
        raise HTTPException(422, "El inicio y el final caen en la misma celda.")
    try:
        plan = v3.planear(mapa, cands, a, b, v3.ROVER, factor=p.factor,
                          max_candidatos=MAX_CANDIDATOS)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if len(plan["frente"]) == 1 and not plan["frente"][0]["seq"]:
        avisos.append("Ningun objetivo cabe en el presupuesto: ruta directa.")
    if plan.get("aviso"):
        avisos.append(plan["aviso"])
    return {**respuesta_v3(plan, p.prioridad, mapa, v3.ROVER), "inicio": a_xy([a])[0], "fin": a_xy([b])[0],
            "factor": p.factor, "avisos": avisos}


@app.get("/api/aleatorios")
def aleatorios(n: int = 4, radio_m: float = RADIO_M, semilla: int | None = None, sitio: str = "jezero"):
    """n puntos al azar en terreno transitable, a menos de radio_m del aterrizaje.
    (Con todo el mapa las rutas pasan de 30 km y A* en Python tarda mas de 20 s.)"""
    if not 2 <= n <= 10:
        raise HTTPException(422, "n debe estar entre 2 y 10.")
    s = datos_sitio(sitio)
    libres = np.argwhere(np.isfinite(s.costo) & (distancia_a(s.costo.shape, s.centro) <= radio_m))
    elegidas = np.random.default_rng(semilla).choice(len(libres), n, replace=False)
    return {"puntos": a_xy(libres[elegidas])}


@app.post("/api/eva")
def eva(p: PedidoEva, sitio: str = "jezero"):
    """EVA en pareja: dos astronautas salen del hábitat, no pasan del radio y regresan (planificador v3 + Marswalk v4).
    Se planea con el más limitado de los dos; cada punto de la ruta se revisa con: O2 de cada uno para volver,
    rescate si uno se lesiona (eva_avanzada.py), señal de radio con el hábitat y luz del Sol a esa hora."""
    s = datos_sitio(sitio)
    avisos = []
    base, cands_v3 = s.mapas["astronauta"], s.candidatos["astronauta"]
    if p.o2_L is not None:
        for a in p.pareja:
            a.o2_L = p.o2_L
    if p.habitat is None:
        cands = [{"celda": c["celda"], "puntaje": c["ciencia"]} for c in cands_v3]
        habitat, _ = mejor_centroide(base.costo, cands, p.radio_m)
        avisos.append("Habitat en el mejor centroide (mas ciencia dentro del radio).")
    else:
        habitat = a_celda(*p.habitat, avisos, base.costo)

    # ---- Luz: el Sol limita la duración ----
    lat = sitios.SITIOS[sitio]["lat"]
    dia = p.fecha or date.today()
    ls, dec = ea.declinacion_sol(dia)
    amanecer, ocaso = ea.horas_de_luz(lat, dec)
    salida = p.hora_salida
    if salida < amanecer:
        avisos.append(f"A las {salida:.1f} h aún es de noche: la salida se movió al amanecer ({amanecer:.1f} h).")
        salida = amanecer
    luz_h = (ocaso - salida) * ea.HORA_MARCIANA_H
    if luz_h < 0.5:
        raise HTTPException(422, f"Queda menos de media hora de luz (el Sol se pone a las {ocaso:.1f} h).")
    horas = min(p.horas, luz_h)
    if horas < p.horas:
        avisos.append(f"Solo quedan {luz_h:.1f} h de luz: la EVA se limita a eso (no a {p.horas:g} h).")

    # ---- Pareja: se planea con el más limitado ----
    pareja = [{"agente": ea.astronauta(a.masa_kg), "o2_L": a.o2_L, "masa_kg": a.masa_kg} for a in p.pareja]
    w, presupuesto_wh = ea.presupuesto_pareja(pareja)
    ag = pareja[w]["agente"]
    tanques_wh = [q["o2_L"] / v3.O2_L_POR_WH for q in pareja]

    # ---- Radio ----
    cobertura = ea.cobertura_radio(base, habitat, p.radio_m)
    mapa = ea.con_radio(base, cobertura) if p.evitar_sin_senal else base

    plan = v3.planear(mapa, cands_v3, habitat, None, ag, presupuesto={"h": horas, "wh": presupuesto_wh},
                      radio_m=p.radio_m, max_candidatos=MAX_CANDIDATOS)
    datos = {"habitat": a_xy([habitat])[0], "radio_m": p.radio_m, "horas_max": round(horas, 2),
             "o2_tanque_L": pareja[w]["o2_L"], "o2_usable_L": round(pareja[w]["o2_L"] * (1 - RESERVA_O2), 1),
             "intensidad_max_ok_Lh": INTENSIDAD_MAX_LH, "avisos": avisos, "objetivos": [], "frente": [],
             "pareja_info": [{"masa_kg": q["masa_kg"], "o2_L": q["o2_L"]} for q in pareja], "gasta_mas": w,
             "luz": {"fecha": dia.isoformat(), "ls": round(ls, 1), "declinacion": round(dec, 2),
                     "amanecer": round(amanecer, 2), "ocaso": round(ocaso, 2), "salida": round(salida, 2)},
             "radio": {"antena_habitat_m": ea.ANTENA_HABITAT_M, "antena_traje_m": ea.ANTENA_TRAJE_M,
                       "evita_sin_senal": p.evitar_sin_senal}}
    el0, az0 = ea.sol(lat, dec, salida)
    datos["luz"]["sol_salida"] = {"elev": round(float(el0), 1), "azimut": round(float(az0), 1)}
    if not plan["frente"]:
        avisos.append("Ningun objetivo alcanzable dentro del radio, las horas y el oxigeno.")
        return datos

    rmax = p.radio_m + 500
    reg = ea.regresos(base, habitat, {0: pareja[0]["agente"], 1: pareja[1]["agente"]}, rmax)
    asist = ea.regresos(base, habitat, {
        "ayuda0": replace(pareja[0]["agente"], kit_kg=pareja[0]["agente"].kit_kg + ea.CARGA_AYUDA_KG),
        "ayuda1": replace(pareja[1]["agente"], kit_kg=pareja[1]["agente"].kit_kg + ea.CARGA_AYUDA_KG),
        "herido0": pareja[0]["agente"], "herido1": pareja[1]["agente"]}, rmax, ea.VEL_ASISTIDA)
    ctx = dict(base=base, pareja=pareja, w=w, tanques_wh=tanques_wh, reg=reg, asist=asist, horas=horas,
               cobertura=cobertura, lat=lat, dec=dec, salida=salida)
    seg = [evaluar_eva(plan, m, ctx) for m in plan["frente"]]
    # Límite duro: si alguno de los dos volvería con menos del 10 % de su tanque, la misión no existe.
    vivas = [i for i, x in enumerate(seg) if x["seguridad"]["tanque_final_pct"] >= 100 * RESERVA_O2]
    if len(vivas) < len(seg):
        avisos.append(f"{len(seg) - len(vivas)} mision(es) descartadas: uno de los dos volveria con menos de 10 % de O2.")
    if not vivas:
        avisos.append("Ninguna mision deja a los dos con 10 % de oxigeno: acerca el habitat o sube el O2.")
        return datos
    plan["frente"] = [plan["frente"][i] for i in vivas]
    seg = [seg[i] for i in vivas]
    plan["nombradas"] = v3.nombrar(plan["frente"])

    # La vida primero: las 4 misiones con nombre se eligen entre las que (1) dejan >= 15 % de O2 a los dos y
    # (2) permiten volver con un compañero lesionado desde cualquier punto. Si ninguna cumple (2), se relaja.
    o2_ok = [i for i, x in enumerate(seg) if x["seguridad"]["tanque_final_pct"] >= 100 * ALERTA_O2]
    seguras = [i for i in o2_ok if seg[i]["sin_rescate"] is None]
    if not seguras and o2_ok:
        seguras = o2_ok
        avisos.append("Ninguna mision permite volver con un companero lesionado desde todos los puntos: "
                      "se muestran las que cumplen el oxigeno (ver el tramo sin rescate).")
    if seguras:
        sub = v3.nombrar([plan["frente"][i] for i in seguras])
        plan["nombradas"] = {k: seguras[i] for k, i in sub.items()}
    else:
        avisos.append("Ninguna mision vuelve con 15 % de oxigeno: se muestran las que dejan entre 10 y 15 %.")
    r = respuesta_v3(plan, p.prioridad, mapa, ag)
    con_detalle = set(plan["nombradas"].values())
    hx, hy = datos["habitat"]
    for i, (m_json, x) in enumerate(zip(r["frente"], seg)):
        xy = np.asarray(m_json["plan"])
        m_json["metricas"]["max_alejamiento_m"] = round(float(np.hypot(xy[:, 0] - hx, xy[:, 1] - hy).max()))
        m_json["metricas"]["intensidad_max_Lh"] = max(x["intensidad_Lh"], default=0)
        m_json["metricas"]["tanque_final_pct"] = x["seguridad"]["tanque_final_pct"]
        justo = min(range(2), key=lambda k: x["pareja"][k]["tanque_final_pct"])     # quien vuelve con menos
        m_json["metricas"]["o2_L"] = x["pareja"][justo]["o2_usado_L"]
        m_json["metricas"]["o2_usable_L"] = round(pareja[justo]["o2_L"] * (1 - RESERVA_O2), 1)
        if i not in con_detalle:          # los arreglos por punto solo hacen falta en las misiones que se dibujan
            x = {k: v for k, v in x.items() if k in ("seguridad", "pareja", "sin_rescate", "no_retorno")}
            m_json["plan"] = None
        m_json.update(x)
    datos["descartadas_justas"] = len(seg) - len(seguras)
    elegida = r["frente"][plan["nombradas"][p.prioridad]]
    r.update(elegida)
    r["presupuesto"] = {"h": round(horas, 2), "o2_L": datos["o2_usable_L"]}
    datos.update(r)
    if datos["no_retorno"] is not None:
        avisos.append("PELIGRO: hay un punto de la ruta desde el que ya no alcanza el oxigeno para volver.")
    datos["max_alejamiento_m"] = datos["metricas"]["max_alejamiento_m"]
    return datos


def evaluar_eva(plan, m, c):
    """Revisa una misión punto por punto. Oxígeno: para cada astronauta, margen = usable - (gastado + volver al
    hábitat desde ahí); en la ruta se muestra el peor de los dos. Además rescate, radio y luz (eva_avanzada.py).
    punto_critico = desde donde volver cuesta más O2; no_retorno = primer punto sin O2 para volver (None = nunca)."""
    base, pareja, w = c["base"], c["pareja"], c["w"]
    T, pb = plan["tramos"], plan["problema"]
    rg = v3.regreso_mision(base, T, pb, m, {"wh": c["reg"][w]}, c["tanques_wh"][w], RESERVA_O2)    # quien más gasta
    camino, paradas = rg["camino"], rg["paradas"]
    perfiles = {}
    for k, q in enumerate(pareja):
        perfiles[k] = rg if k == w else v3.perfil_regreso(base, camino, {"wh": c["reg"][k]}, q["agente"],
                                                          c["tanques_wh"][k], RESERVA_O2, paradas)
    tanque_pct, margen_L, por_persona = None, None, []
    for k, q in enumerate(pareja):
        mg = np.asarray(perfiles[k]["margen_wh"], float) * v3.O2_L_POR_WH
        mg = np.where(np.isfinite(mg), mg, -1.0)
        pct = 100 * (mg + RESERVA_O2 * q["o2_L"]) / q["o2_L"]
        tanque_pct = pct if tanque_pct is None else np.fmin(tanque_pct, pct)
        margen_L = mg if margen_L is None else np.fmin(margen_L, mg)
        usado = perfiles[k]["gastado_wh"][-1] * v3.O2_L_POR_WH
        por_persona.append({"o2_usado_L": round(usado, 1), "tanque_final_pct": round(float(pct[-1]), 1),
                            "no_retorno": perfiles[k]["punto_no_retorno"]})
    no_ret = [x["no_retorno"] for x in por_persona if x["no_retorno"] is not None]

    a = np.asarray(camino)
    ag = pareja[w]["agente"]
    dz = np.diff(np.nan_to_num(base.dem[a[:, 0], a[:, 1]]))
    dh = np.maximum(20.0 * np.hypot(*np.diff(a, axis=0).T), 1e-6)
    lento = (base.riesgo | base.duna)[a[1:, 0], a[1:, 1]]
    vel = np.where(lento, ag.vel_riesgo_m_h, ag.vel_seguro_m_h)
    arena = base.arena[a[1:, 0], a[1:, 1]] if base.arena is not None else np.zeros(len(dh), bool)
    eta = np.where(arena, ag.eta_arena, ag.eta_terreno)
    intensidad = v3.pandolf_w(ag, vel / 3600, 100 * dz / dh, eta) * v3.O2_L_POR_WH     # W -> L/h de O2
    volver = np.nan_to_num(np.asarray(rg["regreso_wh"], float)) * v3.O2_L_POR_WH
    critico = int(np.argmax(volver))
    tramo = np.hypot(dh, dz)

    t_h = ea.tiempos_camino(base, camino, ag, paradas)
    gastado = [np.asarray(perfiles[k]["gastado_wh"], float) for k in (0, 1)]
    rescate = ea.contingencia(base, camino, paradas, pareja, gastado, t_h, c["horas"], c["asist"])
    radio = ea.tramos_sin_senal(camino, c["cobertura"])
    hora = c["salida"] + t_h / ea.HORA_MARCIANA_H
    elev, az = ea.sol(c["lat"], c["dec"], hora)
    sombra, noche = ea.sombra_en_camino(base, camino, elev, az)
    largo = np.r_[0.0, tramo]
    return {"margen_L": np.round(margen_L, 1).tolist(), "tanque_pct": np.round(tanque_pct, 1).tolist(),
            "intensidad_Lh": np.round(intensidad, 1).tolist(),
            "punto_critico": critico, "no_retorno": min(no_ret) if no_ret else None,
            "pareja": por_persona, **rescate, "senal": radio["senal"],
            "sombra": sombra.tolist(), "hora_solar": np.round(hora, 2).tolist(),
            "seguridad": {"o2_volver_critico_L": round(float(volver[critico]), 1),
                          "margen_critico_L": round(float(margen_L[critico]), 1),
                          "sobrante_L": round(min(q["o2_L"] * x["tanque_final_pct"] / 100
                                                  for q, x in zip(pareja, por_persona)), 1),
                          "tanque_final_pct": round(float(tanque_pct[-1]), 1),
                          "tanque_min_pct": round(float(tanque_pct.min()), 1),
                          "intenso_pct": round(float(100 * tramo[intensidad > INTENSIDAD_MAX_LH].sum()
                                                     / max(tramo.sum(), 1e-9)), 1),
                          "rescate_min_L": round(float(min(rescate["margen_rescate_L"])), 1),
                          "sin_senal_pct": radio["sin_senal_pct"], "sin_senal_max_m": radio["sin_senal_max_m"],
                          "sombra_pct": round(float(100 * largo[sombra].sum() / max(largo.sum(), 1e-9)), 1),
                          "noche": bool(noche.any()), "regreso_hora": round(float(hora[-1]), 2)}}
