"""Pruebas de eva_avanzada.py (antes eva_pareja.py): EVA en pareja (oxígeno de cada uno y rescate con un compañero lesionado) y radio."""
import numpy as np
import pytest

from conftest import v3

import eva_avanzada as ep


def mapa_plano(n=60, dem=None):
    L = {"pendiente": np.full((n, n), 2.0, np.float32),
         "dem": np.zeros((n, n), np.float32) if dem is None else dem.astype(np.float32)}
    return v3.Mapa.desde_capas(L, p=v3.parametros(v3.ASTRONAUTA))


def ida_y_vuelta(base, lejos):
    """Camino recto base -> (base[0], lejos) -> base, celda por celda; parada en el extremo."""
    ida = [(base[0], c) for c in range(base[1], lejos + 1)]
    return ida + ida[-2::-1], [len(ida) - 1]


def test_regresos_coincide_con_costo_regreso():
    rng = np.random.default_rng(3)
    L = {"pendiente": (rng.random((40, 40)) * 25).astype(np.float32),
         "dem": (rng.random((40, 40)) * 30).astype(np.float32)}
    mapa = v3.Mapa.desde_capas(L, p=v3.parametros(v3.ASTRONAUTA))
    base = (20, 20)
    mapa.costo[base] = mapa.costo[base] if np.isfinite(mapa.costo[base]) else 1.0
    ref = v3.costo_regreso(mapa, base, v3.ASTRONAUTA, radio_m=500)
    r = ep.regresos(mapa, base, {"a": v3.ASTRONAUTA}, 500)
    assert np.allclose(np.nan_to_num(ref["wh"], nan=-1), np.nan_to_num(r["a"], nan=-1))
    assert np.allclose(np.nan_to_num(ref["h"], nan=-1), np.nan_to_num(r["h"], nan=-1))


def test_regreso_asistido_cuesta_mas_y_tarda_el_doble():
    mapa, base = mapa_plano(), (30, 30)
    normal = ep.regresos(mapa, base, {"a": v3.ASTRONAUTA}, 600)
    lento = ep.regresos(mapa, base, {"a": v3.ASTRONAUTA}, 600, vel_factor=ep.VEL_ASISTIDA)
    lejos = (30, 50)
    assert lento["h"][lejos] == pytest.approx(normal["h"][lejos] / ep.VEL_ASISTIDA)
    assert lento["a"][lejos] > normal["a"][lejos]


def test_pareja_con_mucho_oxigeno_tiene_rescate_y_con_poco_no():
    mapa, base = mapa_plano(), (30, 5)
    camino, paradas = ida_y_vuelta(base, 55)            # 1 km de ida
    holgada = ep.perfil_pareja(mapa, camino, paradas, base, [{"masa_kg": 80, "o2_L": 380}, {"masa_kg": 70, "o2_L": 380}])
    assert holgada["rescate"]["sin_rescate"] is None and holgada["punto_no_retorno"] is None
    assert len(holgada["rescate"]["margen_L"]) == len(camino) == len(holgada["tanque_pct"])
    justa = ep.perfil_pareja(mapa, camino, paradas, base, [{"masa_kg": 80, "o2_L": 45}, {"masa_kg": 70, "o2_L": 45}])
    sr = justa["rescate"]["sin_rescate"]
    assert sr is not None and 0 < sr < len(camino)
    assert justa["rescate"]["metros_hasta_sin_rescate"] > 0
    # el rescate es más exigente que el regreso normal: se pierde antes (o igual) que el punto de no retorno
    if justa["punto_no_retorno"] is not None:
        assert sr <= justa["punto_no_retorno"]


def test_cada_astronauta_con_su_peso_y_tanque():
    mapa, base = mapa_plano(), (30, 5)
    camino, paradas = ida_y_vuelta(base, 40)
    r = ep.perfil_pareja(mapa, camino, paradas, base, [{"masa_kg": 95, "o2_L": 380}, {"masa_kg": 60, "o2_L": 200}])
    a, b = r["personas"]
    assert a["o2_usado_L"] != b["o2_usado_L"]
    # el tanque más chico deja menos porcentaje al volver; tanque_pct al final = el más justo de los dos
    assert b["o2_final_pct"] < a["o2_final_pct"]
    assert r["tanque_pct"][-1] == pytest.approx(min(a["o2_final_pct"], b["o2_final_pct"]), abs=0.2)


def test_rescate_respeta_las_horas_del_traje():
    mapa, base = mapa_plano(), (30, 5)
    camino, paradas = ida_y_vuelta(base, 55)
    r = ep.perfil_pareja(mapa, camino, paradas, base, ep.PAREJA_DEFECTO, horas_max=0.5)
    assert r["rescate"]["sin_rescate"] is not None


def test_pareja_debe_ser_de_dos():
    mapa, base = mapa_plano(), (30, 5)
    camino, paradas = ida_y_vuelta(base, 20)
    with pytest.raises(ValueError):
        ep.perfil_pareja(mapa, camino, paradas, base, [{"masa_kg": 80, "o2_L": 380}])


def test_radio_en_plano_todo_visible_y_fuera_del_radio_sin_evaluar():
    mapa, base = mapa_plano(), (30, 30)
    cob = ep.cobertura_radio(mapa, base, radio_m=400, paso=1)
    f, c = np.mgrid[0:60, 0:60]
    d = 20.0 * np.hypot(f - 30, c - 30)
    assert (cob[d <= 380] == 1).all()
    assert (cob[d > 420] == -1).all()


def test_una_loma_corta_la_senal_detras():
    dem = np.zeros((60, 60))
    dem[:, 40] = 80.0                                   # muro de 80 m al este del hábitat
    mapa, base = mapa_plano(dem=dem), (30, 30)
    cob = ep.cobertura_radio(mapa, base, radio_m=550, paso=1)
    assert cob[30, 35] == 1                             # antes del muro: hay señal
    assert cob[30, 50] == 0                             # detrás del muro: no
    caro = ep.con_radio(mapa, cob)
    assert caro.costo[30, 50] == pytest.approx(mapa.costo[30, 50] + ep.W_SIN_SENAL)
    assert caro.costo[30, 35] == mapa.costo[30, 35]
    s = ep.senal_en_camino([(30, c) for c in range(30, 55)], cob)
    assert s["senal"][0] is True and s["senal"][-1] is False
    assert s["sin_senal_max_m"] >= 200 and 0 < s["sin_senal_pct"] < 100


def test_la_curvatura_de_marte_tapa_lo_muy_lejano():
    # en plano, con antenas de 10 m y 2 m el horizonte queda a ~11.5 km: a 14 km ya no hay señal
    L = {"pendiente": np.full((20, 900), 2.0, np.float32), "dem": np.zeros((20, 900), np.float32)}
    mapa, base = v3.Mapa.desde_capas(L, p=v3.P), (10, 0)
    cob = ep.cobertura_radio(mapa, base, radio_m=17000, paso=4)
    assert cob[10, 400] == 1                            # 8 km
    assert cob[10, 700] == 0                            # 14 km
