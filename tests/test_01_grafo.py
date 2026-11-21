"""1. Ventana.grafo: aristas, bloqueos, esquinas, fórmula de peso, asimetría, perfil seguro."""
import numpy as np
from hypothesis import given, settings, strategies as st

from conftest import mapa_aleatorio, movimiento_valido, peso_ref, v3, VEC


def _aristas(mapa, seguro):
    v = v3.Ventana.alrededor(mapa, [(0, 0), (mapa.forma[0] - 1, mapa.forma[1] - 1)])
    g = v.grafo(seguro).tocoo()
    m = v.costo.shape[1]
    return {(divmod(int(o), m), divmod(int(d), m)): float(w) for o, d, w in zip(g.row, g.col, g.data)}


@settings(max_examples=60, deadline=None)
@given(st.integers(0, 10**6), st.integers(2, 9), st.integers(2, 9), st.booleans())
def test_aristas_validas_y_completas(seed, n, m, seguro):
    mapa = mapa_aleatorio(np.random.default_rng(seed), n, m, p_bloq=0.3)
    E = _aristas(mapa, seguro)
    for (a, b), w in E.items():
        assert movimiento_valido(mapa, a, b), (a, b)          # nada toca inf, sin cortar esquinas
        assert np.isclose(w, peso_ref(mapa, a, b, seguro), rtol=1e-12)
    # completitud: todo movimiento válido existe como arista
    for f in range(n):
        for c in range(m):
            for df, dc in VEC:
                if movimiento_valido(mapa, (f, c), (f + df, c + dc)):
                    assert ((f, c), (f + df, c + dc)) in E


def test_diagonal_bloqueada_por_un_ortogonal():
    c = np.ones((2, 2)); c[0, 1] = np.inf
    from conftest import mk_mapa
    E = _aristas(mk_mapa(c), False)
    assert ((0, 0), (1, 1)) not in E and ((1, 1), (0, 0)) not in E
    assert ((0, 0), (1, 0)) in E


@settings(max_examples=40, deadline=None)
@given(st.integers(0, 10**6))
def test_asimetria_subida_bajada(seed):
    mapa = mapa_aleatorio(np.random.default_rng(seed), 5, 5, p_bloq=0.1, dz=30)
    E = _aristas(mapa, False)
    for (a, b), w in E.items():
        dz = mapa.dem[b] - mapa.dem[a]
        assert np.isclose(w - E[(b, a)], 8.0 * dz, atol=1e-9)    # w_subida * dz


@settings(max_examples=40, deadline=None)
@given(st.integers(0, 10**6))
def test_seguro_solo_multiplica_celdas_de_riesgo(seed):
    mapa = mapa_aleatorio(np.random.default_rng(seed), 6, 6, p_bloq=0.1)
    En, Es = _aristas(mapa, False), _aristas(mapa, True)
    assert En.keys() == Es.keys()
    for e in En:
        a, b = e
        if not (mapa.riesgo[a] or mapa.riesgo[b]):
            assert En[e] == Es[e]
        else:
            assert Es[e] > En[e]
