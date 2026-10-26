"""exportar_rutas.py - Paso 5 del visor 3D.
Corre el plan del prototipo 1 y guarda en JSON las rutas y los objetivos para el navegador.
Coordenadas en metros locales: x = Este, y = Norte (centro del mapa = 0, 0)."""
import json
import os
import sys

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))                 # .../NASA_SAC/visor_3d
sys.path.insert(0, os.path.join(AQUI, "..", "prototipo_uno"))     # para importar tus módulos
SALIDA = os.path.join(AQUI, "public", "data", "rutas.json")

from proto1_capas import cargar, rc_a_xy                           # noqa: E402
from proto1_mapa_costos import construir_costo                     # noqa: E402
from proto1_objetivos import candidatos_ciencia, elegir_objetivos  # noqa: E402
from proto1_planificador import matriz_costos, planear_mision      # noqa: E402

NOMBRES = {1: "Olivine", 2: "Mg-Carbonate", 3: "Fe/Mg-Smectite", 4: "Olivine+Smectite",
           5: "Olv.Smect+2.2um", 6: "Carb.+2.2um", 7: "High-Ca Pyroxene",
           8: "Low-Ca Pyroxene", 9: "Kaolinite", 10: "Mg-Smectite 2"}


def a_xy(celdas):
    """Lista de (fila, col) -> lista de [x, y] en metros, redondeados a 0.1 m."""
    a = np.asarray(celdas)
    x, y = rc_a_xy(a[:, 0], a[:, 1])
    return np.round(np.c_[x, y], 1).tolist()


def sin_repetidos(xy, minimo_m=5.0):
    """Quita puntos consecutivos casi iguales (el rover detenido): rompen las curvas 3D."""
    limpio = [xy[0]]
    for p in xy[1:]:
        if np.hypot(p[0] - limpio[-1][0], p[1] - limpio[-1][1]) > minimo_m:
            limpio.append(p)
    return limpio


def main():
    L = cargar()
    costo = construir_costo(L)["costo"]

    # --- mismo flujo que proto1_plan_estrategico.py ---
    candidatos = candidatos_ciencia(L, costo)
    inicio = tuple(int(v) for v in L["ruta_rc"][0])
    meta = tuple(int(v) for v in L["ruta_rc"][-1])
    nodos = [inicio, meta] + [c["celda"] for c in candidatos]
    M = matriz_costos(costo, nodos)
    orden, total, presupuesto = elegir_objetivos(M, [c["puntaje"] for c in candidatos])
    mision = planear_mision(costo, [nodos[k] for k in orden])

    objetivos = []
    for paso, k in enumerate(orden[1:-1], start=1):
        c = candidatos[k - 2]
        x, y = a_xy([c["celda"]])[0]
        objetivos.append({"parada": paso, "x": x, "y": y,
                          "mineral": NOMBRES.get(c["mineral"], str(c["mineral"])),
                          "area_ha": round(c["area_ha"], 1), "puntaje": round(c["puntaje"])})

    real = np.round(L["ruta_xy_m"], 1).tolist()
    datos = {
        "plan": a_xy(mision["camino"]),          # camino celda por celda de A*
        "waypoints": a_xy(mision["waypoints"]),  # versión simplificada
        "objetivos": objetivos,
        "inicio": a_xy([inicio])[0],
        "meta": a_xy([meta])[0],
        "real": sin_repetidos(real),             # ruta real de Perseverance
        "costo_total": round(mision["costo_total"]),
        "presupuesto": round(presupuesto),
    }
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False)
    print(f"Listo: plan {len(datos['plan'])} puntos, {len(objetivos)} objetivos, "
          f"ruta real {len(datos['real'])} puntos -> {SALIDA}")


if __name__ == "__main__":
    main()