# Prototipo 1 - A*, simplificacion de rutas, matriz de costos y plan por tramos
"""planeador.py - Busqueda de rutas sobre un mapa de costos.

Este modulo implementa el algoritmo de Dijkstra para encontrar el camino de
costo minimo entre dos celdas en un mapa de costos.
"""
import math
import heapq
from skimage.graph import MCP_Geometric
import numpy as np

# 8 movimientos posibles: (delta_fila, delta_columna)
MOVIMIENTOS = [(-1, 0), (1, 0), (0, -1), (0, 1),      # ortogonales
               (-1, -1), (-1, 1), (1, -1), (1, 1)]    # diagonales


def vecinos(fila, col, costo, res=20.0):
    """Genera (fila2, col2, costo_del_paso) para cada vecino transitable."""
    n, m = costo.shape
    for df, dc in MOVIMIENTOS:
        f, c = fila + df, col + dc

        if not (0 <= f < n and 0 <= c < m):       # fuera del mapa
            continue
        if not np.isfinite(costo[f, c]):          # obstaculo
            continue

        if df != 0 and dc != 0:                   # movimiento diagonal
            # no cortar esquinas: las dos celdas ortogonales tambien deben estar libres
            if not (np.isfinite(costo[f, col]) and np.isfinite(costo[fila, c])):
                continue
            dist = res * math.sqrt(2)             # 28.28 m
        else:
            dist = res                            # 20 m

        # costo del paso = distancia * promedio de los costos de las dos celdas
        yield f, c, dist * (costo[fila, col] + costo[f, c]) / 2


def dijkstra(costo, inicio, meta):
    """Camino de costo minimo de `inicio` a `meta`.

    Devuelve (camino, costo_total), donde camino es una lista de (fila, col)
    desde inicio hasta meta. Si no hay camino, devuelve (None, np.inf).
    """
    n, m = costo.shape
    g = np.full((n, m), np.inf)      # mejor costo conocido para llegar a cada celda
    padre = {}                       # de que celda se llego a cada celda
    g[inicio] = 0.0
    cola = [(0.0, inicio)]           # cola de prioridad: (costo acumulado, celda)

    while cola:
        gi, (f, c) = heapq.heappop(cola)      # la celda pendiente mas barata
        if gi > g[f, c]:
            continue                          # entrada vieja: ya hay un camino mejor
        if (f, c) == meta:
            break
        for f2, c2, w in vecinos(f, c, costo):
            g2 = gi + w
            if g2 < g[f2, c2]:               # camino mejor hacia ese vecino
                g[f2, c2] = g2
                padre[(f2, c2)] = (f, c)
                heapq.heappush(cola, (g2, (f2, c2)))

    if not np.isfinite(g[meta]):
        return None, np.inf                   # meta inalcanzable

    camino = [meta]
    while camino[-1] != inicio:               # reconstruir de la meta hacia el inicio
        camino.append(padre[camino[-1]])
    return camino[::-1], g[meta]

def heuristica_octil(f, c, meta, costo_min, res=20.0):
    """Cota inferior del costo restante: distancia octil * costo minimo por metro."""
    df, dc = abs(f - meta[0]), abs(c - meta[1])
    return costo_min * res * (max(df, dc) + (math.sqrt(2) - 1) * min(df, dc))


def astar(costo, inicio, meta, res=20.0):
    """Igual que dijkstra, pero ordena la cola por g + h en lugar de solo g."""
    n, m = costo.shape
    costo_min = float(costo[np.isfinite(costo)].min())
    g = np.full((n, m), np.inf)
    padre = {}
    g[inicio] = 0.0
    cola = [(heuristica_octil(*inicio, meta, costo_min, res), 0.0, inicio)]

    while cola:
        _, gi, (f, c) = heapq.heappop(cola)
        if gi > g[f, c]:
            continue
        if (f, c) == meta:
            break
        for f2, c2, w in vecinos(f, c, costo, res):
            g2 = gi + w
            if g2 < g[f2, c2]:
                g[f2, c2] = g2
                padre[(f2, c2)] = (f, c)
                h = heuristica_octil(f2, c2, meta, costo_min, res)
                heapq.heappush(cola, (g2 + h, g2, (f2, c2)))

    if not np.isfinite(g[meta]):
        return None, np.inf
    camino = [meta]
    while camino[-1] != inicio:
        camino.append(padre[camino[-1]])
    return camino[::-1], g[meta]

def celdas_en_linea(a, b, paso=0.25):
    """Celdas (fila, col) que toca la recta entre las celdas a y b."""
    n = int(max(abs(b[0] - a[0]), abs(b[1] - a[1])) / paso) + 2
    t = np.linspace(0, 1, n)
    f = np.rint(a[0] + (b[0] - a[0]) * t).astype(int)
    c = np.rint(a[1] + (b[1] - a[1]) * t).astype(int)
    return f, c


def costo_acumulado(camino, costo, res=20.0):
    """Costo para llegar a cada punto del camino, con la misma regla que usa A*."""
    acum = [0.0]
    for (f1, c1), (f2, c2) in zip(camino[:-1], camino[1:]):
        dist = res * math.hypot(f2 - f1, c2 - c1)
        acum.append(acum[-1] + dist * (costo[f1, c1] + costo[f2, c2]) / 2)
    return np.array(acum)


def tramo_aceptable(a, b, costo, costo_camino, res=20.0, tolerancia=0.05):
    """True si la recta a-b no toca obstáculos y no cuesta más que el camino original."""
    f, c = celdas_en_linea(a, b)
    v = costo[f, c]
    if not np.isfinite(v).all():
        return False
    largo = res * math.hypot(b[0] - a[0], b[1] - a[1])
    return v.mean() * largo <= (1 + tolerancia) * costo_camino


def simplificar(camino, costo, res=20.0, tolerancia=0.05):
    """Reduce el camino de celdas a pocos waypoints unidos por rectas seguras."""
    acum = costo_acumulado(camino, costo, res)
    indices = [0]
    i = 0
    while i < len(camino) - 1:
        j = i + 1
        while j + 1 < len(camino) and tramo_aceptable(
                camino[i], camino[j + 1], costo, acum[j + 1] - acum[i], res, tolerancia):
            j += 1
        indices.append(j)
        i = j
    return [camino[k] for k in indices]


def planear_mision(costo, paradas, res=20.0, tolerancia=0.02):
    """Une una lista de paradas con A* y simplifica cada tramo en waypoints."""
    camino, waypoints, tramos = [], [paradas[0]], []
    for k, (a, b) in enumerate(zip(paradas[:-1], paradas[1:])):
        c, total = astar(costo, a, b, res)
        if c is None:
            raise ValueError(f"Tramo {k}: no hay camino de {a} a {b}")
        camino += c if not camino else c[1:]
        wp = simplificar(c, costo, res, tolerancia)
        waypoints += wp[1:]
        tramos.append({"de": a, "a": b, "costo": float(total),
                       "celdas": len(c), "waypoints": len(wp) - 1})
    return {"paradas": paradas, "camino": camino, "waypoints": waypoints, "tramos": tramos,
            "costo_total": sum(t["costo"] for t in tramos)}

def matriz_costos(costo, nodos, res=20.0):
    """Costo mínimo entre cada par de nodos (fila, col). M[i, j] = costo de ir de i a j."""
    c = np.where(np.isfinite(costo), costo, -1.0)      # en MCP, un costo negativo = intransitable
    M = np.zeros((len(nodos), len(nodos)))
    for i, origen in enumerate(nodos):
        mcp = MCP_Geometric(c, fully_connected=True)
        acumulado, _ = mcp.find_costs([origen])
        for j, destino in enumerate(nodos):
            M[i, j] = acumulado[destino] * res
    return M

