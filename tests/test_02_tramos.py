"""2. matriz_tramos: caminos válidos, métricas, y comparación contra networkx (fuerza bruta)."""
import networkx as nx
import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from conftest import grafo_nx, mapa_aleatorio, metricas_ref, movimiento_valido, v3


def _nodos(rng, mapa, k):
    n, m = mapa.forma
    return [tuple(int(x) for x in (rng.integers(n), rng.integers(m))) for _ in range(k)]


@settings(max_examples=60, deadline=None)
@given(st.integers(0, 10**6), st.integers(3, 9), st.integers(3, 9), st.integers(2, 5),
       st.sampled_from([v3.ROVER, v3.ASTRONAUTA]))
def test_tramos_contra_networkx(seed, n, m, k, ag):
    rng = np.random.default_rng(seed)
    mapa = mapa_aleatorio(rng, n, m, p_bloq=0.25)
    nodos = _nodos(rng, mapa, k)
    v = v3.Ventana.alrededor(mapa, nodos)
    T = v3.matriz_tramos(v, nodos, ag)
    for perfil in T.perfiles:
        G = grafo_nx(mapa, seguro=(perfil == "seguro"))
        for i, a in enumerate(nodos):
            for j, b in enumerate(nodos):
                if i == j:
                    continue
                alc = nx.has_path(G, a, b)
                assert T.alcanzable[i, j] == alc
                if not alc:
                    assert (perfil, i, j) not in T.caminos
                    continue
                d_ref = nx.dijkstra_path_length(G, a, b)
                assert np.isclose(T.get(perfil, "costo")[i, j], d_ref, rtol=1e-9, atol=1e-9)
                cam = T.caminos[(perfil, i, j)]
                assert cam[0] == a and cam[-1] == b
                w = 0.0
                for p, q in zip(cam[:-1], cam[1:]):
                    assert movimiento_valido(mapa, p, q)
                    w += G[p][q]["weight"]
                assert np.isclose(w, T.get(perfil, "costo")[i, j], rtol=1e-9)
                ref = metricas_ref(mapa, cam, ag)
                for key in ("km", "h", "wh", "riesgo_km", "pend_max"):
                    assert np.isclose(T.get(perfil, key)[i, j], ref[key], rtol=1e-9, atol=1e-12), key


def test_tramos_real_subconjunto(mapa_real, capas):
    """En el mapa real: inicio, meta y 3 candidatos; caminos válidos y métricas recomputadas."""
    cands = v3.candidatos_ciencia(mapa_real, capas)[:3]
    ini = tuple(int(x) for x in capas["ruta_rc"][0]); fin = tuple(int(x) for x in capas["ruta_rc"][-1])
    nodos = [ini, fin] + [c["celda"] for c in cands]
    v = v3.Ventana.alrededor(mapa_real, nodos)
    T = v3.matriz_tramos(v, nodos, v3.ROVER)
    assert T.alcanzable[0, 1]
    for (perfil, i, j), cam in T.caminos.items():
        assert cam[0] == nodos[i] and cam[-1] == nodos[j]
        for p, q in zip(cam[:-1], cam[1:]):
            assert movimiento_valido(mapa_real, p, q)
        ref = metricas_ref(mapa_real, cam, v3.ROVER)
        for key in ("km", "h", "wh", "riesgo_km"):
            assert np.isclose(T.get(perfil, key)[i, j], ref[key], rtol=1e-6)
    # el perfil seguro nunca tiene más km de riesgo que el normal... no es garantía; sí: costo seguro >= normal
    assert np.all(T.get("seguro", "costo") >= T.get("normal", "costo") - 1e-6)
