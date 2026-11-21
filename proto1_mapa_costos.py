# Prototipo 1 - mapa de costos de transitabilidad
import os
import sys

import numpy as np
from scipy.ndimage import uniform_filter


# Carga de capas

from proto1_capas import cargar, xy_a_rc

FIGURAS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figuras")
os.makedirs(FIGURAS, exist_ok=True)


# Parametros 

PARAMS = dict(
    pend_ref=15.0,         # grados: a esta pendiente el termino de pendiente vale 1
    pend_max=20.0,         # grados: desde aqui la celda es obstaculo
    w_pend=1.0,            # pesos de cada penalizacion
    w_rug=0.3,
    w_duna=0.5,
    rug_ventana=5,         # celdas (5 = 100 x 100 m)
    duna_unidad=7,         # codigo de "Eolian bedform unit"
    bonus_min_max=0.20,    # bonus maximo por mineral
    bonus_geo_max=0.10,    # bonus maximo por unidad geologica de interes
    bonus_pend_max=10.0,   # sin bonus donde la pendiente supera esto
    piso_costo=0.5,        # ninguna celda cuesta menos que esto (importante para A*)
)

# SUPUESTOS TUYOS: que tan interesante es cada mineral (0 a 1)
VALOR_MINERAL = {
    2: 1.0,   # Mg-Carbonate
    6: 1.0,   # Carb. + 2.2um
    3: 1.0,   # Fe/Mg-Smectite
    9: 1.0,   # Kaolinite
    10: 1.0,  # Mg-Smectite 2
    4: 0.8,   # Olivine+Smectite
    5: 0.8,   # Olv. Smect + 2.2um
    1: 0.6,   # Olivine
    7: 0.4,   # High-Ca Pyroxene
    8: 0.4,   # Low-Ca Pyroxene
}
FACTOR_CONF = {1: 0.6, 2: 1.0}      # confianza media / muy alta
VALOR_UNIDAD = {0: 1.0, 1: 1.0}     # 0 = Jezero fan 2, 1 = Jezero fan 1


# Componentes del costo

def tabla(diccionario, n=256):
    lut = np.zeros(n, dtype=np.float32)
    for codigo, valor in diccionario.items():
        lut[codigo] = valor
    return lut


def rugosidad(pend, ventana):
    m1 = uniform_filter(pend, ventana)
    m2 = uniform_filter(pend ** 2, ventana)
    rug = np.sqrt(np.maximum(m2 - m1 ** 2, 0))
    lo, hi = np.percentile(rug, [5, 99])
    return np.clip((rug - lo) / (hi - lo), 0, 1)


def bonus(L, p):
    pend = L["pendiente"]
    b = np.zeros(pend.shape, dtype=np.float32)

    if "mineralogia" in L and "mineralogia_confianza" in L:
        val = tabla(VALOR_MINERAL)[L["mineralogia"]]          
        conf = tabla(FACTOR_CONF)[L["mineralogia_confianza"]]  
        b += p["bonus_min_max"] * val * conf

    if "unidades_geologicas" in L:
        b += p["bonus_geo_max"] * tabla(VALOR_UNIDAD)[L["unidades_geologicas"]]

    b[pend > p["bonus_pend_max"]] = 0.0  
    return b


def construir_costo(L, p=PARAMS):
    pend = L["pendiente"]

    obstaculo = np.isnan(pend) | (pend >= p["pend_max"])
    c_pend = (pend / p["pend_ref"]) ** 2
    c_rug = rugosidad(np.nan_to_num(pend), p["rug_ventana"])

    if "unidades_geologicas" in L:
        c_duna = (L["unidades_geologicas"] == p["duna_unidad"]).astype(np.float32)
    else:
        c_duna = np.zeros(pend.shape, dtype=np.float32)

    b = bonus(L, p)

    costo = 1.0 + p["w_pend"] * c_pend + p["w_rug"] * c_rug + p["w_duna"] * c_duna - b
    costo = np.maximum(costo, p["piso_costo"]).astype(np.float32)
    costo[obstaculo] = np.inf

    return dict(costo=costo, obstaculo=obstaculo, c_pend=c_pend, c_rug=c_rug,
                c_duna=c_duna, bonus=b)


# Evaluar una polilinea (p. ej. la ruta real) sobre el mapa de costos
def evaluar_polilinea(costo, xy_m, paso=5.0):
    """Muestrea la polilinea cada `paso` metros. Devuelve longitud, costo integrado y bloqueos."""
    long_total, costo_total, muestras, bloqueadas = 0.0, 0.0, 0, 0
    for a, b in zip(xy_m[:-1], xy_m[1:]):
        largo = float(np.hypot(*(b - a)))
        if largo == 0:
            continue
        n = max(2, int(np.ceil(largo / paso)) + 1)
        t = np.linspace(0, 1, n)[:, None]
        pts = a + (b - a) * t
        fila, col = xy_a_rc(pts[:, 0], pts[:, 1])
        fila = np.clip(fila, 0, costo.shape[0] - 1)
        col = np.clip(col, 0, costo.shape[1] - 1)
        c = costo[fila, col]
        dl = largo / (n - 1)
        # Calcular el costo promedio entre puntos consecutivos
        libres = np.isfinite(c[:-1]) & np.isfinite(c[1:])
        costo_total += float(((c[:-1] + c[1:]) / 2)[libres].sum() * dl)
        bloqueadas += int((~np.isfinite(c)).sum())
        muestras += n
        long_total += largo
    return dict(longitud_m=long_total,
                costo_total=costo_total,
                costo_medio_por_m=costo_total / long_total,
                frac_bloqueada=bloqueadas / muestras)



# Visualizacion opcional
def graficar(res, xy_m, archivo=os.path.join(FIGURAS, "mapa_costos.png")):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    c = np.where(np.isfinite(res["costo"]), res["costo"], np.nan)
    fig, ax = plt.subplots(figsize=(8, 7))
    im = ax.imshow(c, cmap="viridis", vmin=np.nanmin(c), vmax=np.nanpercentile(c, 99),
                   extent=[-10, 10, -10, 10])
    ax.imshow(np.where(res["obstaculo"], 1.0, np.nan), cmap="gray_r", vmin=0, vmax=1,
              extent=[-10, 10, -10, 10])
    ax.plot(xy_m[:, 0] / 1000, xy_m[:, 1] / 1000, "-", c="white", lw=1)
    ax.plot(*(xy_m[0] / 1000), "o", c="lime", mec="k")
    ax.plot(*(xy_m[-1] / 1000), "s", c="magenta", mec="k")
    plt.colorbar(im, ax=ax, label="costo por celda (negro = obstaculo)")
    ax.set_xlabel("x (km)")
    ax.set_ylabel("y (km)")
    ax.set_title("Mapa de costos y ruta real")
    fig.tight_layout()
    fig.savefig(archivo, dpi=110)
    print("figura guardada en", os.path.abspath(archivo))


# main
def main():
    L = cargar()
    res = construir_costo(L)
    costo, obst = res["costo"], res["obstaculo"]
    libre = ~obst

    print("== Mapa de costos ==")
    print("forma:", costo.shape, "| obstaculos: %.2f %%" % (100 * obst.mean()))
    c = costo[libre]
    print("costo transitable: min %.2f  mediana %.2f  media %.2f  p99 %.2f  max %.2f"
          % (c.min(), np.median(c), c.mean(), np.percentile(c, 99), c.max()))
    print("aporte medio: pendiente %.3f | rugosidad %.3f | dunas %.3f | bonus -%.3f"
          % (PARAMS["w_pend"] * res["c_pend"][libre].mean(),
             PARAMS["w_rug"] * res["c_rug"][libre].mean(),
             PARAMS["w_duna"] * res["c_duna"][libre].mean(),
             res["bonus"][libre].mean()))
    print("correlacion pendiente-rugosidad: %.2f"
          % np.corrcoef(res["c_pend"][libre], res["c_rug"][libre])[0, 1])

    print("\n== Ruta real de Perseverance sobre tu mapa ==")
    xy = L["ruta_xy_m"]
    r = evaluar_polilinea(costo, xy)
    print("longitud (polilinea): %.2f km" % (r["longitud_m"] / 1000))
    print("muestras en obstaculo: %.2f %%" % (100 * r["frac_bloqueada"]))
    print("costo medio por metro: %.3f (zona transitable: %.3f)" % (r["costo_medio_por_m"], c.mean()))
    print("=> la ruta real es %.0f %% del costo medio de la zona"
          % (100 * r["costo_medio_por_m"] / c.mean()))

    graficar(res, xy)
    return res


if __name__ == "__main__":
    main()