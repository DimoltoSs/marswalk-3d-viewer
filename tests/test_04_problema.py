"""4, 5, 7. Problema.evaluar, presupuesto/reserva, 2-opt / or-opt, _rellenar (delta), codificación."""
import itertools

import numpy as np
import pytest
from hypothesis import assume, given, settings, strategies as st

from conftest import mapa_aleatorio, metricas_ref, mk_mapa, v3


def construir(seed, cerrado, K=5, ag=v3.ROVER, pres=None, reserva=0.1, n=12):
    rng = np.random.default_rng(seed)
    mapa = mapa_aleatorio(rng, n, n, p_bloq=0.08, dz=10)
    libres = np.argwhere(np.isfinite(mapa.costo))
    pick = rng.choice(len(libres), (1 if cerrado else 2) + K, replace=False)
    nodos = [tuple(int(x) for x in libres[i]) for i in pick]
    T = v3.matriz_tramos(v3.Ventana.alrededor(mapa, nodos), nodos, ag)
    ciencia = list(rng.uniform(0.1, 1.0, K))
    mins = list(rng.choice(["A", "B", "C"], K))
    if pres is None:
        pres = {"h": float(rng.uniform(5, 40)), "wh": float(rng.uniform(200, 3000))}
    op = v3.OpcionesGA(reserva_energia=reserva)
    return mapa, T, v3.Problema(T, ciencia, mins, ag, pres, cerrado, op)


@settings(max_examples=60, deadline=None)
@given(st.integers(0, 10**6), st.booleans(), st.data())
def test_evaluar_igual_a_camino_recomputado(seed, cerrado, data):
    mapa, T, pb = construir(seed, cerrado)
    seq = data.draw(st.permutations(range(pb.primer, pb.primer + pb.K)))[:data.draw(st.integers(0, pb.K))]
    perf = tuple(data.draw(st.lists(st.sampled_from(["normal", "seguro"]), min_size=len(seq) + 1,
                                    max_size=len(seq) + 1)))
    m = pb.evaluar(seq, perf)
    nodos = pb.ruta(seq)
    if not all(T.alcanzable[a, b] for a, b in zip(nodos[:-1], nodos[1:])):
        assert m is None
        return
    # suma por tramo usando los caminos guardados
    tot = dict(km=0, h=0, wh=0, riesgo_km=0)
    for p, (a, b) in zip(perf, zip(nodos[:-1], nodos[1:])):
        if a == b:
            continue
        r = metricas_ref(mapa, T.caminos[(p, a, b)], pb.agente)
        for k in tot:
            tot[k] += r[k]
    est = pb.agente.horas_por_objetivo * len(seq)
    assert np.isclose(m["km"], tot["km"]) and np.isclose(m["riesgo_km"], tot["riesgo_km"])
    assert np.isclose(m["h"], tot["h"] + est)
    assert np.isclose(m["wh"], tot["wh"] + pb.agente.w_estudio * est)
    # el camino concatenado tiene la misma longitud (misión cerrada vacía: ver test_BUG_camino_mision_cerrada_vacia)
    if cerrado and not seq:
        return
    cam = v3.camino_mision(T, pb, m)
    assert np.isclose(metricas_ref(mapa, cam, pb.agente)["km"], m["km"])
    # factible / violación coherentes
    assert pb.factible(m) == all(x <= 1e-9 for x in pb.violacion(m))


def test_reserva_energia_se_aplica():
    _, T, pb = construir(1, False, pres={"h": 1e9, "wh": 1000.0}, reserva=0.25)
    assert pb.pres["wh"] == 750.0
    m = pb.evaluar(())
    m2 = dict(m, wh=760.0)
    assert not pb.factible(m2) and pb.violacion(m2)[1] == pytest.approx(10.0)


def test_astronauta_metabolico_con_presupuesto_wh():
    """v4: el ASTRONAUTA gasta energía metabólica (Pandolf + Santee) y 'factor' crea un presupuesto 'wh'
    que todas las misiones del frente respetan (con la reserva)."""
    c = np.ones((15, 15)); mapa = mk_mapa(c)
    cands = [{"celda": (3, 10), "ciencia": 0.5, "mineral": "A"}]
    plan = v3.planear(mapa, cands, (0, 0), (14, 14), v3.ASTRONAUTA, factor=3.0,
                      op=v3.OpcionesGA(pop_size=10, max_gen=3, ils_iter=2))
    assert "wh" in plan["presupuesto"]
    assert all(0 < m["wh"] <= plan["presupuesto"]["wh"] + 1e-9 for m in plan["frente"])


def _costo_orden(pb, s, M):
    fin = 0 if pb.cerrado else 1
    r = [0, *s, fin]
    return sum(M[a][b] for a, b in zip(r[:-1], r[1:]))


@settings(max_examples=150, deadline=None)
@given(st.integers(0, 10**6), st.booleans(), st.integers(0, 7))
def test_two_opt_y_or_opt_no_empeoran(seed, cerrado, L):
    rng = np.random.default_rng(seed)
    K = 8
    pb = object.__new__(v3.Problema)
    pb.cerrado = cerrado
    N = K + (1 if cerrado else 2)
    M = rng.random((N, N)) * 10
    M[rng.random((N, N)) < 0.1] = 1e9            # tramos inalcanzables como en _matriz_busqueda
    np.fill_diagonal(M, 0)
    M = M.tolist()
    prim = 1 if cerrado else 2
    seq = list(rng.permutation(range(prim, N))[:L])
    s2 = pb._two_opt(seq, M)
    s3 = pb._or_opt(s2, M)
    s4 = pb._or_opt(seq, M)
    for s in (s2, s3, s4):
        assert sorted(s) == sorted(seq)
    assert _costo_orden(pb, s2, M) <= _costo_orden(pb, seq, M) + 1e-9
    assert _costo_orden(pb, s3, M) <= _costo_orden(pb, s2, M) + 1e-9
    assert _costo_orden(pb, s4, M) <= _costo_orden(pb, seq, M) + 1e-9


@settings(max_examples=60, deadline=None)
@given(st.integers(0, 10**6), st.booleans(), st.data())
def test_delta_insercion_igual_a_reevaluacion(seed, cerrado, data):
    """Fórmula de _rellenar: M[a][k]+M[k][b]-M[a][b]+estudio == evaluar(nueva)-evaluar(seq)."""
    _, T, pb = construir(seed, cerrado)
    seq = data.draw(st.permutations(range(pb.primer, pb.primer + pb.K)))[:data.draw(st.integers(0, pb.K - 1))]
    m = pb.evaluar(seq)
    assume(m is not None)
    fin = 0 if cerrado else 1
    ruta = [0, *seq, fin]
    est = {"h": pb.agente.horas_por_objetivo, "wh": pb.agente.w_estudio * pb.agente.horas_por_objetivo}
    for k in set(range(pb.primer, pb.primer + pb.K)) - set(seq):
        for pos in range(len(ruta) - 1):
            a, b = ruta[pos], ruta[pos + 1]
            nueva = pb.evaluar(seq[:pos] + [k] + seq[pos:])
            if nueva is None:
                continue
            for r in ("h", "wh"):
                Mx = pb._L[("normal", r)]
                d = Mx[a][k] + Mx[k][b] - Mx[a][b] + est[r]
                assert np.isclose(m[r] + d, nueva[r], rtol=1e-9, atol=1e-9)


@settings(max_examples=60, deadline=None)
@given(st.integers(0, 10**6), st.booleans(), st.data())
def test_rellenar_no_devuelve_infactible(seed, cerrado, data):
    _, T, pb = construir(seed, cerrado)
    seq0 = data.draw(st.permutations(range(pb.primer, pb.primer + pb.K)))[:data.draw(st.integers(0, 2))]
    m0 = pb.evaluar(seq0)
    seq, m = pb._rellenar(seq0, rng=np.random.default_rng(seed) if seed % 2 else None)
    if m is not None:
        assert m == pb.evaluar(seq)                    # métricas reales, no estimadas
    if pb.factible(m0):
        assert pb.factible(m)                          # partiendo de factible no se sale del presupuesto
        assert set(seq0) <= set(seq)


@settings(max_examples=200, deadline=None)
@given(st.integers(0, 12), st.integers(1, 3), st.data())
def test_codificar_decodificar_roundtrip(K, primer, data):
    seq = tuple(data.draw(st.permutations(range(primer, primer + K)))[:data.draw(st.integers(0, K))])
    x = v3._codificar(seq, K, primer, np.random.default_rng(K))
    assert np.all((x >= 0) & (x <= 1))
    assert v3._decodificar(x, primer) == seq


def test_BUG_camino_mision_cerrada_vacia():
    """camino_mision de la misión cerrada vacía (0 -> 0) lanza KeyError: no hay T.caminos[(p,0,0)]."""
    _, T, pb = construir(0, True)
    m = pb.evaluar(())
    assert m is not None and pb.factible(m)
    assert v3.camino_mision(T, pb, m) == [T.nodos[0]]
