"""exportar_replaneo.py - Simula que el robot detecta un peligro sobre el plan y se desvia.

Lee el plan de public/data/rutas_v2.json, pone un peligro circular que el mapa orbital
no conocia y guarda el resultado en public/data/replaneo.json para el visor."""
import json
import os
import sys

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "prototipo_uno"))
from proto1_capas import cargar, rc_a_xy, xy_a_rc            # noqa: E402
from proto1_mapa_costos import construir_costo               # noqa: E402
from replaneo import distancia_acumulada, replanear          # noqa: E402

DATOS = os.path.join(AQUI, "public", "data")
ENTRADA = os.path.join(DATOS, "rutas_v2.json")
SALIDA = os.path.join(DATOS, "replaneo.json")

# Escenario de la simulacion (lo que puedes mover)
FRACCION_DETECCION = 0.45   # el robot ve el peligro al 45 % del recorrido
VISTA_M = 60.0              # a que distancia del borde del peligro lo ve
RADIO_M = 100.0             # radio del peligro
MARGEN_M = 100.0            # distancia extra al reengancharse al plan


def a_celdas(xy):
    """[[x, y], ...] en metros -> [(fila, col), ...] sin celdas repetidas seguidas."""
    a = np.asarray(xy)
    f, c = xy_a_rc(a[:, 0], a[:, 1])
    camino = []
    for p in zip(f.tolist(), c.tolist()):
        if not camino or p != camino[-1]:
            camino.append(p)
    return camino


def a_xy(celdas):
    """[(fila, col), ...] -> [[x, y], ...] en metros."""
    a = np.asarray(celdas)
    x, y = rc_a_xy(a[:, 0], a[:, 1])
    return np.round(np.c_[x, y], 1).tolist()


def main():
    costo = construir_costo(cargar())["costo"]
    with open(ENTRADA, encoding="utf-8") as f:
        plan = json.load(f)["plan"]
    camino = a_celdas(plan)
    acum = distancia_acumulada(camino)

    # Donde va el robot y donde esta el peligro (centrado sobre el plan, mas adelante)
    i_robot = int(np.searchsorted(acum, FRACCION_DETECCION * acum[-1]))
    i_peligro = int(np.searchsorted(acum, acum[i_robot] + VISTA_M + RADIO_M))
    peligro = camino[i_peligro]

    r = replanear(costo, camino, i_robot, peligro, RADIO_M, MARGEN_M)
    if r["estado"] != "ok":
        print("Sin desvio:", r["estado"])
        return

    px, py = a_xy([peligro])[0]
    extra = r["m_desvio"] - r["m_original"]
    datos = {
        "estado": r["estado"],
        "peligro": {"x": px, "y": py, "radio_m": RADIO_M},
        "deteccion": {"xy": a_xy([camino[i_robot]])[0], "d_m": round(float(acum[i_robot]))},
        "reenganche": a_xy([camino[r["i_reenganche"]]])[0],
        "tramo_original": a_xy(camino[i_robot:r["i_reenganche"] + 1]),
        "desvio": a_xy(r["desvio"]),
        "plan": a_xy(r["camino"]),
        "metricas": {"m_original": round(r["m_original"]), "m_desvio": round(r["m_desvio"]),
                     "extra_m": round(extra), "extra_pct": round(100 * extra / r["m_original"], 1)},
    }
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False)

    m = datos["metricas"]
    print(f"Peligro de {RADIO_M:.0f} m detectado a los {datos['deteccion']['d_m'] / 1000:.2f} km "
          f"de {acum[-1] / 1000:.2f} km")
    print(f"Tramo original {m['m_original']} m -> desvio {m['m_desvio']} m "
          f"(+{m['extra_m']} m, +{m['extra_pct']} %)")
    print(f"Plan nuevo: {len(datos['plan'])} puntos -> {SALIDA}")


if __name__ == "__main__":
    main()