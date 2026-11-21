"""validar_seitah.py - ¿El planificador reproduce el rodeo que hizo Perseverance en Séítah?

Compara la ruta del planificador (modo rover, un tramo, perfil normal) con el recorrido real de Perseverance
(data/processed/m20_tramos_ABC.geojson) en tres tramos de Jezero:
  A  sol 13 -> 248   aterrizaje -> sur de Séítah        (calibración)
  B  sol 362 -> 477  rodeo de Séítah por el norte        (PRUEBA: no se usó para elegir w_arena)
  C  sol 502 -> 565  frente del delta                    (calibración)
Configuraciones: v3 original (sin arena ni pendiente HiRISE); v4 arena (textura HiRISE, w_arena=10, pendiente CTX);
v4 arena + HiRISE (además p95 de la pendiente HiRISE a 5 m). Calibración (14 nov 2026, 12 combinaciones de
w_arena 5/10/20, pendiente CTX o p95 HiRISE, umbrales 20° o 15/30°): la mejor en A+C es "v4 arena" con w=10;
en el tramo B TODAS las combinaciones quedan entre 118 y 125 m de distancia media simétrica (v3: 498 m).
Métricas: longitud, distancia media modelo->real, real->modelo, simétrica, Hausdorff.
Uso:  python validar_seitah.py            (guarda salida/validacion_seitah.json y .png)
"""
import json
import os
import sys

import numpy as np
from shapely.geometry import LineString

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from proto1_capas import cargar, rc_a_xy, xy_a_rc  # noqa: E402

import mision_v3 as v3  # noqa: E402


def metricas(modelo, real):
    mp = [modelo.interpolate(t) for t in np.arange(0, modelo.length, 10.0)]
    rp = [real.interpolate(t) for t in np.arange(0, real.length, 10.0)]
    m2r = float(np.mean([real.distance(p) for p in mp]))
    r2m = float(np.mean([modelo.distance(p) for p in rp]))
    return {"km": round(modelo.length / 1000, 2), "modelo_a_real_m": round(m2r), "real_a_modelo_m": round(r2m),
            "simetrica_m": round((m2r + r2m) / 2), "hausdorff_m": round(modelo.hausdorff_distance(real))}


def main():
    L = cargar()
    tramos = json.load(open(os.path.join(AQUI, "data", "processed", "m20_tramos_ABC.geojson")))["features"]
    sin_v4 = {k: v for k, v in L.items() if k not in ("arena_textura", "pendiente_hirise_p95")}
    sin_p95 = {k: v for k, v in L.items() if k != "pendiente_hirise_p95"}
    p_rover = v3.parametros(v3.ROVER)       # mismos umbrales que usa el exportador (P_ROVER)
    mapas = {"v3 original": v3.Mapa.desde_capas(sin_v4),                  # v3 tal cual: umbrales P (20°)
             "v4 arena": v3.Mapa.desde_capas(sin_p95, p=p_rover),          # elegida solo con A y C (ver docstring)
             "v4 arena + HiRISE": v3.Mapa.desde_capas(L, p=p_rover)}
    res, rutas = {}, {}
    for f in tramos:
        t = f["properties"]["tramo"]
        real = LineString(f["geometry"]["coordinates"])
        a = tuple(int(x) for x in xy_a_rc(*real.coords[0]))
        b = tuple(int(x) for x in xy_a_rc(*real.coords[-1]))
        for nombre, mapa in mapas.items():
            r = v3.replanear_tramo(mapa, a, b, v3.ROVER)
            if r is None:
                res[f"{t} · {nombre}"] = "sin ruta"
                continue
            cam = np.asarray(r["camino"])
            linea = LineString(np.c_[rc_a_xy(cam[:, 0], cam[:, 1])])
            res[f"{t} · {nombre}"] = metricas(linea, real)
            rutas[(t, nombre)] = linea
        rutas[(t, "real")] = real
        res[f"{t} · odómetro real km"] = round(f["properties"]["odometro_m"] / 1000, 2)
    os.makedirs(os.path.join(AQUI, "salida"), exist_ok=True)
    with open(os.path.join(AQUI, "salida", "validacion_seitah.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    for k, v in res.items():
        print(f"{k:<28} {v}")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        real = rutas[("B", "real")]
        xs, ys = real.xy
        pad = 800
        fig, ax = plt.subplots(figsize=(9, 8))
        ext = (-10000, 10000, -10000, 10000)
        ax.imshow(L["imagen"], cmap="gray", extent=ext)
        if "arena_textura" in L:
            ar = np.ma.masked_where(L["arena_textura"] == 0, L["arena_textura"])
            ax.imshow(ar, cmap=matplotlib.colors.ListedColormap(["#ff9900"]), alpha=0.35, extent=ext, interpolation="nearest")
        ax.plot(xs, ys, color="white", lw=3, label=f"Perseverance real ({res['B · odómetro real km']} km)")
        for nombre, col in (("v3 original", "#e41a1c"), ("v4 arena", "#00e5ff")):
            if ("B", nombre) in rutas:
                ax.plot(*rutas[("B", nombre)].xy, color=col, lw=2.2,
                        label=f"planner {nombre}: {res['B · ' + nombre]['km']} km, mean dist {res['B · ' + nombre]['simetrica_m']} m")
        ax.set_xlim(min(xs) - pad, max(xs) + pad)
        ax.set_ylim(min(ys) - pad, max(ys) + pad)
        ax.set_xticks([]); ax.set_yticks([])
        ax.legend(loc="lower left", fontsize=8)
        ax.set_title("Séítah (held-out leg B): planner vs Perseverance's actual route\norange = sand from HiRISE texture; rover mode")
        fig.tight_layout()
        fig.savefig(os.path.join(AQUI, "salida", "validacion_seitah_B.png"), dpi=140)
    except Exception as e:      # la figura es opcional
        print("figura no generada:", e)


if __name__ == "__main__":
    main()
