"""Escenario real de Jezero (exportar_mision_v3): archivo, determinismo y efecto del timeout."""
import pytest

from conftest import v3
from test_05_planear import check_frente


@pytest.fixture(scope="module")
def escenario(mapa_real, capas):
    cands = v3.candidatos_ciencia(mapa_real, capas)
    ini = tuple(int(x) for x in capas["ruta_rc"][0]); fin = tuple(int(x) for x in capas["ruta_rc"][-1])
    return cands, ini, fin


def _run(mapa_real, escenario, **kw):
    cands, ini, fin = escenario
    return v3.planear(mapa_real, cands, ini, fin, v3.ROVER, factor=2.0, max_candidatos=15,
                      op=v3.OpcionesGA(semilla=42, **kw))


def _firma(plan):
    return [(m["seq"], m["perfiles"], round(m["ciencia"], 6), round(m["h"], 6)) for m in plan["frente"]]


@pytest.fixture(scope="module")
def plan_ref(mapa_real, escenario):
    return _run(mapa_real, escenario)


def test_real_archivo_y_frente(plan_ref, mapa_real):
    pb, fr = check_frente(plan_ref)
    assert all(pb.factible(m) for m in fr)
    cam = v3.camino_mision(plan_ref["tramos"], pb, fr[v3.elegir(fr, {"ciencia": .5, "tiempo": .3, "riesgo": .2})])
    assert all(not mapa_real.bloqueado[c] for c in cam)


def test_real_determinismo(plan_ref, mapa_real, escenario):
    assert _firma(_run(mapa_real, escenario)) == _firma(plan_ref)


def test_por_defecto_sin_reloj(plan_ref):
    """Corregido (B3): por defecto no hay tiempo límite (timeout_s=None), así que el resultado no depende de la
    velocidad de la máquina. Con un timeout explícito que se alcanza, el resultado SÍ puede cambiar (documentado)."""
    assert v3.OpcionesGA().timeout_s is None
