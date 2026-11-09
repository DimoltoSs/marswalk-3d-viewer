"""replaneo.py - El robot detecta un peligro que el mapa orbital no tenia en cuenta y recalcula su trayectoria solo"""
import os
import sys
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "prototipo_uno"))
from proto1_planificador import astar

def bloquear_circulo(costo, centro, radio_m, res=20.0):
    """"Copia del mapa de costos con un circulo de obstaculo (np.inf) en ´centro´ (fila, col)."""
    n, m = costo.shape
    filas, cols = np.ogrid[:n, :m]
    dist = res * np.hypot(filas - centro[0], cols - centro[1])
    nuevo = costo.copy()
    nuevo[dist <= radio_m] = np.inf
    return nuevo

def distancia_acumulada(camino, res=20.0):
    """Metros recorridos hasta cada celda del camino."""
    a = np.asanyarray(camino, dtype=float)
    pasos = res * np.hypot(*np.diff(a, axis=0).T)
    return np.concatenate([[0,0], np.cumsum(pasos)])

def replanear(costo, camino, i_robot, peligro, radio_m, margen_m=100.0, res=20.0):
    """El robot va en camino[i_robot] y detecta un peligro circular en ´peligro´ (fila, col)."""
    costo2 = bloquear_circulo(costo, peligro, radio_m, res)
    a = np.asanyarray(camino)
    d_peligro = res * np.hypot(a[:, 0] - peligro[0], a[:, 1] - peligro[1])

    # Celdas del plan, por delante del robot que caen dentro de peligro
    adentro = np.nonzero(d_peligro < radio_m)[0]
    adentro = adentro[adentro > i_robot]
    if len(adentro) == 0:
        return dict(estado="sin_cambio", camino=camino, costo=costo2)

    # Reenganche: primera celda despues del peligro, a mas de radio + margen y transitable
    j = len(camino) - 1
    for k in range(adentro[-1] + 1, len(camino)):
        if d_peligro[k] > radio_m + margen_m and np.isfinite(costo2[camino[k]]):
            j = k
            break

    desvio, costo_desvio = astar(costo2, camino[i_robot], camino[j], res)
    if desvio is None:                                   # no hay forma de rodearlo
        return dict(estado="sin_ruta", camino=camino[:i_robot + 1], costo=costo2)

    acum = distancia_acumulada(camino, res)
    return dict(estado="ok", costo=costo2,
                camino=list(camino[:i_robot]) + desvio + list(camino[j + 1:]),
                desvio=desvio, i_robot=i_robot, i_reenganche=j,
                m_original=float(acum[j] - acum[i_robot]),
                m_desvio=float(distancia_acumulada(desvio, res)[-1]),
                costo_desvio=float(costo_desvio))

