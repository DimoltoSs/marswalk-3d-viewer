"""3. Ventana.alrededor: radio, bordes, recorte de margen, índices locales."""
import math

import numpy as np
from hypothesis import given, settings, strategies as st

from conftest import mapa_aleatorio, mk_mapa, v3


@settings(max_examples=80, deadline=None)
@given(st.integers(0, 10**6), st.integers(1, 30), st.integers(1, 30), st.integers(1, 4),
       st.floats(0, 600), st.one_of(st.none(), st.floats(0, 500)))
def test_ventana_recorte_y_radio(seed, n, m, k, margen, radio):
    rng = np.random.default_rng(seed)
    mapa = mapa_aleatorio(rng, n, m, p_bloq=0.1)
    nodos = [(int(rng.integers(n)), int(rng.integers(m))) for _ in range(k)]
    v = v3.Ventana.alrededor(mapa, nodos, margen_m=margen, centro=nodos[0], radio_m=radio)
    mc = int(margen // 20)
    a = np.array(nodos)
    assert v.f0 == max(0, a[:, 0].min() - mc) and v.c0 == max(0, a[:, 1].min() - mc)
    assert v.f0 + v.costo.shape[0] == min(n, a[:, 0].max() + mc + 1)
    assert v.c0 + v.costo.shape[1] == min(m, a[:, 1].max() + mc + 1)
    for nd in nodos:   # todos los nodos dentro y local() coherente
        li = v.local(nd)
        assert divmod(li, v.costo.shape[1]) == (nd[0] - v.f0, nd[1] - v.c0)
    orig = v.sl(mapa.costo)
    for f in range(v.costo.shape[0]):
        for c in range(v.costo.shape[1]):
            fuera = radio is not None and 20 * math.hypot(f + v.f0 - nodos[0][0], c + v.c0 - nodos[0][1]) > radio
            if fuera:
                assert np.isinf(v.costo[f, c])
            else:
                assert v.costo[f, c] == orig[f, c] or (np.isinf(v.costo[f, c]) and np.isinf(orig[f, c]))
    assert np.isinf(mapa.costo).sum() == (~np.isfinite(mapa.costo)).sum()   # mapa original intacto


def test_radio_bloquea_camino_por_fuera():
    """Un muro con hueco fuera del radio: dentro del radio no hay camino."""
    c = np.ones((11, 11)); c[5, :] = np.inf; c[5, 10] = 1.0    # hueco en la esquina
    mapa = mk_mapa(c)
    nodos = [(2, 2), (8, 2)]
    sin = v3.matriz_tramos(v3.Ventana.alrededor(mapa, nodos, margen_m=400), nodos, v3.ROVER)
    con = v3.matriz_tramos(v3.Ventana.alrededor(mapa, nodos, margen_m=400, centro=(2, 2), radio_m=150),
                           nodos, v3.ROVER)
    assert sin.alcanzable[0, 1] and not con.alcanzable[0, 1]


def test_nodos_en_bordes_y_margen_cero():
    c = np.ones((4, 4))
    mapa = mk_mapa(c)
    nodos = [(0, 0), (3, 3)]
    v = v3.Ventana.alrededor(mapa, nodos, margen_m=0)
    assert v.costo.shape == (4, 4)
    T = v3.matriz_tramos(v, nodos, v3.ROVER)
    assert T.alcanzable[0, 1] and np.isclose(T.get("normal", "km")[0, 1], 3 * 20 * math.sqrt(2) / 1000)
