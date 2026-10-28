"""exportar_terrenos.py - Convierte el DEM y la ortoimagen CTX a formatos para el navegador.

Salida en public/data/: dem.bin (alturas float32, N x N), textura.jpg y meta.json."""
import json
import os
import numpy as np
import rasterio
from PIL import Image

AQUI = os.path.dirname(os.path.abspath(__file__))
ENTRADA = os.path.join(AQUI, "..", "data", "processed")
SALIDA = os.path.join(AQUI, "public", "data")
N = 400   # vértices por lado: 400 x 400 = 160k, suficiente detalle y carga rápida

def leer(name):
    """Lee la banda 1 de un GeoTIFF como float32, con NaN en los valores nulos."""
    with rasterio.open(os.path.join(ENTRADA, name)) as src:
        arr = src.read(1).astype(np.float32)
        if src.nodata is not None:
            arr[arr == src.nodata] = np.nan
    return arr

def exportar_dem():
    dem = leer("dem_ctx_20m.tif")
    dem = np.where(np.isnan(dem), np.nanmin(dem), dem)   # huecos sin dato -> altura mínima
    chico = Image.fromarray(dem).resize((N, N), Image.BILINEAR)
    chico = np.asarray(chico, dtype="<f4")
    chico.tofile(os.path.join(SALIDA, "dem.bin"))       # binario little-endian: lo lee Float32Array
    return float(chico.min()), float(chico.max())

def exportar_textura():
    img = leer("ortho_ctx_20m.tif")
    lo, hi = np.percentile(img[img > 0], [1, 99])       # estirar el contraste (0 = sin dato)
    g = np.clip((img - lo) / (hi - lo), 0, 1)
    # Gris -> tono marciano: cada canal con su propio rango de color
    rgb = np.stack([0.35 + 0.60 * g,
                    0.20 + 0.50 * g,
                    0.12 + 0.33 * g], axis=-1)
    foto = Image.fromarray((rgb * 255).astype(np.uint8)).resize((1024, 1024))
    foto.save(os.path.join(SALIDA, "textura.jpg"), quality=85)

def main():
    os.makedirs(SALIDA, exist_ok=True)
    zmin, zmax = exportar_dem()
    exportar_textura()
    meta = {
        "n": N,
        "extension_m": 20000,
        "elev_min_m": zmin,
        "elev_max_m": zmax,
        "orden": "fila 0 = Norte, columna 0 = Oeste",
        "fuente" : "DTM CTX 20 m de Mars 2020 (USGS)",
    }
    with open(os.path.join(SALIDA, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"Listo: {N}x{N} vértices, elevación {zmin:.0f} a {zmax:.0f} m -> {SALIDA}")

if __name__ == "__main__":
    main()