"""6, 9, 11. Archivo de Pareto, _recortar, nombrar/elegir, casos borde y determinismo (sintético)."""
import math

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from conftest import mapa_aleatorio, mk_mapa, v3

OP = dict(pop_size=20, max_gen=15, ils_iter=5, timeout_s=60)


def escenario(seed, n=25, K=8, p_bloq=0.1):
    rng = np.random.default_rng(seed)
    mapa = mapa_aleatorio(rng, n, n, p_bloq=p_bloq, dz=15)
    mapa.costo[0, 0] = mapa.costo[n - 1, n - 1] = 1.0
    mapa.bloqueado[:] = ~np.isfinite(mapa.costo)
    libres = np.argwhere(np.isfinite(mapa.costo))
    cands = [{"celda": tuple(int(x) for x in libres[i]), "ciencia": float(rng.uniform(0.1, 1)),
              "mineral": str(rng.choice(["A", "B", "C"]))} for i in rng.choice(len(libres), K, replace=False)]
    return mapa, cands


def domina(a, b):
    return np.all(a <= b) and np.any(a < b)


def check_frente(plan):
    pb, fr = plan["problema"], plan["frente"]
    F = [pb.objetivos(m) for m in pb.archivo]
    for i in range(len(F)):
        assert pb.factible(pb.archivo[i])
        for j in range(len(F)):
            if i != j:
                assert not domina(F[i], F[j]), "archivo con dominados"
                assert not np.allclose(F[i], F[j], atol=1e-6, rtol=0), "duplicados"
    # el frente está ordenado como dice planear
    claves = [(-m["ciencia"], m["h"], m["riesgo_km"]) for m in fr]
    assert claves == sorted(claves)
    for k, i in plan["nombradas"].items():
        assert 0 <= i < len(fr)
    # métricas guardadas == re-evaluación
    for m in fr:
        assert m == pb.evaluar(m["seq"], m["perfiles"])
    return pb, fr


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("cerrado", [False, True])
def test_planear_archivo_valido(seed, cerrado):
    mapa, cands = escenario(seed)
    n = mapa.forma[0]
    if cerrado:
        plan = v3.planear(mapa, cands, (0, 0), None, v3.ROVER, presupuesto={"h": 30, "wh": 3000},
                          op=v3.OpcionesGA(**OP))
    else:
        try:
            plan = v3.planear(mapa, cands, (0, 0), (n - 1, n - 1), v3.ROVER, factor=2.5, op=v3.OpcionesGA(**OP))
        except ValueError:
            pytest.skip("A y B desconectados en este mapa")
    pb, fr = check_frente(plan)
    if cerrado:
        assert all(m["seq"] for m in fr)
    # nombradas son óptimas en su objetivo
    if fr:
        assert fr[plan["nombradas"]["ciencia"]]["ciencia"] == max(m["ciencia"] for m in fr)
        assert fr[plan["nombradas"]["rapida"]]["h"] == min(m["h"] for m in fr)


@settings(max_examples=100, deadline=None)
@given(st.integers(0, 10**6), st.integers(2, 40), st.integers(1, 20))
def test_recortar_conserva_extremos(seed, n, k):
    rng = np.random.default_rng(seed)
    F = rng.random((n, 3))
    misiones = [{"ciencia": -f[0], "h": f[1], "riesgo_km": f[2], "id": i} for i, f in enumerate(F)]
    out = v3._recortar(misiones, k)
    assert len(out) == min(n, k)
    ids = [m["id"] for m in out]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    if n > k and k >= 6:
        for j in range(3):
            assert int(np.argmin(F[:, j])) in ids and int(np.argmax(F[:, j])) in ids


def test_k0_abierta_y_cerrada():
    mapa = mk_mapa(np.ones((10, 10)))
    plan = v3.planear(mapa, [], (0, 0), (9, 9), v3.ROVER, factor=2.0, op=v3.OpcionesGA(**OP))
    assert [m["seq"] for m in plan["frente"]] == [()]
    plan = v3.planear(mapa, [], (0, 0), None, v3.ROVER, op=v3.OpcionesGA(**OP))
    assert plan["frente"] == [] and plan["nombradas"] == {}


def test_k1():
    mapa = mk_mapa(np.ones((10, 10)))
    c = [{"celda": (2, 7), "ciencia": 0.5, "mineral": "A"}]
    plan = v3.planear(mapa, c, (0, 0), (9, 9), v3.ROVER, factor=10.0, op=v3.OpcionesGA(**OP))
    check_frente(plan)
    assert (2,) in [m["seq"] for m in plan["frente"]]


def test_meta_inalcanzable_valueerror():
    c = np.ones((10, 10)); c[5, :] = np.inf
    with pytest.raises(ValueError):
        v3.planear(mk_mapa(c), [], (0, 0), (9, 9), v3.ROVER, factor=2.0, op=v3.OpcionesGA(**OP))


def test_eva_cerrada_con_radio_filtra_y_respeta_radio():
    mapa = mk_mapa(np.ones((40, 40)))
    cands = [{"celda": (20, 25), "ciencia": 0.5, "mineral": "A"},     # 100 m: dentro
             {"celda": (20, 39), "ciencia": 0.9, "mineral": "B"},     # 380 m: fuera
             {"celda": (5, 5), "ciencia": 0.9, "mineral": "B"}]
    mapa.costo[5, 5] = np.inf; mapa.bloqueado[5, 5] = True             # candidato bloqueado
    plan = v3.planear(mapa, cands, (20, 20), None, v3.ASTRONAUTA, radio_m=200,
                      presupuesto={"h": 10}, op=v3.OpcionesGA(**OP))
    assert [c["celda"] for c in plan["candidatos"]] == [(20, 25)]
    pb = plan["problema"]
    for m in plan["frente"]:
        for cel in v3.camino_mision(plan["tramos"], pb, m):
            assert 20 * math.hypot(cel[0] - 20, cel[1] - 20) <= 200


def test_radio_m_con_meta_es_error():
    """Corregido (B5): radio_m solo aplica a misiones de ida y vuelta; con meta, error explícito."""
    mapa = mk_mapa(np.ones((40, 40)))
    cands = [{"celda": (0, 39), "ciencia": 0.9, "mineral": "B"}]
    with pytest.raises(ValueError):
        v3.planear(mapa, cands, (20, 20), (20, 25), v3.ROVER, radio_m=200,
                   presupuesto={"h": 100, "wh": 1e5}, op=v3.OpcionesGA(**OP))


@pytest.mark.parametrize("factor", [1.0, 1.05, 1.1])
def test_mision_infactible_marcada(factor):
    """Corregido (B2): si ni la ruta directa cabe (reserva de energía), se devuelve marcada factible=False
    y con aviso; toda misión sin marca es factible."""
    mapa = mk_mapa(np.ones((30, 30)))
    plan = v3.planear(mapa, [], (0, 0), (29, 29), v3.ROVER, factor=factor, op=v3.OpcionesGA(**OP))
    pb = plan["problema"]
    for m in plan["frente"]:
        assert pb.factible(m) or (m.get("factible") is False and plan["aviso"])


def test_nan_en_pendiente_bloquea():
    pend = np.full((6, 6), 5.0); pend[2, :5] = np.nan
    L = {"pendiente": pend.astype(np.float32), "dem": np.zeros((6, 6), np.float32)}
    mapa = v3.Mapa.desde_capas(L)
    assert mapa.bloqueado[2, :5].all() and np.isinf(mapa.costo[2, :5]).all()
    assert not mapa.riesgo[2, :5].any() and np.isfinite(mapa.costo[~mapa.bloqueado]).all()
    nodos = [(0, 0), (5, 0)]
    T = v3.matriz_tramos(v3.Ventana.alrededor(mapa, nodos), nodos, v3.ROVER)
    cam = T.caminos[("normal", 0, 1)]
    assert all(not mapa.bloqueado[c] for c in cam) and (2, 5) in cam
    assert np.isfinite(T.get("normal", "pend_max")[0, 1])


def test_determinismo_misma_semilla():
    mapa, cands = escenario(3)
    run = lambda: v3.planear(mapa, cands, (0, 0), (24, 24), v3.ROVER, factor=2.5,  # noqa: E731
                             op=v3.OpcionesGA(**OP))["frente"]
    a, b = run(), run()
    assert [(m["seq"], m["perfiles"]) for m in a] == [(m["seq"], m["perfiles"]) for m in b]
