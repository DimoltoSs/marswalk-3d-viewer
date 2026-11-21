"""8. simplificar(): subsecuencia, rectas sin bloqueos, tolerancia del 3 %."""
import math

import numpy as np
from hypothesis import given, settings, strategies as st

from conftest import mapa_aleatorio, mk_mapa, v3


def celdas_cruzadas(p, q, N=4000):
    """Supercubierta aproximada: celdas que la recta continua atraviesa (muestreo muy denso)."""
    t = np.linspace(0, 1, N)
    f = p[0] + (q[0] - p[0]) * t
    c = p[1] + (q[1] - p[1]) * t
    return set(zip(np.floor(f + 0.5).astype(int).tolist(), np.floor(c + 0.5).astype(int).tolist()))


def costo_simplificar(mapa, a, i, j):
    """Medida de v4: costo integrado exactamente sobre las celdas que cruza la recta (fracción de longitud).
    Se calcula aquí con celdas_cruzadas (implementación independiente del supercover)."""
    p, q = a[i].astype(float), a[j].astype(float)
    n = 4000
    t = (np.arange(n) + 0.5) / n
    pts = p + np.outer(t, q - p)
    celdas = np.floor(pts + 0.5).astype(int)
    v = mapa.costo[celdas[:, 0], celdas[:, 1]]
    return float(v.mean()) * 20 * math.hypot(*(q - p))


def _camino(mapa, n):
    nodos = [(0, 0), (n - 1, n - 1)]
    T = v3.matriz_tramos(v3.Ventana.alrededor(mapa, nodos), nodos, v3.ROVER, ("normal",))
    return T.caminos.get(("normal", 0, 1))


@settings(max_examples=150, deadline=None)
@given(st.integers(0, 10**6), st.integers(4, 16))
def test_simplificar_subsecuencia_y_tolerancia(seed, n):
    mapa = mapa_aleatorio(np.random.default_rng(seed), n, n, p_bloq=0.25)
    mapa.costo[0, 0] = mapa.costo[-1, -1] = 1.0
    cam = _camino(mapa, n)
    if cam is None:
        return
    w = v3.simplificar(mapa, cam)
    a = np.asarray(cam)
    assert w[0] == cam[0] and w[-1] == cam[-1]
    idx, k = [], 0
    for x in w:                                   # subsecuencia en orden
        while cam[k] != x:
            k += 1
        idx.append(k)
    assert idx == sorted(idx)
    paso = mapa.costo[a[:-1, 0], a[:-1, 1]] + mapa.costo[a[1:, 0], a[1:, 1]]
    acum = np.concatenate([[0], np.cumsum(20 * np.hypot(*np.diff(a, axis=0).T) * paso / 2)])
    for i, j in zip(idx[:-1], idx[1:]):
        if j > i + 1:
            assert costo_simplificar(mapa, a, i, j) <= 1.03 * (acum[j] - acum[i]) + 1e-9


@settings(max_examples=300, deadline=None)
@given(st.integers(0, 10**6), st.integers(5, 16))
def test_BUG_simplificar_recta_no_cruza_bloqueos(seed, n):
    mapa = mapa_aleatorio(np.random.default_rng(seed), n, n, p_bloq=0.25)
    mapa.costo[0, 0] = mapa.costo[-1, -1] = 1.0
    cam = _camino(mapa, n)
    if cam is None:
        return
    for p, q in zip(*(lambda w: (w[:-1], w[1:]))(v3.simplificar(mapa, cam))):
        malas = [x for x in celdas_cruzadas(p, q) if not np.isfinite(mapa.costo[x])]
        assert not malas, f"recta {p}->{q} cruza celdas bloqueadas {malas}"


def test_BUG_simplificar_repro_minima():
    """Repro determinista (6x6). La recta (0,0)->(4,3) atraviesa la celda bloqueada (3,3)
    durante ~0.2 celdas (t en [0.833, 0.875]); el muestreo de 18 puntos (paso 1/17) no la ve."""
    inf = np.inf
    c = np.array([[1.00, 1.09, 1.14, 1.04, 1.04, 1.07],
                  [1.11, 1.17, 1.14, inf, 1.05, 1.12],
                  [1.00, 1.09, 1.12, 1.05, 1.00, 1.06],
                  [1.00, 1.15, 1.17, inf, inf, inf],
                  [1.07, 1.12, 1.10, 1.06, 1.09, 1.09],
                  [1.12, 1.10, inf, 1.17, 1.16, 1.00]])
    mapa = mk_mapa(c)
    cam = [(0, 0), (1, 0), (2, 0), (3, 1), (4, 2), (4, 3), (4, 4), (5, 5)]   # camino válido de Dijkstra
    w = v3.simplificar(mapa, cam)
    assert (3, 3) in celdas_cruzadas((0, 0), (4, 3))   # la recta vieja cruzaba un bloqueo
    assert w[0] == (0, 0) and w[-1] == (5, 5)
    assert not any(np.isinf(mapa.costo[x]) for p, q in zip(w[:-1], w[1:]) for x in celdas_cruzadas(p, q))


def test_simplificar_real(mapa_real, capas):
    ini = tuple(int(x) for x in capas["ruta_rc"][0]); fin = tuple(int(x) for x in capas["ruta_rc"][-1])
    T = v3.matriz_tramos(v3.Ventana.alrededor(mapa_real, [ini, fin]), [ini, fin], v3.ROVER, ("normal",))
    cam = T.caminos[("normal", 0, 1)]
    w = v3.simplificar(mapa_real, cam)
    malas = [(p, q) for p, q in zip(w[:-1], w[1:])
             if any(mapa_real.bloqueado[x] for x in celdas_cruzadas(p, q))]
    print(f"real: {len(cam)} celdas -> {len(w)} waypoints; segmentos que cruzan bloqueos: {len(malas)}")
    assert not malas, malas[:5]
