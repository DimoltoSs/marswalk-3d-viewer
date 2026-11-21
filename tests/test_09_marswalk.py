"""Pruebas de lo nuevo en Marswalk v4: arena, duda de la IA, verificación del robot, regreso y punto de no
retorno, recta exacta de simplificar, perfil por tramo y regresión de Séítah."""
import json
import math
import os

import networkx as nx
import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from conftest import v3

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def capas_planas(n=12, arena=None):
    L = {"pendiente": np.full((n, n), 2.0, np.float32), "dem": np.zeros((n, n), np.float32)}
    if arena is not None:
        L["arena_textura"] = arena.astype(np.uint8)
    return L


def test_arena_encarece_y_marca():
    ar = np.zeros((12, 12), bool); ar[4:8, 4:8] = True
    m = v3.Mapa.desde_capas(capas_planas(arena=ar))
    assert (m.costo[ar] - m.costo[~ar].max() >= v3.P["w_arena"] - 1e-9).all()
    assert m.arena[ar].all() and m.duna[ar].all() and (m.origen[ar] == 1).all()


def test_ia_duda_y_robot_verifica():
    n = 12
    prob = np.full((n, n), np.nan); prob[2, 2] = 0.5; prob[3, 3] = 0.9; prob[4, 4] = 0.1
    m = v3.Mapa.desde_capas(capas_planas(n), prob_arena=prob)
    assert m.incierto[2, 2] and not m.incierto[3, 3] and not m.incierto[4, 4]
    assert m.arena[3, 3] and not m.arena[4, 4] and m.origen[3, 3] == 2
    # el robot verifica: (2,2) era duda -> firme; (3,3) la IA decía arena -> el robot dice firme
    m2 = v3.Mapa.desde_capas(capas_planas(n), prob_arena=prob, verificadas={(2, 2): "firme", (3, 3): "firme"})
    assert not m2.incierto[2, 2] and not m2.arena[3, 3] and m2.origen[3, 3] == 3
    assert m2.costo[3, 3] < m.costo[3, 3]
    m3 = v3.Mapa.desde_capas(capas_planas(n), verificadas={(5, 5): "arena"})
    assert m3.arena[5, 5] and m3.origen[5, 5] == 3


def test_replanear_rodea_arena_verificada():
    n = 15
    m0 = v3.Mapa.desde_capas(capas_planas(n))
    r0 = v3.replanear_tramo(m0, (7, 0), (7, 14))
    muro = {(f, 7): "arena" for f in range(2, 13)}
    m1 = v3.Mapa.desde_capas(capas_planas(n), verificadas=muro)
    r1 = v3.replanear_tramo(m1, (7, 0), (7, 14))
    assert r1["km"] > r0["km"]
    assert not any(tuple(c) in muro for c in r1["camino"])


def test_costo_regreso_contra_networkx():
    rng = np.random.default_rng(3)
    n = 14
    L = {"pendiente": (rng.random((n, n)) * 18).astype(np.float32), "dem": (rng.random((n, n)) * 6).astype(np.float32)}
    L["pendiente"][rng.random((n, n)) < 0.1] = 25.0
    m = v3.Mapa.desde_capas(L)
    base = (7, 7)
    if m.bloqueado[base]:
        pytest.skip("base bloqueada")
    r = v3.costo_regreso(m, base, v3.ASTRONAUTA, radio_m=10_000)
    assert r["wh"][base] == 0
    # referencia: grafo dirigido con energía Pandolf por arista a->b, Dijkstra de cada celda hacia la base
    G = nx.DiGraph()
    ag = v3.ASTRONAUTA
    for f in range(n):
        for c in range(n):
            for df, dc in v3.VECINOS:
                g, k = f + df, c + dc
                if not (0 <= g < n and 0 <= k < n) or m.bloqueado[f, c] or m.bloqueado[g, k]:
                    continue
                if df and dc and (m.bloqueado[f, k] or m.bloqueado[g, c]):
                    continue
                dh = 20 * math.hypot(df, dc); dz = m.dem[g, k] - m.dem[f, c]
                lento = m.riesgo[g, k] or m.duna[g, k]
                vel = ag.vel_riesgo_m_h if lento else ag.vel_seguro_m_h
                t = math.hypot(dh, dz) / vel
                w = float(v3.pandolf_w(ag, np.array(vel / 3600), np.array(100 * dz / dh), ag.eta_terreno)) * t
                G.add_edge((f, c), (g, k), weight=w)
    ref = nx.single_source_dijkstra_path_length(G.reverse(copy=True), base)
    for celda, val in ref.items():
        assert abs(r["wh"][celda] - val) < 1e-6 * max(1, val)
    alcanz = np.isfinite(r["wh"])
    assert alcanz.sum() == len(ref)


def test_punto_de_no_retorno():
    n = 40
    m = v3.Mapa.desde_capas(capas_planas(n))
    base = (20, 0)
    reg = v3.costo_regreso(m, base, v3.ASTRONAUTA, radio_m=50_000)
    camino = [(20, c) for c in range(n)]
    ida = v3.perfil_regreso(m, camino, reg, v3.ASTRONAUTA, presupuesto_wh=1e9)
    total = ida["gastado_wh"][-1] + ida["regreso_wh"][-1]
    # presupuesto justo para llegar a la mitad y volver -> el punto de no retorno cae cerca de la mitad
    pres = (ida["gastado_wh"][n // 2] + ida["regreso_wh"][n // 2]) / 0.9
    p = v3.perfil_regreso(m, camino, reg, v3.ASTRONAUTA, presupuesto_wh=pres)
    assert p["punto_no_retorno"] is not None and n // 2 <= p["punto_no_retorno"] <= n // 2 + 1
    assert v3.perfil_regreso(m, camino, reg, v3.ASTRONAUTA, presupuesto_wh=total / 0.9 + 1)["punto_no_retorno"] is None
    # O2 coherente con la energía
    assert abs(p["o2_gastado_L"][-1] - p["gastado_wh"][-1] * v3.O2_L_POR_WH) < 1e-9


@settings(max_examples=200, deadline=None)
@given(st.integers(0, 12), st.integers(0, 12), st.integers(0, 12), st.integers(0, 12))
def test_celdas_segmento_cubre_muestreo_denso(f0, c0, f1, c1):
    celdas, peso = v3._celdas_segmento((f0, c0), (f1, c1))
    conj = {tuple(x) for x in celdas}
    t = (np.arange(3000) + 0.5) / 3000
    pts = np.array([f0, c0], float) + np.outer(t, np.array([f1 - f0, c1 - c0], float))
    densas = {tuple(x) for x in np.floor(pts + 0.5).astype(int)}
    assert densas <= conj
    assert abs(peso.sum() - 1.0) < 1e-9


def test_perfil_por_tramo_rescata_mision():
    """Punto ciego de v3: el conjunto solo cabe si los tramos usan la ruta 'segura', que aquí es más rápida.
    Tramos sintéticos: 0 = base (EVA cerrada), 1 = objetivo. normal: 3 h por tramo; seguro: 2 h por tramo."""
    T = v3.Tramos([(0, 0), (0, 5)], ["normal", "seguro"])
    T.alcanzable = np.ones((2, 2), bool)
    for perfil, h in (("normal", 3.0), ("seguro", 2.0)):
        for k in v3.METRICAS:
            T.M[(perfil, k)] = np.zeros((2, 2))
        T.M[(perfil, "h")] = np.array([[0.0, h], [h, 0.0]])
    pb = v3.Problema(T, [1.0], ["X"], v3.ASTRONAUTA, {"h": 5.0}, True, v3.OpcionesGA())
    m = pb.resolver((1,))
    assert pb.factible(m) and m["ciencia"] == pytest.approx(1.0) and set(m["perfiles"]) == {"seguro"}
    assert any(x["seq"] == (1,) for x in pb.archivo)
    sin = v3.Problema(T, [1.0], ["X"], v3.ASTRONAUTA, {"h": 5.0}, True, v3.OpcionesGA(perfiles_ruta=False))
    assert not sin.factible(sin.resolver((1,)))       # sin perfiles por tramo no cabe


def test_regresion_seitah_tramo_B():
    """Con la capa de arena (v4), el tramo reservado B queda a < 200 m de media de la ruta real (v3: ~498 m)."""
    from shapely.geometry import LineString
    from proto1_capas import cargar, rc_a_xy, xy_a_rc
    from validar_seitah import metricas
    ruta = os.path.join(RAIZ, "data", "processed", "m20_tramos_ABC.geojson")
    if not os.path.exists(ruta):
        pytest.skip("falta m20_tramos_ABC.geojson (correr herramientas/preparar_capas_marswalk.py)")
    L = cargar()
    f = next(x for x in json.load(open(ruta))["features"] if x["properties"]["tramo"] == "B")
    real = LineString(f["geometry"]["coordinates"])
    a = tuple(int(x) for x in xy_a_rc(*real.coords[0])); b = tuple(int(x) for x in xy_a_rc(*real.coords[-1]))
    r = v3.replanear_tramo(v3.Mapa.desde_capas({k: v for k, v in L.items() if k != "pendiente_hirise_p95"}), a, b)
    cam = np.asarray(r["camino"])
    assert metricas(LineString(np.c_[rc_a_xy(cam[:, 0], cam[:, 1])]), real)["simetrica_m"] < 200


def test_regreso_mision_coincide_con_la_mision(mapa_real, capas):
    """La energía acumulada al final de una EVA (caminar + paradas) es exactamente el 'wh' de la misión."""
    base = tuple(int(x) for x in capas["ruta_rc"][0])
    cands = v3.candidatos_ciencia(mapa_real, capas)
    plan = v3.planear(mapa_real, cands, base, None, v3.ASTRONAUTA, presupuesto={"h": 6.0, "wh": 1408.0}, radio_m=2500)
    m = plan["frente"][plan["nombradas"]["ciencia"]]
    reg = v3.costo_regreso(mapa_real, base, v3.ASTRONAUTA, radio_m=3000)
    r = v3.regreso_mision(mapa_real, plan["tramos"], plan["problema"], m, reg, 1408.0)
    assert r["gastado_wh"][-1] == pytest.approx(m["wh"], rel=1e-9)
    assert r["regreso_wh"][-1] == pytest.approx(0.0, abs=1e-9)
    assert r["punto_no_retorno"] is None
    r2 = v3.regreso_mision(mapa_real, plan["tramos"], plan["problema"], m, reg, m["wh"] * 0.9)
    assert r2["punto_no_retorno"] is not None


def test_parametros_por_agente_y_ruta_real(capas):
    """El rover usa P_ROVER (bloqueo 30°) y el astronauta P (20°). Con la pendiente fina, P_ROVER no bloquea
    ninguna celda de la ruta real de Perseverance; el mensaje de error usa el umbral del mapa."""
    assert v3.parametros(v3.ROVER) is v3.P_ROVER and v3.parametros(v3.ASTRONAUTA) is v3.P
    m = v3.Mapa.desde_capas(capas, p=v3.parametros(v3.ROVER))
    assert m.params["pend_max"] == 30.0
    rc = capas["ruta_rc"]
    assert not m.bloqueado[rc[:, 0], rc[:, 1]].any()


def test_mensaje_sin_camino_usa_umbral_del_mapa():
    n = 12
    L = capas_planas(n)
    L["pendiente"] = L["pendiente"].copy()
    L["pendiente"][:, n // 2] = 25.0          # muro de 25°: bloquea con P (20°), no con P_ROVER (30°)
    m = v3.Mapa.desde_capas(L)
    with pytest.raises(ValueError, match="20°"):
        v3.planear(m, [], (5, 1), (5, n - 2), v3.ASTRONAUTA, factor=2.0)
    m2 = v3.Mapa.desde_capas(L, p=v3.P_ROVER)
    plan = v3.planear(m2, [], (5, 1), (5, n - 2), v3.ROVER, factor=2.0)
    assert plan["frente"]
