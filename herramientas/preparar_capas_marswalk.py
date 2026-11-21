"""Genera las capas nuevas de Marswalk en la malla del planificador (20 m, eqc lat_ts=18.43, 1000 x 1000).

Salidas en data/processed/:
  - arena_textura_20m.tif      uint8 0/1. Arena (campos de ondulaciones) detectada SOLO con la textura de la ortoimagen
                               HiRISE 1 m ESP_045994: banda de paso 4-12 m + anisotropía (crestas paralelas), percentil 65,
                               suavizada a 50 m. Es el método validado en Marswalk v2 (tramo reservado B de Séítah).
                               Cobertura: la ventana de la orto (77.38-77.47 E, 18.40-18.48 N); fuera vale 0.
  - arena_textura_cobertura_20m.tif  uint8 1 donde la orto existe (fuera, la ausencia de arena NO está verificada).
  - pend_hirise_p95_20m.tif    float32, grados. Percentil 95 de la pendiente a 5 m (DTM HiRISE 1 m oficial
                               JEZ_hirise_soc_006 promediado a 5 m) dentro de cada celda de 20 m. NaN fuera de cobertura.
  - m20_tramos_ABC.geojson     recorrido real de Perseverance (M20_traverse) de los tramos A (sol 13-248),
                               B (362-477, rodeo de Séítah) y C (502-565), en x/y locales (m) de la malla.

Uso:  python herramientas/preparar_capas_marswalk.py <carpeta_datos>
  <carpeta_datos> debe tener: hirise_ortho/HiRISE_ortho_1m_ESP045994_jezero_win.tif,
  hirise_dtm_1m/full/JEZ_hirise_soc_006_DTM_MOLAtopography_DeltaGeoid_1m_Eqc_latTs0_lon0_blend40.tif,
  m20_traverse/M20_traverse.json y M20_waypoints.json (descargas públicas de USGS / JPL; ver README).
Tarda ~2-3 min y usa ~4 GB de RAM.
"""
import json
import math
import os
import sys

import numpy as np
import pyproj
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject, transform_bounds
from rasterio.windows import from_bounds
from scipy import ndimage as ndi

AQUI = os.path.dirname(os.path.abspath(__file__))
PP = os.path.join(AQUI, "..", "data", "processed")
D = sys.argv[1]
R = 3396190.0
CRS_SRC = f"+proj=eqc +lat_ts=0 +lon_0=0 +x_0=0 +y_0=0 +R={R} +units=m +no_defs"   # CRS de los productos USGS
with rasterio.open(os.path.join(PP, "slope_ctx_20m_deg.tif")) as s:
    CRS_P, TR, SH, PERFIL = s.crs, s.transform, s.shape, s.profile
N = SH[0]


def guardar(nombre, arr, dtype, nodata=None, desc=""):
    prof = dict(PERFIL, dtype=dtype, count=1, compress="deflate", nodata=nodata)
    with rasterio.open(os.path.join(PP, nombre), "w", **prof) as dst:
        dst.write(arr.astype(dtype), 1)
        dst.update_tags(DESCRIPCION=desc)
    print("guardado", nombre, flush=True)


# ------------------------------------------------------------------ 1) arena por textura HiRISE (método v2)
ORTO = os.path.join(D, "hirise_ortho", "HiRISE_ortho_1m_ESP045994_jezero_win.tif")
with rasterio.open(ORTO) as o:
    img = o.read(1).astype(np.float32)
    TRO = o.transform
valido = img > 0
img = np.where(valido, img, np.median(img[valido]))
ratio = img / ndi.gaussian_filter(img, 20)                       # quita albedo e iluminación de gran escala
bp = ndi.gaussian_filter(ratio, 1.0) - ndi.gaussian_filter(ratio, 3.0)   # banda de paso ~4-12 m
m1 = ndi.uniform_filter(bp, 19)
m2 = ndi.uniform_filter(bp * bp, 19)
tex = np.sqrt(np.maximum(m2 - m1 * m1, 0))
gy, gx = np.gradient(bp)
jxx, jyy, jxy = (ndi.gaussian_filter(a, 6) for a in (gx * gx, gy * gy, gx * gy))
tmp = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2)
l1, l2 = (jxx + jyy + tmp) / 2, (jxx + jyy - tmp) / 2
idx = ndi.uniform_filter(tex * np.sqrt(((l1 - l2) / (l1 + l2 + 1e-12)) ** 2), 31)
del ratio, bp, m1, m2, tex, gx, gy, jxx, jyy, jxy, tmp, l1, l2

mk = (idx > np.percentile(idx[valido], 65)) & valido
mk = ndi.binary_opening(mk, structure=np.ones((3, 3)), iterations=3)
lab, n = ndi.label(mk)
tam = ndi.sum(mk, lab, range(1, n + 1))
mk = np.r_[False, tam >= 20000][lab]                              # manchas >= 2 ha
huecos = ~mk
lab, n = ndi.label(huecos)
tam = ndi.sum(huecos, lab, range(1, n + 1))
mk = mk | np.r_[False, tam < 10000][lab]                          # rellena huecos < 1 ha

# suavizado a 50 m (en la malla de la orto) y luego a la malla del planificador
with rasterio.open(ORTO) as o:
    ob = o.bounds
tr50 = from_origin(ob.left, ob.top, 50 / TRO.a * TRO.a, 50)
W50, H50 = int((ob.right - ob.left) // 50), int((ob.top - ob.bottom) // 50)
m50 = np.zeros((H50, W50), np.float32)
reproject(mk.astype(np.float32), m50, src_transform=TRO, src_crs=CRS_SRC, dst_transform=from_origin(ob.left, ob.top, 50, 50),
          dst_crs=CRS_SRC, resampling=Resampling.average)
m50 = m50 > 0.5
m50 = ndi.binary_closing(m50, iterations=2)
m50 = ndi.binary_opening(m50, iterations=2)
lab, n = ndi.label(m50)
tam = ndi.sum(m50, lab, range(1, n + 1))
m50 = np.r_[False, tam >= 40][lab]                                # >= 10 ha
arena = np.zeros(SH, np.uint8)
reproject(m50.astype(np.uint8), arena, src_transform=from_origin(ob.left, ob.top, 50, 50), src_crs=CRS_SRC,
          dst_transform=TR, dst_crs=CRS_P, resampling=Resampling.nearest)
cob = np.zeros(SH, np.float32)
reproject(valido.astype(np.float32), cob, src_transform=TRO, src_crs=CRS_SRC, dst_transform=TR, dst_crs=CRS_P,
          resampling=Resampling.average)
del img, idx, mk, valido
guardar("arena_textura_20m.tif", arena, "uint8", desc="arena por textura HiRISE ESP_045994 (p65, suavizada 50 m); 1 = arena")
guardar("arena_textura_cobertura_20m.tif", (cob > 0.99).astype(np.uint8), "uint8", desc="1 = hay ortoimagen HiRISE")
print(f"arena: {100 * arena.mean():.1f} % de la malla; cobertura de la orto {100 * (cob > 0.99).mean():.1f} %", flush=True)

# ------------------------------------------------------------------ 2) p95 de la pendiente HiRISE a 5 m por celda de 20 m
HIR = os.path.join(D, "hirise_dtm_1m", "full", "JEZ_hirise_soc_006_DTM_MOLAtopography_DeltaGeoid_1m_Eqc_latTs0_lon0_blend40.tif")
p95 = np.full(SH, np.nan, np.float32)
BANDA = 50
with rasterio.open(HIR) as src:
    for b0 in range(0, N, BANDA):
        x0, y1 = TR.c, TR.f - b0 * 20
        tr1 = from_origin(x0 - 5, y1 + 5, 1.0, 1.0)
        lim = transform_bounds(CRS_P, src.crs, x0 - 5, y1 - BANDA * 20 - 5, x0 + N * 20 + 5, y1 + 5)
        win = from_bounds(*lim, src.transform).round_offsets().round_lengths()
        a = src.read(1, window=win, boundless=True, fill_value=src.nodata).astype(np.float32)
        a[(a < -1e30) | ~np.isfinite(a)] = np.nan
        if np.isnan(a).all():
            continue
        z = np.full((BANDA * 20 + 10, N * 20 + 10), np.nan, np.float32)
        reproject(a, z, src_transform=src.window_transform(win), src_crs=src.crs, src_nodata=np.nan,
                  dst_transform=tr1, dst_crs=CRS_P, dst_nodata=np.nan, resampling=Resampling.bilinear)
        z5 = z[5:-5, 5:-5].reshape(BANDA * 4, 5, N * 4, 5).mean(axis=(1, 3))
        gy, gx = np.gradient(z5, 5.0)
        s5 = np.degrees(np.arctan(np.hypot(gx, gy)))
        c5 = s5.reshape(BANDA, 4, N, 4).transpose(0, 2, 1, 3).reshape(BANDA, N, 16)
        ok = np.isfinite(c5).all(-1)
        with np.errstate(all="ignore"):
            p95[b0:b0 + BANDA] = np.where(ok, np.percentile(c5, 95, axis=-1), np.nan)
        print(f"  banda {b0}: {int(ok.sum())} celdas", flush=True)
guardar("pend_hirise_p95_20m.tif", p95, "float32", nodata=np.nan,
        desc="p95 de la pendiente HiRISE a 5 m dentro de cada celda de 20 m (grados); NaN fuera de cobertura")
print(f"pendiente HiRISE: {100 * np.isfinite(p95).mean():.1f} % de la malla", flush=True)

# ------------------------------------------------------------------ 3) tramos reales de Perseverance (validación)
GEO = f"+proj=longlat +R={R} +no_defs"
T = pyproj.Transformer.from_crs(GEO, CRS_P.to_proj4() if hasattr(CRS_P, "to_proj4") else CRS_P, always_xy=True)
wp = sorted(json.load(open(os.path.join(D, "m20_traverse", "M20_waypoints.json")))["features"],
            key=lambda f: (f["properties"]["sol"], f["properties"]["site"], f["properties"]["drive"]))
trav = sorted(json.load(open(os.path.join(D, "m20_traverse", "M20_traverse.json")))["features"],
              key=lambda f: (f["properties"]["sol"], f["properties"]["SCLK_START"]))


def en_sol(sol):
    return [f["properties"] for f in wp if f["properties"]["sol"] <= sol][-1]


feats = []
for tramo, (sa, sb) in {"A": (13, 248), "B": (362, 477), "C": (502, 565)}.items():
    pa, pb = en_sol(sa), en_sol(sb)
    pts = [T.transform(pa["lon"], pa["lat"])]
    for f in trav:
        if sa < f["properties"]["sol"] <= sb:
            pts += [T.transform(lon, lat) for lon, lat, *_ in f["geometry"]["coordinates"]]
    pts.append(T.transform(pb["lon"], pb["lat"]))
    odo = pb["dist_total_m"] - pa["dist_total_m"]
    if odo < 0:
        odo = sum(f["properties"]["length"] for f in trav if sa < f["properties"]["sol"] <= sb)
    feats.append({"type": "Feature", "properties": {"tramo": tramo, "sol_inicio": sa, "sol_fin": sb, "odometro_m": round(odo, 1)},
                  "geometry": {"type": "LineString", "coordinates": [[round(x, 2), round(y, 2)] for x, y in pts]}})
with open(os.path.join(PP, "m20_tramos_ABC.geojson"), "w") as f:
    json.dump({"type": "FeatureCollection", "crs_local": str(CRS_P), "fuente": "NASA/JPL M20_traverse.json + M20_waypoints.json",
               "features": feats}, f)
print("guardado m20_tramos_ABC.geojson")
