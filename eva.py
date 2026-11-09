"""eva.py - Mision de un astronauta a pie: sale de un habitat, no se aleja mas de un radio
y regresa al habitat sin pasarse de su presupuesto de esfuerzo."""
import os
import sys

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "prototipo_uno"))
from proto1_objetivos import costo_recorrido                   # noqa: E402
from proto1_planificador import matriz_costos, planear_mision  # noqa: E402

RADIO_M = 3000.0        # supuesto: maximo alejamiento del habitat (Artemis usa ~2 km a pie)
ESFUERZO_MAX = 8000.0   # supuesto: esfuerzo por salida, en "metros en terreno plano"


def distancia_a(forma, celda, res=20.0):
    """Distancia en metros de cada celda del mapa a `celda` (fila, col)."""
    filas, cols = np.ogrid[:forma[0], :forma[1]]
    return res * np.hypot(filas - celda[0], cols - celda[1])


def solo_dentro(costo, centro, radio_m, res=20.0):
    """Copia del mapa de costos donde todo lo que queda FUERA del radio es obstaculo."""
    nuevo = costo.copy()
    nuevo[distancia_a(costo.shape, centro, res) > radio_m] = np.inf
    return nuevo


def mejor_centroide(costo, candidatos, radio_m, res=20.0):
    """Celda transitable con la mayor suma de puntajes de candidatos a menos de radio_m."""
    suma = np.zeros(costo.shape)
    for c in candidatos:
        suma += c["puntaje"] * (distancia_a(costo.shape, c["celda"], res) <= radio_m)
    suma[~np.isfinite(costo)] = 0.0
    celda = np.unravel_index(np.argmax(suma), suma.shape)
    return (int(celda[0]), int(celda[1])), float(suma[celda])


def elegir_eva(M, puntajes, presupuesto):
    """Como elegir_objetivos, pero la mision empieza y termina en el habitat (nodo 0).
    Nodos: 0 = habitat, 1 en adelante = candidatos (puntajes[k - 1])."""
    orden = [0, 0]
    pendientes = set(range(1, len(M)))
    while True:
        actual = costo_recorrido(M, orden)
        mejor = None
        for k in pendientes:
            for pos in range(1, len(orden)):
                nuevo = orden[:pos] + [k] + orden[pos:]
                total = costo_recorrido(M, nuevo)
                if total > presupuesto:
                    continue
                razon = puntajes[k - 1] / max(total - actual, 1.0)
                if mejor is None or razon > mejor[0]:
                    mejor = (razon, nuevo, k)
        if mejor is None:
            break
        _, orden, k = mejor
        pendientes.discard(k)
    return orden, costo_recorrido(M, orden)


def planear_eva(costo, candidatos, habitat, radio_m=RADIO_M, esfuerzo=ESFUERZO_MAX,
                max_nodos=15, res=20.0):
    """Mision completa de un astronauta desde `habitat` (fila, col)."""
    costo_r = solo_dentro(costo, habitat, radio_m, res)
    cerca = [c for c in candidatos if np.isfinite(costo_r[c["celda"]])][:max_nodos]
    nodos = [habitat] + [c["celda"] for c in cerca]
    M = matriz_costos(costo_r, nodos, res)
    alcanzables = np.isfinite(M[0]) & np.isfinite(M[:, 0])   # ida y vuelta posibles
    puntajes = [c["puntaje"] if alcanzables[k + 1] else 0.0 for k, c in enumerate(cerca)]
    M = np.where(np.isfinite(M), M, 1e12)                    # inalcanzable = carisimo

    orden, total = elegir_eva(M, puntajes, esfuerzo)
    visitados = [cerca[k - 1] for k in orden[1:-1]]
    if not visitados:
        return dict(orden=orden, visitados=[], costo=0.0, mision=None, costo_mapa=costo_r)
    mision = planear_mision(costo_r, [nodos[k] for k in orden], res)
    return dict(orden=orden, visitados=visitados, costo=float(total), mision=mision,
                costo_mapa=costo_r, considerados=len(cerca))