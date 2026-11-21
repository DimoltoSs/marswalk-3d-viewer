"""eva_avanzada.py - Extras de la EVA de astronautas, encima del planificador v3 (mision_v3.py, que no cambia).
Incluye lo de eva_pareja.py del planificador (perfil_pareja, senal_en_camino, radio con `paso`): ya no hace falta
ese archivo. Uso: r = perfil_pareja(mapa, camino, paradas, habitat, PAREJA_DEFECTO); senal_en_camino(camino, cob, mapa)

1. EVA EN PAREJA (regla de la NASA: nadie sale solo).
   - Cada astronauta con su peso y su oxígeno. La misión se planea con quien más gasta al caminar, y con el
     presupuesto del tanque más justo de los dos (convertido a su gasto). Después se revisa a cada uno.
   - Contingencia "compañero lesionado": desde cada punto de la ruta, uno ayuda al otro a volver. Supuestos
     propios (no son datos de la NASA): se camina a VEL_ASISTIDA de la velocidad normal y quien ayuda carga
     CARGA_AYUDA_KG extra (parte del peso del compañero). Se prueban los dos papeles (A lesionado, B lesionado).
     Ambos deben llegar con O2 (puede usarse la reserva del 10 %) y dentro de las horas del traje.
2. RADIO: línea de vista entre la antena del hábitat (ANTENA_HABITAT_M) y la del traje (ANTENA_TRAJE_M) sobre el
   relieve, con la curvatura de Marte. Las celdas sin señal pueden costar más (W_SIN_SENAL) para que la ruta las evite.
3. ILUMINACIÓN (versión sencilla): posición del Sol en Marte para una fecha y hora solar local (algoritmo Mars24,
   Allison y McEwen 2000). La EVA no puede durar más que la luz que queda; se marcan los tramos en sombra del
   relieve (a la hora a la que se pasa por ahí) y los que caerían de noche. La ruta no cambia por la sombra.
"""
import math
from dataclasses import replace
from datetime import date, datetime, timezone

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

import mision_v3 as v3

R_MARTE = 3396190.0
HORA_MARCIANA_H = 1.0274912517      # una "hora" de reloj solar marciano (1/24 de sol) en horas terrestres

# Supuestos de la pareja
VEL_ASISTIDA = 0.5                  # regreso con compañero lesionado: mitad de la velocidad normal
CARGA_AYUDA_KG = 30.0               # quien ayuda soporta parte del peso del lesionado (kg-masa extra)

# Radio
ANTENA_HABITAT_M = 10.0             # mástil del hábitat
ANTENA_TRAJE_M = 2.0                # antena en la mochila del traje
W_SIN_SENAL = 3.0                   # costo extra por celda sin señal (como una pendiente de ~25°)

# Traje y pareja por defecto
O2_TRAJE_L = 380.0                  # tanque primario del traje EMU de la NASA: 0.54 kg de O2 ~ 380 L
HORAS_TRAJE = 8.0                   # soporte vital primario del EMU
RESERVA = 0.10                      # en la EVA normal se guarda 10 % del tanque; en un rescate se puede usar
PAREJA_DEFECTO = ({"masa_kg": 80.0, "o2_L": O2_TRAJE_L}, {"masa_kg": 70.0, "o2_L": O2_TRAJE_L})


# ---------------------------------------------------------------- pareja
def astronauta(masa_kg=80.0, kit_kg=None):
    """mision_v3.ASTRONAUTA con otra masa corporal (y, si se da, otro kit)."""
    cambios = {"masa_kg": float(masa_kg)}
    if kit_kg is not None:
        cambios["kit_kg"] = float(kit_kg)
    return replace(v3.ASTRONAUTA, **cambios)


def gasto_referencia_w(agente):
    """Gasto metabólico [W] caminando en plano a la velocidad normal: sirve para comparar a dos astronautas."""
    return float(v3.pandolf_w(agente, agente.vel_seguro_m_h / 3600, 0.0, agente.eta_terreno))


def mas_limitado(pareja):
    """Índice del astronauta que gastaría la mayor fracción de su tanque por hora de caminata."""
    return int(np.argmax([gasto_referencia_w(p["agente"]) * v3.O2_L_POR_WH / p["o2_L"] for p in pareja]))


def presupuesto_pareja(pareja):
    """(índice del que más gasta, presupuesto [Wh] en SUS unidades) para planear a los dos con un solo agente.
    Se planea con quien más gasta al caminar; el tanque de cada uno se pasa a esas unidades (tanque x su gasto
    relativo) y se toma el menor. Así nadie queda fuera del presupuesto aunque uno pese más y el otro traiga menos O2.
    (La revisión final de evaluar_eva vuelve a comprobar a cada uno con su propio gasto.)"""
    ref = [gasto_referencia_w(p["agente"]) for p in pareja]
    w = int(np.argmax(ref))
    wh = min(p["o2_L"] / v3.O2_L_POR_WH * ref[w] / r for p, r in zip(pareja, ref))
    return w, wh


# ---------------------------------------------------------------- regreso al hábitat (varios agentes)
def _aristas(mapa, base, radio_m):
    v = v3.Ventana.alrededor(mapa, [base], margen_m=radio_m, centro=base, radio_m=radio_m)
    n, m = v.costo.shape
    libre = np.isfinite(v.costo)
    dem = np.nan_to_num(v.sl(mapa.dem))
    arena = v.sl(mapa.arena) if mapa.arena is not None else np.zeros((n, m), bool)
    lento = v.sl(mapa.riesgo | mapa.duna)
    filas, cols = np.meshgrid(np.arange(n), np.arange(m), indexing="ij")
    A = {k: [] for k in ("o", "d", "dh", "dz", "lento", "arena")}
    for df, dc in v3.VECINOS:
        sl_a = (slice(max(0, -df), min(n, n - df)), slice(max(0, -dc), min(m, m - dc)))
        fa, ca = filas[sl_a], cols[sl_a]
        fb, cb = fa + df, ca + dc
        ok = libre[fa, ca] & libre[fb, cb]
        if df and dc:
            ok &= libre[fa, cb] & libre[fb, ca]
        fa, ca, fb, cb = fa[ok], ca[ok], fb[ok], cb[ok]
        A["o"].append(fa * m + ca); A["d"].append(fb * m + cb)
        A["dh"].append(np.full(len(fa), v3.RES * math.hypot(df, dc)))
        A["dz"].append(dem[fb, cb] - dem[fa, ca])
        A["lento"].append(lento[fb, cb]); A["arena"].append(arena[fb, cb])
    A = {k: np.concatenate(x) for k, x in A.items()}
    return v, (n, m), A


def regresos(mapa, base, agentes, radio_m, vel_factor=1.0):
    """Para cada agente {nombre: Agente}: energía [Wh] mínima para volver a la base desde cada celda, y el tiempo
    [h] (igual para todos: misma velocidad). vel_factor < 1 = regreso lento (asistido)."""
    v, (n, m), A = _aristas(mapa, base, radio_m)
    i0 = v.local(base)

    def dijk(w):
        g = csr_matrix((w, (A["d"], A["o"])), shape=(n * m, n * m))      # aristas invertidas: desde la base
        dist = dijkstra(g, directed=True, indices=i0)
        arr = np.full(mapa.forma, np.nan)
        v.sl(arr)[...] = np.where(np.isfinite(dist), dist, np.nan).reshape(n, m)
        return arr

    salida = {}
    for nombre, ag in agentes.items():
        vel = np.where(A["lento"], ag.vel_riesgo_m_h, ag.vel_seguro_m_h) * vel_factor
        t_h = np.hypot(A["dh"], A["dz"]) / vel
        eta = np.where(A["arena"], ag.eta_arena, ag.eta_terreno)
        salida[nombre] = dijk(v3.pandolf_w(ag, vel / 3600, 100 * A["dz"] / A["dh"], eta) * t_h)
        if "h" not in salida:
            salida["h"] = dijk(t_h)
    return salida


def tiempos_camino(mapa, camino, agente, paradas=()):
    """Horas transcurridas desde la salida en cada punto del camino (incluye las paradas de estudio)."""
    a = np.asarray(camino)
    dz = np.diff(np.nan_to_num(mapa.dem[a[:, 0], a[:, 1]]))
    dh = v3.RES * np.hypot(*np.diff(a, axis=0).T)
    lento = (mapa.riesgo | mapa.duna)[a[1:, 0], a[1:, 1]]
    vel = np.where(lento, agente.vel_riesgo_m_h, agente.vel_seguro_m_h)
    t = np.r_[0.0, np.cumsum(np.hypot(dh, dz) / vel)]
    for i in paradas:
        t[i:] += agente.horas_por_objetivo
    return t


def contingencia(mapa, camino, paradas, pareja, gastado_wh, t_h, horas_max, asist):
    """(Lo usa servidor.py; perfil_pareja hace lo mismo y además el O2 de cada uno.)
    Margen [L de O2] para volver si en ese punto uno de los dos se lesiona (el peor de los dos papeles).
    asist: salida de regresos(..., vel_factor=VEL_ASISTIDA) con claves 'ayuda0', 'herido0', 'ayuda1', 'herido1', 'h'."""
    a = np.asarray(camino)
    idx = (a[:, 0], a[:, 1])
    h_vuelta = asist["h"][idx]
    margen = np.full(len(a), np.inf)
    peor_papel = np.zeros(len(a), int)
    for herido in (0, 1):
        ayuda = 1 - herido
        mg_ayuda = pareja[ayuda]["o2_L"] - (gastado_wh[ayuda] + asist[f"ayuda{ayuda}"][idx]) * v3.O2_L_POR_WH
        mg_herido = pareja[herido]["o2_L"] - (gastado_wh[herido] + asist[f"herido{herido}"][idx]) * v3.O2_L_POR_WH
        mg = np.fmin(mg_ayuda, mg_herido)
        peor = mg < margen
        margen = np.where(peor, mg, margen)
        peor_papel = np.where(peor, herido, peor_papel)
    # además, el regreso lento debe caber en las horas del traje: si no, el margen se vuelve negativo
    sin_tiempo = (t_h + h_vuelta) > horas_max
    margen = np.where(np.isfinite(h_vuelta), margen, -1.0)
    margen = np.where(sin_tiempo, np.minimum(margen, -0.1), margen)
    fuera = np.nonzero(~(margen >= 0))[0]
    return {"margen_rescate_L": np.round(np.nan_to_num(margen, nan=-1.0), 1).tolist(),
            "herido_peor": peor_papel.tolist(),
            "horas_rescate": np.round(np.nan_to_num(h_vuelta, nan=-1.0), 2).tolist(),
            "sin_rescate": int(fuera[0]) if len(fuera) else None}


# ---------------------------------------------------------------- radio
def cobertura_radio(mapa, base, radio_m, h_base=ANTENA_HABITAT_M, h_traje=ANTENA_TRAJE_M, paso=2, lote=4000):
    """int8 del tamaño del mapa: 1 = el traje ve la antena del hábitat (línea de vista sobre el relieve, con la
    curvatura de Marte), 0 = sin señal, -1 = no evaluado (fuera de radio_m). Se evalúa una celda de cada `paso`
    (paso 2 = 40 m) y se rellena el resto con la vecina evaluada más cercana."""
    dem = np.nan_to_num(mapa.dem, nan=float(np.nanmin(mapa.dem)))
    n, m = dem.shape
    f0, c0 = base
    k = int(radio_m / v3.RES) + 1
    ff, cc = np.mgrid[max(0, f0 - k):min(n, f0 + k + 1):paso, max(0, c0 - k):min(m, c0 + k + 1):paso]
    forma = ff.shape
    ff, cc = ff.ravel(), cc.ravel()
    D = v3.RES * np.hypot(ff - f0, cc - c0)
    dentro = D <= radio_m
    z0 = dem[f0, c0] + h_base
    ns = max(int(k / paso), 4) + 2                         # ~1 muestra cada `paso` celdas en la línea más larga
    t = np.linspace(0, 1, ns)[1:-1]
    visible = np.zeros(len(ff), bool)
    sel = np.nonzero(dentro)[0]
    for i in range(0, len(sel), lote):
        j = sel[i:i + lote]
        f, c, d = ff[j, None], cc[j, None], D[j, None]
        fs = np.rint(f0 + (f - f0) * t).astype(int)
        cs = np.rint(c0 + (c - c0) * t).astype(int)
        s = d * t
        suelo = dem[fs, cs] + s * (d - s) / (2 * R_MARTE)          # la curvatura levanta el suelo intermedio
        z1 = dem[f[:, 0], c[:, 0]][:, None] + h_traje
        visible[j] = np.all(suelo <= z0 + (z1 - z0) * t, axis=1)
    rejilla = np.where(dentro, visible.astype(np.int8), np.int8(-1)).reshape(forma)
    out = np.full((n, m), -1, np.int8)
    f_lo, c_lo = max(0, f0 - k), max(0, c0 - k)
    bloque = np.repeat(np.repeat(rejilla, paso, axis=0), paso, axis=1)
    alto, ancho = min(n, f0 + k + 1) - f_lo, min(m, c0 + k + 1) - c_lo
    out[f_lo:f_lo + alto, c_lo:c_lo + ancho] = bloque[:alto, :ancho]
    out[f0, c0] = 1
    return out


def con_radio(mapa, cobertura, w=W_SIN_SENAL):
    """Copia del mapa en la que las celdas sin señal (cobertura == 0) cuestan w más. No toca lo no evaluado."""
    return replace(mapa, costo=np.where(cobertura == 0, mapa.costo + w, mapa.costo))


def tramos_sin_senal(camino, cobertura):
    """Por punto: hay señal (bool); y el tramo seguido más largo sin señal [m]."""
    a = np.asarray(camino)
    ok = cobertura[a[:, 0], a[:, 1]] == 1      # 1 = señal; 0 = sin señal; -1 = fuera del radio evaluado
    paso = np.r_[0.0, v3.RES * np.hypot(*np.diff(a, axis=0).T)]
    largo, actual = 0.0, 0.0
    for s, p in zip(ok, paso):
        actual = 0.0 if s else actual + p
        largo = max(largo, actual)
    total = paso.sum()
    sin = paso[~ok].sum()
    return {"senal": ok.tolist(), "sin_senal_pct": round(100 * sin / max(total, 1e-9), 1),
            "sin_senal_max_m": round(largo)}


# ---------------------------------------------------------------- pareja: revisión completa de una EVA trazada
def distancias_camino(mapa, camino):
    """Metros recorridos (3D) hasta cada punto del camino."""
    a = np.asarray(camino)
    dz = np.diff(np.nan_to_num(mapa.dem[a[:, 0], a[:, 1]]))
    return np.r_[0.0, np.cumsum(np.hypot(v3.RES * np.hypot(*np.diff(a, axis=0).T), dz))]


def regresos_pareja(mapa, base, pareja, radio_m):
    """Los dos juegos de regresos que necesita perfil_pareja: normal (cada uno a su paso) y asistido."""
    ag = [astronauta(p.get("masa_kg", 80.0), p.get("kit_kg")) for p in pareja]
    normal = regresos(mapa, base, {0: ag[0], 1: ag[1]}, radio_m)
    asistido = regresos(mapa, base, {
        "ayuda0": replace(ag[0], kit_kg=ag[0].kit_kg + CARGA_AYUDA_KG),
        "ayuda1": replace(ag[1], kit_kg=ag[1].kit_kg + CARGA_AYUDA_KG),
        "herido0": ag[0], "herido1": ag[1]}, radio_m, VEL_ASISTIDA)
    return normal, asistido


def perfil_pareja(mapa, camino, paradas, base, pareja=PAREJA_DEFECTO, horas_max=HORAS_TRAJE, reserva=RESERVA,
                  radio_m=None, regresos_calculados=None):
    """Revisa una EVA ya trazada (`camino` en celdas, empieza y termina en `base`; `paradas` = índices del camino
    donde se estudia) para una pareja [{"masa_kg", "o2_L", "kit_kg"?}, {...}].

    Devuelve dict con:
      personas: por astronauta, o2_usado_L, o2_final_pct (lo que queda del tanque al volver), punto_no_retorno
      tanque_pct: por punto, el % de tanque que le quedaría al MÁS justo si volviera desde ahí
      punto_no_retorno: primer punto donde a alguno ya no le alcanza para volver guardando la reserva (o None)
      rescate: margen_L por punto (el peor papel), herido (0/1: quién es el lesionado en el peor caso),
               horas_regreso, sin_rescate (primer punto sin rescate posible, o None) y metros recorridos hasta ahí
      horas: tiempo transcurrido en cada punto
    regresos_calculados: (normal, asistido) de regresos_pareja, para reutilizarlos entre consultas."""
    if len(pareja) != 2:
        raise ValueError("La pareja debe tener exactamente dos astronautas.")
    a = np.asarray(camino)
    idx = (a[:, 0], a[:, 1])
    if radio_m is None:
        radio_m = v3.RES * float(np.hypot(a[:, 0] - base[0], a[:, 1] - base[1]).max()) + 1500.0
    normal, asist = regresos_calculados or regresos_pareja(mapa, base, pareja, radio_m)
    agentes = [astronauta(p.get("masa_kg", 80.0), p.get("kit_kg")) for p in pareja]
    tanques_wh = [p["o2_L"] / v3.O2_L_POR_WH for p in pareja]

    personas, gastado, tanque_pct = [], [], None
    for k, (ag, p) in enumerate(zip(agentes, pareja)):
        pr = v3.perfil_regreso(mapa, camino, {"wh": normal[k]}, ag, tanques_wh[k], reserva, paradas)
        g = np.asarray(pr["gastado_wh"], float)
        gastado.append(g)
        margen_L = np.nan_to_num(np.asarray(pr["margen_wh"], float), nan=-np.inf) * v3.O2_L_POR_WH
        pct = 100 * (margen_L + reserva * p["o2_L"]) / p["o2_L"]      # tanque que quedaría al volver desde ahí
        tanque_pct = pct if tanque_pct is None else np.fmin(tanque_pct, pct)
        personas.append({"masa_kg": float(p.get("masa_kg", 80.0)), "o2_L": float(p["o2_L"]),
                         "o2_usado_L": round(float(g[-1] * v3.O2_L_POR_WH), 1),
                         "o2_final_pct": round(float(100 * (1 - g[-1] * v3.O2_L_POR_WH / p["o2_L"])), 1),
                         "punto_no_retorno": pr["punto_no_retorno"]})

    t_h = tiempos_camino(mapa, camino, agentes[0], paradas)
    h_vuelta = asist["h"][idx]
    margen = np.full(len(a), np.inf)
    herido_peor = np.zeros(len(a), int)
    for herido in (0, 1):
        ayuda = 1 - herido
        mg_ayuda = pareja[ayuda]["o2_L"] - (gastado[ayuda] + asist[f"ayuda{ayuda}"][idx]) * v3.O2_L_POR_WH
        mg_herido = pareja[herido]["o2_L"] - (gastado[herido] + asist[f"herido{herido}"][idx]) * v3.O2_L_POR_WH
        mg = np.fmin(mg_ayuda, mg_herido)
        peor = mg < margen
        margen = np.where(peor, mg, margen)
        herido_peor = np.where(peor, herido, herido_peor)
    margen = np.where(np.isfinite(h_vuelta) & np.isfinite(margen), margen, -1.0)   # sin camino de vuelta
    margen = np.where(t_h + np.nan_to_num(h_vuelta, nan=np.inf) > horas_max, np.minimum(margen, -0.1), margen)
    fuera = np.nonzero(margen < 0)[0]
    sin_rescate = int(fuera[0]) if len(fuera) else None
    no_ret = [p["punto_no_retorno"] for p in personas if p["punto_no_retorno"] is not None]
    d = distancias_camino(mapa, camino)
    return {
        "personas": personas,
        "tanque_pct": np.round(np.nan_to_num(tanque_pct, neginf=-100.0), 1).tolist(),
        "punto_no_retorno": min(no_ret) if no_ret else None,
        "rescate": {
            "margen_L": np.round(margen, 1).tolist(),
            "herido": herido_peor.tolist(),
            "horas_regreso": np.round(np.nan_to_num(h_vuelta, nan=-1.0), 2).tolist(),
            "sin_rescate": sin_rescate,
            "metros_hasta_sin_rescate": None if sin_rescate is None else round(float(d[sin_rescate])),
            "margen_min_L": round(float(margen.min()), 1),
            "supuestos": {"vel_asistida": VEL_ASISTIDA, "carga_ayuda_kg": CARGA_AYUDA_KG, "horas_traje": horas_max},
        },
        "horas": np.round(t_h, 3).tolist(),
        "distancia_m": round(float(d[-1])),
    }


def senal_en_camino(camino, cobertura, mapa=None):
    """Por punto: hay señal (True), no (False) o no se evaluó (None). Y el % del recorrido sin señal y el tramo
    seguido más largo sin señal [m] (lo no evaluado no cuenta como sin señal)."""
    a = np.asarray(camino)
    c = cobertura[a[:, 0], a[:, 1]]
    paso = (np.diff(distancias_camino(mapa, camino)) if mapa is not None
            else v3.RES * np.hypot(*np.diff(a, axis=0).T))
    paso = np.r_[0.0, paso]
    largo = actual = 0.0
    for s, p in zip(c, paso):
        actual = actual + p if s == 0 else 0.0
        largo = max(largo, actual)
    total = float(paso.sum())
    return {"senal": [None if s < 0 else bool(s) for s in c],
            "sin_senal_m": round(float(paso[c == 0].sum())),
            "sin_senal_pct": round(100 * float(paso[c == 0].sum()) / max(total, 1e-9), 1),
            "sin_senal_max_m": round(largo),
            "antenas_m": {"habitat": ANTENA_HABITAT_M, "traje": ANTENA_TRAJE_M}}



# ---------------------------------------------------------------- Sol (Mars24, Allison y McEwen 2000)
_PBS = ((0.0071, 2.2353, 49.409), (0.0057, 2.7543, 168.173), (0.0039, 1.1177, 191.837),
        (0.0037, 15.7866, 21.736), (0.0021, 2.1354, 15.704), (0.0020, 2.4694, 95.528),
        (0.0018, 32.8493, 49.095))


def declinacion_sol(dia: date):
    """(Ls [°], declinación del Sol [°]) en Marte para un día terrestre (a mediodía UTC)."""
    dt = datetime(dia.year, dia.month, dia.day, 12, tzinfo=timezone.utc)
    jd_tt = dt.timestamp() / 86400 + 2440587.5 + 69.184 / 86400
    d = jd_tt - 2451545.0
    M = math.radians(19.3871 + 0.52402073 * d)
    alfa = 270.3871 + 0.524038496 * d
    pbs = sum(A * math.cos(math.radians(0.985626 * d / tau + phi)) for A, tau, phi in _PBS)
    nu_m = ((10.691 + 3.0e-7 * d) * math.sin(M) + 0.623 * math.sin(2 * M) + 0.050 * math.sin(3 * M)
            + 0.005 * math.sin(4 * M) + 0.0005 * math.sin(5 * M) + pbs)
    ls = (alfa + nu_m) % 360
    s = math.sin(math.radians(ls))
    return ls, math.degrees(math.asin(0.42565 * s)) + 0.25 * s


def sol(lat, dec, hora_solar):
    """Elevación y azimut (desde el norte, en sentido horario) del Sol, en grados, a una hora solar local
    (0-24, horas marcianas: 12 = mediodía). Acepta arreglos."""
    p, d = math.radians(lat), math.radians(dec)
    H = np.radians(15.0 * (np.asarray(hora_solar, float) - 12.0))
    elev = np.degrees(np.arcsin(math.sin(p) * math.sin(d) + math.cos(p) * math.cos(d) * np.cos(H)))
    este = -math.cos(d) * np.sin(H)
    norte = math.sin(d) * math.cos(p) - math.cos(d) * math.sin(p) * np.cos(H)
    return elev, np.degrees(np.arctan2(este, norte)) % 360


def horas_de_luz(lat, dec):
    """(salida, puesta) del Sol en hora solar local, sin relieve ni refracción."""
    x = -math.tan(math.radians(lat)) * math.tan(math.radians(dec))
    if x <= -1:
        return 0.0, 24.0
    if x >= 1:
        return 12.0, 12.0
    h0 = math.degrees(math.acos(x)) / 15
    return 12 - h0, 12 + h0


def sombra_en_camino(mapa, camino, elev, azim, max_m=6000.0):
    """True donde el punto queda en la sombra del relieve con el Sol en (elev, azim) de ESE punto, o de noche."""
    a = np.asarray(camino, float)
    dem = np.nan_to_num(mapa.dem, nan=np.nanmin(mapa.dem))
    n, m = dem.shape
    elev, azim = np.asarray(elev, float), np.asarray(azim, float)
    noche = elev <= 0
    tan_e = np.tan(np.radians(np.clip(elev, 0.1, 89.9)))
    de, dn = np.sin(np.radians(azim)), np.cos(np.radians(azim))       # dirección hacia el Sol (este, norte)
    z = dem[a[:, 0].astype(int), a[:, 1].astype(int)] + 1.8           # altura de los ojos
    pasos = np.arange(1, int(max_m / v3.RES) + 1) * 1.0
    sombra = np.zeros(len(a), bool)
    for i in range(0, len(a), 400):
        sl = slice(i, i + 400)
        f = np.rint(a[sl, 0, None] - dn[sl, None] * pasos).astype(int)
        c = np.rint(a[sl, 1, None] + de[sl, None] * pasos).astype(int)
        dentro = (f >= 0) & (f < n) & (c >= 0) & (c < m)
        alto = np.where(dentro, dem[np.clip(f, 0, n - 1), np.clip(c, 0, m - 1)], -np.inf)
        sombra[sl] = np.any(alto > z[sl, None] + pasos * v3.RES * tan_e[sl, None], axis=1)
    return sombra | noche, noche
