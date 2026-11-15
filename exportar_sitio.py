"""exportar_sitio.py - Archivos que el visor necesita de un sitio distinto de Jezero (ver sitios.py).

Escribe en public/data/<sitio>/:  dem.bin + meta.json (relieve), textura.jpg (relieve sombreado en tono marciano y,
donde la hay, la foto HiRISE), capa_crism.png, capa_costo.png y capas.json (capas y leyendas).
La misión precalculada (rutas_v3.json) se genera aparte:  python exportar_mision_v3.py --sitio <sitio>

Uso (desde visor_3d):  python exportar_sitio.py gale [--sin-foto]
"""
import json
import os
import sys

import numpy as np
from PIL import Image

import mision_v3 as v3
import sitios

N = 400                 # vértices por lado del relieve (igual que exportar_terrenos.py)
COLORES = {2: "#00ff00", 3: "#00ffff", 11: "#ff00ff"}          # carbonato y esmectita como en Jezero; sulfato magenta
ESCALA = ["#006837", "#87cb67", "#fffebe", "#f88c51", "#a50026"]
BLOQUEADO = "#46005a"
FOTO = {"gale": "/vsicurl/https://asc-pds-services.s3.us-west-2.amazonaws.com/mosaic/Mars/MSL/"
                "MSL_Gale_HiRISE-LRGB_78quads_sharp_cog.tif"}
R_MARTE = 3396190.0


def rgb(h):
    return np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)], np.float32)


def sombreado(dem, res=20.0, azimut=315.0, altura=40.0, exag=3.0):
    gy, gx = np.gradient(dem * exag, res)
    pend, asp = np.arctan(np.hypot(gx, gy)), np.arctan2(gy, -gx)
    az, al = np.radians(360 - azimut + 90), np.radians(altura)
    return np.clip(np.sin(al) * np.cos(pend) + np.cos(al) * np.sin(pend) * np.cos(az - asp), 0, 1)


def foto_hirise(sitio, meta, lado=1000):
    """Brillo 0..1 de la foto en la malla (NaN donde no hay foto). Se lee una miniatura del mosaico remoto."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.windows import from_bounds
    os.environ.update(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif", GDAL_HTTP_MAX_RETRY="5")
    lat0, lon0 = meta["centro_lat_lon"]
    xc, yc, half = R_MARTE * np.radians(lon0), R_MARTE * np.radians(lat0), lado * meta["res_m"] / 2
    out = np.full((lado, lado), np.nan, np.float32)
    with rasterio.open(FOTO[sitio]) as s:
        x0, x1 = max(xc - half, s.bounds.left), min(xc + half, s.bounds.right)
        y0, y1 = max(yc - half, s.bounds.bottom), min(yc + half, s.bounds.top)
        if x1 <= x0 or y1 <= y0:
            return out
        c0, c1 = int((x0 - (xc - half)) // meta["res_m"]), int((x1 - (xc - half)) // meta["res_m"])
        f0, f1 = int(((yc + half) - y1) // meta["res_m"]), int(((yc + half) - y0) // meta["res_m"])
        img = s.read(window=from_bounds(x0, y0, x1, y1, s.transform), out_shape=(s.count, f1 - f0, c1 - c0),
                     resampling=Resampling.average).astype(np.float32)
    lum = img[:3].mean(0)
    lum[img[:3].max(0) == 0] = np.nan
    lo, hi = np.nanpercentile(lum, [1, 99])
    out[f0:f1, c0:c1] = np.clip((lum - lo) / (hi - lo), 0, 1)
    return out


def main():
    sitio = sys.argv[1] if len(sys.argv) > 1 else "gale"
    if sitio == "jezero":
        sys.exit("Jezero usa exportar_terrenos.py y el notebook (sección 13.4).")
    L = sitios.cargar(sitio)
    sal = sitios.carpeta_web(sitio)
    os.makedirs(sal, exist_ok=True)
    dem = np.where(np.isfinite(L["dem"]), L["dem"], np.nanmin(L["dem"])).astype(np.float32)

    # ---- Relieve ----
    chico = np.asarray(Image.fromarray(dem).resize((N, N), Image.BILINEAR), dtype="<f4")
    chico.tofile(os.path.join(sal, "dem.bin"))
    meta = {"n": N, "extension_m": int(dem.shape[0] * L["res_m"]), "elev_min_m": float(chico.min()),
            "elev_max_m": float(chico.max()), "orden": "fila 0 = Norte, columna 0 = Oeste",
            "fuente": L["meta"].get("fuente_dem", ""), "sitio": sitios.SITIOS[sitio]["titulo"]}
    json.dump(meta, open(os.path.join(sal, "meta.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)

    # ---- Textura: relieve sombreado + foto donde exista ----
    g = 0.25 + 0.75 * sombreado(dem, L["res_m"])
    con_foto = 0.0
    if "--sin-foto" not in sys.argv and sitio in FOTO:
        try:
            f = foto_hirise(sitio, L["meta"], dem.shape[0])
            hay = np.isfinite(f)
            f = np.nan_to_num(f - np.nanmean(f)) + g[hay].mean()      # mismo brillo medio que el resto: sin escalón en el borde
            g = np.where(hay, np.clip(0.65 * f + 0.35 * g, 0, 1), g)
            con_foto = float(hay.mean())
        except Exception as e:                      # sin internet: queda solo el relieve sombreado
            print("sin foto:", e)
    color = np.stack([0.35 + 0.60 * g, 0.20 + 0.50 * g, 0.12 + 0.33 * g], axis=-1)
    Image.fromarray((color * 255).astype(np.uint8)).resize((1024, 1024), Image.LANCZOS).save(
        os.path.join(sal, "textura.jpg"), quality=88)

    # ---- Capa de minerales ----
    mapa = v3.Mapa.desde_capas(L, p=v3.parametros(v3.ROVER))
    cod = L["mineralogia"]
    capa = np.zeros(cod.shape + (4,), np.uint8)
    leyenda = []
    for c, h in COLORES.items():
        if (cod == c).any():
            capa[cod == c] = (*rgb(h).astype(np.uint8), 255)
            leyenda.append({"nombre": v3.NOMBRES.get(c, str(c)), "color": h, "valor": v3.VALOR_MINERAL.get(c, 0)})
    capa[(cod == 0)] = (0, 0, 0, 70)                # con dato, sin mineral: velo oscuro (se ve hasta dónde hay CRISM)
    Image.fromarray(capa).save(os.path.join(sal, "capa_crism.png"))

    # ---- Capa de costos (mapa del rover, el mismo que usa el planificador) ----
    costo = mapa.costo
    libre = np.isfinite(costo)
    lo, hi = 1.0, float(np.percentile(costo[libre], 99))
    t = np.clip((np.where(libre, costo, lo) - lo) / max(hi - lo, 1e-6), 0, 1) * (len(ESCALA) - 1)
    i = np.minimum(t.astype(int), len(ESCALA) - 2)
    pal = np.array([rgb(h) for h in ESCALA])
    col = pal[i] + (pal[i + 1] - pal[i]) * (t - i)[..., None]
    col[~libre] = rgb(BLOQUEADO)
    Image.fromarray(np.dstack([col, np.full(costo.shape, 255)]).astype(np.uint8)).save(os.path.join(sal, "capa_costo.png"))

    capas = {"crism": {"archivo": "capa_crism.png", "titulo": "Minerales (CRISM, aproximado)", "leyenda": leyenda},
             "costo": {"archivo": "capa_costo.png", "titulo": "Mapa de costos (rover)",
                       "escala": {"min": lo, "max": round(hi, 2), "colores": ESCALA}, "bloqueado": BLOQUEADO,
                       "bloqueado_texto": f"bloqueado (≥ {mapa.params['pend_max']:g}°)"}}
    json.dump(capas, open(os.path.join(sal, "capas.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"{sitio}: relieve {N}x{N} ({meta['elev_min_m']:.0f} a {meta['elev_max_m']:.0f} m) · foto en {100 * con_foto:.0f} % "
          f"· minerales {[m['nombre'] for m in leyenda]} · bloqueado {100 * (~libre).mean():.1f} % -> {sal}")


if __name__ == "__main__":
    main()
