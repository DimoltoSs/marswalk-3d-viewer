"""exportar_mision_v3.py - Misión del plan v3 para el visor (public/data/rutas_v3.json).

Mismo escenario que el notebook planificador_v2 (inicio y meta = extremos de la ruta real de
Perseverance, presupuesto = FACTOR x la ruta directa), pero con el planificador v3
(mision_v3.py): rutas normal/segura por tramo, varios órdenes, búsqueda local y paro por
estancamiento. Guarda la misión elegida con los mismos pesos que el notebook y el frente completo.

Uso (desde visor_3d):  python exportar_mision_v3.py [--factor 2.0] [--semilla 42]
"""
import argparse
import json
import os
import sys

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "prototipo_uno"))
from proto1_capas import cargar, rc_a_xy  # noqa: E402

import mision_v3 as v3  # noqa: E402

PESOS = {"ciencia": 0.5, "tiempo": 0.3, "riesgo": 0.2}   # los mismos que la sección 10 del notebook


def a_xy(celdas):
    a = np.asarray(celdas)
    x, y = rc_a_xy(a[:, 0], a[:, 1])
    return np.round(np.c_[x, y], 1).tolist()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--factor", type=float, default=2.0, help="presupuesto = factor x ruta directa")
    ap.add_argument("--semilla", type=int, default=42)
    ap.add_argument("--candidatos", type=int, default=15)
    ap.add_argument("--salida", default=os.path.join(AQUI, "public", "data", "rutas_v3.json"))
    a = ap.parse_args()

    L = cargar()
    mapa = v3.Mapa.desde_capas(L)
    cands = v3.candidatos_ciencia(mapa, L)
    inicio = tuple(int(v) for v in L["ruta_rc"][0])
    meta = tuple(int(v) for v in L["ruta_rc"][-1])
    op = v3.OpcionesGA(semilla=a.semilla)
    plan = v3.planear(mapa, cands, inicio, meta, v3.ROVER, factor=a.factor,
                      max_candidatos=a.candidatos, op=op)
    T, pb, frente = plan["tramos"], plan["problema"], plan["frente"]
    elegida = frente[v3.elegir(frente, PESOS)]
    camino = v3.camino_mision(T, pb, elegida)
    print(f"{len(plan['candidatos'])} candidatos · tramos {plan['seg_tramos']} s · "
          f"total {plan['seg_total']} s · {plan['generaciones']} generaciones · frente {len(frente)}")

    def resumen(m):
        return {"ciencia": round(m["ciencia"], 3), "horas": round(m["h"], 1), "wh": round(m["wh"]),
                "km": round(m["km"], 2), "riesgo_km": round(m["riesgo_km"], 3),
                "pend_max": round(m["pend_max"], 1), "objetivos": len(m["seq"])}

    real = [L["ruta_xy_m"][0].tolist()]
    for p in L["ruta_xy_m"][1:]:
        if np.hypot(*(p - np.array(real[-1]))) > 5:              # sin puntos repetidos
            real.append(p.tolist())
    salida = {
        "plan": a_xy(camino),
        "waypoints": a_xy(v3.simplificar(mapa, camino)),
        "objetivos": [{"parada": i + 1, "x": xy[0], "y": xy[1], "mineral": c["mineral"],
                       "area_ha": c["area_ha"], "ciencia": c["ciencia"]}
                      for i, k in enumerate(elegida["seq"])
                      for c in [plan["candidatos"][k - pb.primer]]
                      for xy in [a_xy([c["celda"]])[0]]],
        "inicio": a_xy([inicio])[0],
        "meta": a_xy([meta])[0],
        "real": np.round(real, 1).tolist(),
        "metricas": resumen(elegida),
        "presupuesto": {"horas": round(plan["presupuesto"]["h"], 1),
                        "wh": round(plan["presupuesto"]["wh"])},
        "supuestos": {"horas_por_objetivo": v3.ROVER.horas_por_objetivo, "factor": a.factor,
                      "reserva_energia": op.reserva_energia, "pesos": PESOS,
                      "planificador": "v3 (mision_v3.py)"},
        "frente": [resumen(m) for m in frente],
        "nombradas": plan["nombradas"],
    }
    with open(a.salida, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False)
    m = salida["metricas"]
    print(f"misión elegida: {m['objetivos']} objetivos · ciencia {m['ciencia']} · {m['horas']} h · "
          f"{m['wh']} Wh · {m['km']} km · riesgo {m['riesgo_km']} km")
    for nombre, i in plan["nombradas"].items():
        r = salida["frente"][i]
        print(f"  {nombre:<12} ciencia {r['ciencia']:.3f} · {r['horas']:.1f} h · riesgo {r['riesgo_km']:.3f} km")
    print("guardado en", os.path.abspath(a.salida))


if __name__ == "__main__":
    main()
