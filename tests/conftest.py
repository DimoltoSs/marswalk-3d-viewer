"""Helpers comunes. Importa los módulos de visor_3d vía sys.path (no los modifica)."""
import math
import os
import sys

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import mision_v3 as v3  # noqa: E402

VEC = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]


def mk_mapa(costo, dem=None, pend=None, riesgo=None, duna=None):
    """Construye un Mapa directamente con arreglos pequeños."""
    costo = np.asarray(costo, dtype=float)
    sh = costo.shape
    dem = np.zeros(sh) if dem is None else np.asarray(dem, float)
    pend = np.zeros(sh) if pend is None else np.asarray(pend, float)
    bloq = ~np.isfinite(costo)
    riesgo = np.zeros(sh, bool) if riesgo is None else (np.asarray(riesgo, bool) & ~bloq)
    duna = np.zeros(sh, bool) if duna is None else np.asarray(duna, bool)
    return v3.Mapa(costo, dem, pend, riesgo, duna, bloq)


def mapa_aleatorio(rng, n, m, p_bloq=0.2, p_riesgo=0.2, dz=5.0):
    costo = 1 + rng.random((n, m)) * 2
    costo[rng.random((n, m)) < p_bloq] = np.inf
    dem = rng.random((n, m)) * dz
    pend = rng.random((n, m)) * 19
    riesgo = rng.random((n, m)) < p_riesgo
    duna = rng.random((n, m)) < 0.1
    return mk_mapa(costo, dem, pend, riesgo, duna)


def peso_ref(mapa, a, b, seguro=False, w_subida=8.0, w_seguro=4.0):
    """Peso de arista independiente: longitud 3D x costo medio + w_subida x max(dz,0)."""
    c = mapa.costo
    ca, cb = c[a], c[b]
    if seguro:
        ca = ca * (1 + w_seguro * mapa.riesgo[a])
        cb = cb * (1 + w_seguro * mapa.riesgo[b])
    dz = mapa.dem[b] - mapa.dem[a]
    d3 = math.hypot(20.0 * math.hypot(b[0] - a[0], b[1] - a[1]), dz)
    return d3 * (ca + cb) / 2 + w_subida * max(dz, 0.0)


def movimiento_valido(mapa, a, b):
    n, m = mapa.forma
    df, dc = b[0] - a[0], b[1] - a[1]
    if (df, dc) not in VEC:
        return False
    if not (0 <= b[0] < n and 0 <= b[1] < m):
        return False
    lib = np.isfinite(mapa.costo)
    if not (lib[a] and lib[b]):
        return False
    if df and dc and not (lib[a[0], b[1]] and lib[b[0], a[1]]):
        return False
    return True


def grafo_nx(mapa, seguro=False):
    import networkx as nx
    G = nx.DiGraph()
    n, m = mapa.forma
    for f in range(n):
        for c in range(m):
            G.add_node((f, c))
            for df, dc in VEC:
                b = (f + df, c + dc)
                if movimiento_valido(mapa, (f, c), b):
                    G.add_edge((f, c), b, weight=peso_ref(mapa, (f, c), b, seguro))
    return G


def metricas_ref(mapa, cam, ag):
    """Métricas independientes de un camino global [(f,c),...]."""
    km = h = wh = rk = 0.0
    pmax = max(mapa.pend[x] for x in cam)
    for a, b in zip(cam[:-1], cam[1:]):
        dz = mapa.dem[b] - mapa.dem[a]
        d3 = math.hypot(20.0 * math.hypot(b[0] - a[0], b[1] - a[1]), dz)
        lento = mapa.riesgo[b] or mapa.duna[b]
        km += d3 / 1000
        h += d3 / (ag.vel_riesgo_m_h if lento else ag.vel_seguro_m_h)
        if getattr(ag, "metabolico", False):          # referencia independiente de Pandolf + Santee
            v = (ag.vel_riesgo_m_h if lento else ag.vel_seguro_m_h) / 3600
            dh = 20.0 * math.hypot(b[0] - a[0], b[1] - a[1])
            G = 100 * dz / dh
            arena = mapa.arena is not None and bool(mapa.arena[b])
            eta = ag.eta_arena if arena else ag.eta_terreno
            W, Lk = ag.masa_kg, ag.traje_kg + ag.kit_kg
            M = 1.5 * W + 2.0 * (W + Lk) * (Lk / W) ** 2 + eta * (W + Lk) * (1.5 * v * v + 0.35 * v * G)
            if G < 0:
                M -= eta * ((G * (W + Lk) * v) / 3.5 - (W + Lk) * (G + 6) ** 2 / W + 25 - v * v)   # MP - CF
            wh += max(M, 1.5 * W) * ag.g_rel * d3 / (v * 3600)
        else:
            wh += ag.wh_por_m * d3 + ag.wh_por_m_subida * max(dz, 0)
        rk += d3 / 1000 if mapa.riesgo[b] else 0
    return dict(km=km, h=h, wh=wh, riesgo_km=rk, pend_max=pmax)


@pytest.fixture(scope="session")
def capas():
    from proto1_capas import cargar
    return cargar()


@pytest.fixture(scope="session")
def mapa_real(capas):
    return v3.Mapa.desde_capas(capas)
