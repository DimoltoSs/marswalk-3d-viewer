"""sitios.py - Lugares de Marte que conoce el visor. Todos usan la misma malla (1000 x 1000 celdas de 20 m,
x este / y norte en metros desde el centro) y el mismo modelo (mision_v3.py); solo cambian las capas de datos.

  jezero : capas de data/processed (proto1_capas.cargar), como siempre.
  gale   : capas de data/gale/processed (relieve del DEM de MSL; arena y minerales APROXIMADOS, ver
           mapas_marte/herramientas). Ruta real = Curiosity.
Para agregar otro lugar: una carpeta data/<nombre>/processed con dem_20m.tif, slope_20m_deg.tif y malla.json
(opcionales: minerales, arena, ruta real), una entrada en SITIOS y `python exportar_sitio.py <nombre>`.
"""
import json
import os
import sys

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import mision_v3 as v3  # noqa: E402

SITIOS = {
    "jezero": {"titulo": "Jezero", "rover": "Perseverance", "carpeta_web": "", "lat": 18.43, "lon": 77.43},
    "gale": {"titulo": "Gale", "rover": "Curiosity", "carpeta_web": "gale", "lat": -4.66, "lon": 137.41},
}
OPCIONALES = {"mineralogia": "mineralogia_crism_20m.tif", "mineralogia_confianza": "mineralogia_confianza_20m.tif",
              "arena_textura": "arena_textura_20m.tif", "arena_textura_cobertura": "arena_textura_cobertura_20m.tif"}

# Minerales que solo existen en Gale (los códigos 2 y 3 son los mismos que en Jezero)
v3.VALOR_MINERAL.setdefault(11, 1.0)
v3.NOMBRES.setdefault(11, "Sulfato")


def carpeta_datos(sitio):
    return os.path.join(AQUI, "data", "processed") if sitio == "jezero" \
        else os.path.join(AQUI, "data", sitio, "processed")


def carpeta_web(sitio):
    """Donde el visor lee los archivos del sitio: public/data (Jezero) o public/data/<sitio>."""
    return os.path.join(AQUI, "public", "data", SITIOS[sitio]["carpeta_web"])


def cargar(sitio="jezero"):
    """Capas del sitio con las mismas claves que proto1_capas.cargar()."""
    if sitio not in SITIOS:
        raise KeyError(f"Sitio desconocido: {sitio}. Opciones: {', '.join(SITIOS)}")
    if sitio == "jezero":
        from proto1_capas import cargar as cargar_jezero
        return cargar_jezero()
    import rasterio
    P = carpeta_datos(sitio)
    lee = lambda f: rasterio.open(os.path.join(P, f)).read(1)   # noqa: E731
    m = json.load(open(os.path.join(P, "malla.json"), encoding="utf-8"))
    L = {"dem": lee("dem_20m.tif"), "pendiente": lee("slope_20m_deg.tif"), "meta": m, "res_m": m["res_m"]}
    for k, f in OPCIONALES.items():
        if os.path.exists(os.path.join(P, f)):
            L[k] = lee(f)
    n = L["dem"].shape[0]
    if "mineralogia" not in L:              # sin minerales: no hay objetivos de ciencia, solo rutas A -> B
        L["mineralogia"] = np.full((n, n), 255, np.uint8)
        L["mineralogia_confianza"] = np.zeros((n, n), np.uint8)
    ruta = os.path.join(P, "ruta_real_xy.npz")
    if os.path.exists(ruta):
        r = np.load(ruta)
        half, res = n * m["res_m"] / 2, m["res_m"]
        fila = np.floor((half - r["y"]) / res).astype(int)
        col = np.floor((r["x"] + half) / res).astype(int)
        ok = (fila >= 0) & (fila < n) & (col >= 0) & (col < n)       # solo la parte de la ruta dentro del mapa
        L["ruta_xy_m"] = np.c_[r["x"], r["y"]][ok]
        L["ruta_rc"] = np.c_[fila, col][ok]
    return L
