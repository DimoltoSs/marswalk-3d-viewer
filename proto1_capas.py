# Prototipo 1 - carga de capas alineadas de Jezero
"""Carga las capas alineadas de Jezero como arreglos numpy (todas 1000x1000, 20 m/celda).

Uso:
    from proto1_capas import cargar
    L = cargar()
    L["dem"], L["pendiente"], L["ruta_real"] ...
Convencion: fila 0 = norte, columna 0 = oeste. Coordenadas locales en metros
respecto a 18.43N, 77.43E: x = -10000 + 20*(col+0.5),  y = 10000 - 20*(fila+0.5).
"""
import os, json
import numpy as np
import rasterio

RAIZ = os.path.dirname(os.path.abspath(__file__))   # carpeta autonoma: datos en ./data/processed
P = os.path.join(RAIZ, "data", "processed")

CAPAS = {   # nombre -> archivo
    "dem": "dem_ctx_20m.tif",                    # m (geoide), CTX 20 m
    "pendiente": "slope_ctx_20m_deg.tif",        # grados
    "dem_global": "dem_mola_hrsc_200m_a20m.tif", # m, MOLA/HRSC (suave)
    "pendiente_global": "slope_mola_hrsc_deg.tif",
    "imagen": "ortho_ctx_20m.tif",               # uint8, 0 = sin dato
    "ruta_real": "ruta_real_mask.tif",           # 1 = celda recorrida por Perseverance
}
# Se agregan automaticamente si existen (capas opcionales)
OPCIONALES = {"inercia_termica": "themis_ti_20m.tif",          # aun no disponible
              "unidades_geologicas": "geounits_20m.tif",       # uint8, codigo de unidad; 255 = sin dato (ver geounits_leyenda.csv)
              "dem_hirise_norte": "dem_hirise_N_20m.tif",      # m; NaN fuera de cobertura (solo ~9% de la zona)
              "pendiente_hirise_norte": "slope_hirise_N_20m_deg.tif",
              "mineralogia": "mineralogia_crism_20m.tif",      # uint8, clase CRISM 0-10 (0 = sin identificar), 255 = sin dato (ver mineralogia_leyenda.csv); cobertura ~66 % de la zona
              "mineralogia_confianza": "mineralogia_confianza_20m.tif",  # uint8: 0 = sin dato/sin identificar, 1 = media, 2 = alta
              # Marswalk v4 (herramientas/preparar_capas_marswalk.py)
              "arena_textura": "arena_textura_20m.tif",                # uint8 1 = arena (textura HiRISE ESP_045994)
              "arena_cobertura": "arena_textura_cobertura_20m.tif",    # uint8 1 = hay orto HiRISE (fuera: arena no evaluada)
              "pendiente_hirise_p95": "pend_hirise_p95_20m.tif"}       # grados, p95 de la pendiente HiRISE a 5 m; NaN fuera

def cargar():
    out = {}
    for k, f in {**CAPAS, **OPCIONALES}.items():
        p = os.path.join(P, f)
        if os.path.exists(p):
            with rasterio.open(p) as s:
                a = s.read(1)
                if a.dtype.kind == "f" and s.nodata is not None:
                    a = np.where(np.isclose(a, s.nodata, equal_nan=True), np.nan, a)
                out[k] = a
        elif k in CAPAS:
            raise FileNotFoundError(p)
    m = json.load(open(os.path.join(P, "malla.json")))
    out["meta"] = m
    out["res_m"] = m["res_m"]
    r = np.load(os.path.join(P, "ruta_real_xy.npz"))
    out["ruta_xy_m"] = np.c_[r["x"], r["y"]]              # x,y metros, ordenados por sol
    out["ruta_sol"] = r["sol"]
    out["ruta_rc"] = np.c_[xy_a_rc(r["x"], r["y"])]        # (fila, col)
    return out

def xy_a_rc(x, y, res=20.0, half=10000.0):
    col = np.floor((np.asarray(x) + half) / res).astype(int)
    fila = np.floor((half - np.asarray(y)) / res).astype(int)
    return fila, col

def rc_a_xy(fila, col, res=20.0, half=10000.0):
    return -half + res * (np.asarray(col) + .5), half - res * (np.asarray(fila) + .5)

CRS_LOCAL = "+proj=eqc +lat_ts=18.43 +lat_0=18.43 +lon_0=77.43 +x_0=0 +y_0=0 +R=3396190 +units=m +no_defs"

def xy_a_lonlat(x, y):
    """x, y locales (m) -> lon, lat planetocéntricas (grados, esfera de Marte R = 3396190 m), para MapLibre."""
    import pyproj
    t = pyproj.Transformer.from_crs(CRS_LOCAL, "+proj=longlat +R=3396190 +no_defs", always_xy=True)
    return t.transform(np.asarray(x, float), np.asarray(y, float))

if __name__ == "__main__":
    L = cargar()
    for k, v in L.items():
        if isinstance(v, np.ndarray):
            print(f"{k:22s} {v.shape} {v.dtype}")
    print("inicio ruta (fila,col):", L["ruta_rc"][0], " fin:", L["ruta_rc"][-1])
