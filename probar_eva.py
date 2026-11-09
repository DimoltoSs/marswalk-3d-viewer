"""probar_eva.py - Compara una salida de astronauta desde el aterrizaje y desde el mejor centroide."""
import os
import sys

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "prototipo_uno"))
from proto1_capas import cargar, rc_a_xy                     # noqa: E402
from proto1_mapa_costos import construir_costo               # noqa: E402
from proto1_objetivos import candidatos_ciencia              # noqa: E402
from eva import ESFUERZO_MAX, RADIO_M, mejor_centroide, planear_eva  # noqa: E402
from replaneo import distancia_acumulada                     # noqa: E402


def resumen(nombre, habitat, r, res=20.0):
    x, y = rc_a_xy(*habitat)
    print(f"\n== Habitat en {nombre}: celda {habitat}, x={x / 1000:.2f} km, y={y / 1000:.2f} km ==")
    if r["mision"] is None:
        print("Ningun objetivo alcanzable dentro del radio y el presupuesto.")
        return
    camino = r["mision"]["camino"]
    lejos = max(res * np.hypot(f - habitat[0], c - habitat[1]) for f, c in camino)
    print(f"candidatos considerados: {r['considerados']} | visitados: {len(r['visitados'])}")
    print(f"ciencia: {sum(v['puntaje'] for v in r['visitados']):.0f} | "
          f"esfuerzo: {r['costo']:.0f} de {ESFUERZO_MAX:.0f}")
    print(f"recorrido: {distancia_acumulada(camino)[-1] / 1000:.2f} km | "
          f"maximo alejamiento: {lejos:.0f} m de {RADIO_M:.0f} m | "
          f"waypoints: {len(r['mision']['waypoints'])}")


def main():
    L = cargar()
    costo = construir_costo(L)["costo"]
    candidatos = candidatos_ciencia(L, costo, max_candidatos=1000)   # todos, no solo 12

    aterrizaje = tuple(int(v) for v in L["ruta_rc"][0])
    resumen("el aterrizaje", aterrizaje, planear_eva(costo, candidatos, aterrizaje))

    centroide, _ = mejor_centroide(costo, candidatos, RADIO_M)
    resumen("el mejor centroide", centroide, planear_eva(costo, candidatos, centroide))


if __name__ == "__main__":
    main()