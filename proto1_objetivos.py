# Prototipo 1 - candidatos cientificos y eleccion de objetivos con presupuesto
import numpy as np
from scipy import ndimage as ndi

from proto1_mapa_costos import VALOR_MINERAL, FACTOR_CONF, tabla



def paradas_desde_ruta_real(L, separacion_min=300.0):
    """Lugares donde Perseverance se detuvo (posición repetida), separados al menos separacion_min metros."""
    xy, rc = L["ruta_xy_m"], L["ruta_rc"]
    detenciones = []
    i = 0
    while i < len(xy):
        j = i
        while j + 1 < len(xy) and np.allclose(xy[j + 1], xy[i]):
            j += 1
        if j > i:
            detenciones.append(i)
        i = j + 1

    elegidas = [0]
    for k in detenciones:
        if np.hypot(*(xy[k] - xy[elegidas[-1]])) >= separacion_min:
            elegidas.append(k)
    if elegidas[-1] != len(xy) - 1:
        elegidas.append(len(xy) - 1)
    return [tuple(int(v) for v in rc[k]) for k in elegidas]

def candidatos_ciencia(L, costo, valor_min=0.6, area_min=25, max_candidatos=12):
    """Zonas de interés científico: manchas de minerales valiosos, transitables y con área mínima."""
    mn = L["mineralogia"]
    valor = tabla(VALOR_MINERAL)[mn] * tabla(FACTOR_CONF)[L["mineralogia_confianza"]]
    interes = (valor >= valor_min) & np.isfinite(costo)

    etiquetas, n = ndi.label(interes, structure=np.ones((3, 3)))
    ids = np.arange(1, n + 1)
    areas = ndi.sum(interes, etiquetas, ids)
    puntajes = ndi.sum(valor, etiquetas, ids)

    candidatos = []
    for k in ids[areas >= area_min]:
        celdas = np.argwhere(etiquetas == k)
        centro = celdas.mean(axis=0)
        celda = celdas[np.argmin(((celdas - centro) ** 2).sum(axis=1))]
        candidatos.append({"celda": (int(celda[0]), int(celda[1])),
                           "puntaje": float(puntajes[k - 1]),
                           "mineral": int(np.bincount(mn[etiquetas == k]).argmax()),
                           "area_ha": float(areas[k - 1]) * 0.04})
    candidatos.sort(key=lambda c: -c["puntaje"])
    print(f"manchas de interés: {n} | con área suficiente: {int((areas >= area_min).sum())}")
    return candidatos[:max_candidatos]

def costo_recorrido(M, orden):
    """Costo de visitar los nodos en ese orden, usando la matriz M."""
    return sum(M[a, b] for a, b in zip(orden[:-1], orden[1:]))


def elegir_objetivos(M, puntajes, factor_presupuesto=1.5):
    """Elige qué candidatos visitar y en qué orden, sin pasar del presupuesto.
    Nodos: 0 = inicio, 1 = meta, 2 en adelante = candidatos (puntajes[k - 2])."""
    presupuesto = factor_presupuesto * M[0, 1]
    orden = [0, 1]
    pendientes = set(range(2, len(M)))
    while True:
        actual = costo_recorrido(M, orden)
        mejor = None
        for k in pendientes:
            for pos in range(1, len(orden)):
                nuevo = orden[:pos] + [k] + orden[pos:]
                total = costo_recorrido(M, nuevo)
                if total > presupuesto:
                    continue
                razon = puntajes[k - 2] / max(total - actual, 1.0)
                if mejor is None or razon > mejor[0]:
                    mejor = (razon, nuevo, k)
        if mejor is None:
            break
        _, orden, k = mejor
        pendientes.discard(k)
    return orden, costo_recorrido(M, orden), presupuesto