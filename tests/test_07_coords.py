"""10. xy_a_rc / rc_a_xy y metadatos de malla.json vs rasters."""
import glob
import json
import os

import numpy as np
import rasterio
from hypothesis import given, settings, strategies as st

from conftest import REPO
from proto1_capas import rc_a_xy, xy_a_rc

P = os.path.join(REPO, "data", "processed")


@settings(max_examples=300)
@given(st.integers(0, 999), st.integers(0, 999))
def test_rc_xy_roundtrip(f, c):
    x, y = rc_a_xy(f, c)
    assert tuple(int(v) for v in xy_a_rc(x, y)) == (f, c)


@settings(max_examples=300)
@given(st.floats(-10000, 9999.999), st.floats(-9999.999, 10000))
def test_xy_dentro_de_su_celda(x, y):
    f, c = xy_a_rc(x, y)
    xc, yc = rc_a_xy(f, c)
    assert abs(x - xc) <= 10 + 1e-9 and abs(y - yc) <= 10 + 1e-9
    assert 0 <= f < 1000 and 0 <= c < 1000


def test_malla_json_consistente_con_rasters(capas):
    m = json.load(open(os.path.join(P, "malla.json")))
    ref = None
    for p in sorted(glob.glob(os.path.join(P, "*.tif"))):
        with rasterio.open(p) as s:
            assert s.shape == tuple(m["shape"]), p
            assert s.crs.to_proj4().replace(" +type=crs", "") == m["crs_proj4"], p
            t = s.transform
            assert (t.a, t.e) == (m["res_m"], -m["res_m"]) and t.b == t.d == 0
            assert (t.c, t.f) == (m["extent_m"][0], m["extent_m"][1]), p
            ref = ref or (s.shape, t, s.crs)
            assert (s.shape, t, s.crs) == ref
            # el centro de la celda (f,c) del transform coincide con rc_a_xy
            for f, c in [(0, 0), (999, 999), (123, 456)]:
                assert np.allclose(s.xy(f, c), rc_a_xy(f, c))
    assert np.all((capas["ruta_rc"] >= 0) & (capas["ruta_rc"] < 1000))
