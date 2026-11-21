"""mision_v3.py - Planificador de misiones v3: modelo del notebook v2 + NSGA-II mejorado.

Qué cambia frente al notebook planificador_v2 (sección 8) y al genético del proyecto:
  1. Operadores más exploradores (SBX eta 3, PM eta 5, prob_var 0.15): el genético viejo se
     estancaba con muchos candidatos (ver laboratorio-genetico).
  2. Población inicial sembrada con misiones de un objetivo y con el greedy a varios presupuestos.
  3. Para cada conjunto de objetivos se prueban varios ÓRDENES (2-opt por tiempo, 2-opt por riesgo
     y el orden tal cual) y varias RUTAS por tramo (perfil normal, perfil seguro y mixto).
  4. Búsqueda local al final: rellena el presupuesto que sobra en las misiones de más ciencia,
     con movimientos grandes (quitar 1 o 2 y rellenar, or-opt) y búsqueda local iterada.
  5. El 2-opt y el greedy ahorran el recurso que de verdad se acaba (horas, energía o esfuerzo),
     no solo el tiempo.
  6. Para cuando el frente deja de mejorar (paciencia) o al límite de tiempo.
  7. Reserva de energía: la misión no puede gastar el 100 % de la batería.
  8. (Opcional) ciencia con rendimiento decreciente al repetir mineral.

Marswalk v4 (rama marswalk-v4; ver CAMBIOS_V4.md):
  9. Arena a escala de rover: capa `arena_textura` (textura HiRISE) en el costo, w_arena = 10 (validado en Séítah).
 10. Pendiente fina: se usa max(pendiente CTX 20 m, p95 de la pendiente HiRISE a 5 m) donde hay HiRISE.
 11. Duda de la IA y verificación del robot: `Mapa.desde_capas(..., prob_arena=, verificadas=)` y `replanear_tramo`.
 12. Astronauta con modelo metabólico (Pandolf + Santee a 0.38 g, traje + kit): energía y O2 por tramo, y
     `costo_regreso` (energía para volver al hábitat desde cada celda -> punto de no retorno).
 13. Correcciones de la evaluación: simplificar no cruza bloqueos, misión infactible marcada, paro sin depender
     del reloj, perfil por tramo cuando la misión "normal" no cabe, radio_m con meta = error.

Uso típico:
    mapa = Mapa.desde_capas(cargar(), p=parametros(ROVER))   # P_ROVER; para el astronauta, parametros(ASTRONAUTA)
    cands = candidatos_ciencia(mapa, L)
    plan = planear(mapa, cands, inicio, meta, ROVER, presupuesto={"h": 168, "wh": 5000})
    plan["frente"], plan["nombradas"]
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage as ndi
from scipy.ndimage import uniform_filter
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

RES = 20.0  # metros por celda

# ---------------------------------------------------------------- parámetros (notebook v2)
P = dict(
    pend_ref=15.0,     # grados: a esta pendiente el término de pendiente vale 1
    pend_riesgo=10.0,  # desde aquí la celda es "de riesgo"
    pend_max=20.0,     # desde aquí la celda está bloqueada
    w_pend=1.0, w_rug=0.3, w_duna=0.5,
    w_arena=10.0,      # arena por textura HiRISE (o prob. de la IA): elegido en los tramos A y C de Jezero, probado en B
    w_incierto=0.0,    # castigo extra en celdas donde la IA duda (0.4 <= p <= 0.6); 0 = solo se marcan para el robot
    rug_ventana=5, duna_unidad=7,
    w_subida=8.0,      # 1 m de subida cuesta como 8 m de camino plano
    w_seguro=4.0,      # perfil "seguro": una celda de riesgo cuesta (1 + 4) veces más
)
# Umbrales del rover: los conductores de Perseverance evitan inclinaciones > 30° (diseño 45°; NASA/JPL, rover
# components). Con pendiente fina (p95 HiRISE 5 m), el umbral de 20° bloquea celdas por donde Perseverance sí pasó
# (1.6-4.4 % de su ruta real en los tramos B y C), así que para el rover: riesgo >= 15°, bloqueado >= 30°.
# P (riesgo 10°, bloqueado 20°) queda para el astronauta (Apollo 15: tramo más empinado ~15°).
P_ROVER = dict(P, pend_riesgo=15.0, pend_max=30.0)
VALOR_MINERAL = {2: 1.0, 6: 1.0, 3: 1.0, 9: 1.0, 10: 1.0, 4: 0.8, 5: 0.8, 1: 0.6, 7: 0.4, 8: 0.4}
FACTOR_CONF = {1: 0.6, 2: 1.0}
NOMBRES = {1: "Olivine", 2: "Mg-Carbonate", 3: "Fe/Mg-Smectite", 4: "Olivine+Smectite",
           5: "Olv.Smect+2.2um", 6: "Carb.+2.2um", 7: "High-Ca Pyroxene", 8: "Low-Ca Pyroxene",
           9: "Kaolinite", 10: "Mg-Smectite 2"}
AREA_REF_HA = 50.0
VECINOS = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]


@dataclass(frozen=True)
class Agente:
    """Quién recorre la misión: cambia velocidades, energía y tiempo de estudio.
    Si `metabolico` es True, la energía ('wh') es el gasto metabólico del astronauta (Pandolf + Santee) y no
    se usan wh_por_m / wh_por_m_subida."""
    nombre: str
    vel_seguro_m_h: float
    vel_riesgo_m_h: float
    wh_por_m: float
    wh_por_m_subida: float
    horas_por_objetivo: float
    w_estudio: float
    metabolico: bool = False
    masa_kg: float = 80.0        # persona
    traje_kg: float = 104.0      # máx. recomendado para trajes de Marte (NASA, ICES 2026, NTRS 20260005410)
    kit_kg: float = 10.0         # herramientas y muestras (control "kit" del dashboard)
    eta_terreno: float = 1.2     # Pandolf: 1.0 asfalto, 1.2 terracería/regolito firme
    eta_arena: float = 2.1       # Pandolf: arena suelta
    g_rel: float = 0.38          # gravedad de Marte / Tierra (escalado lineal: cota baja, ver CAMBIOS_V4.md)


# Rover: 1.3 Wh/m ~ <200 W a <=152 m/h (NASA, componentes de Perseverance); el valor viejo (0.25) era ~5x bajo.
ROVER = Agente("rover", 100.0, 50.0, 1.3, 2.0, 4.0, 60.0)
# Astronauta a pie: ~2 km/h (Apollo 15: 1-2 km/h). Estudio: 150 W metabólicos por hora de trabajo en una parada.
ASTRONAUTA = Agente("astronauta", 2000.0, 1000.0, 0.0, 0.0, 0.5, 150.0, metabolico=True)
O2_L_POR_WH = 3600 / 20100   # 20.1 kJ por litro de O2 consumido (equivalente calórico) -> ~0.179 L/Wh


def parametros(agente: "Agente") -> dict:
    """Umbrales del mapa de costos para cada agente: P_ROVER (riesgo 15°, bloqueo 30°) para el rover y P
    (10° y 20°) para el astronauta a pie. Uso: Mapa.desde_capas(L, p=parametros(agente))."""
    return P if agente.metabolico else P_ROVER


def pandolf_w(agente: Agente, v_m_s, grado_pct, eta):
    """Potencia metabólica [W] (Pandolf 1977 + corrección de bajada de Santee 2001; forma de Kim et al., IEEE EMBC
    2024, NASA JSC, NTRS 20240001423), escalada por la gravedad relativa."""
    W, Lk = agente.masa_kg, agente.traje_kg + agente.kit_kg
    M = 1.5 * W + 2.0 * (W + Lk) * (Lk / W) ** 2 + eta * (W + Lk) * (1.5 * v_m_s ** 2 + 0.35 * v_m_s * grado_pct)
    cf = eta * ((grado_pct * (W + Lk) * v_m_s) / 3.5 - (W + Lk) * (grado_pct + 6) ** 2 / W + 25 - v_m_s ** 2)
    M = np.where(grado_pct < 0, M - cf, M)   # MF = MP - CF (Kim et al. 2024, ec. 1): en bajada se RESTA CF
    return np.maximum(M, 1.5 * W) * agente.g_rel


@dataclass
class OpcionesGA:
    pop_size: int = 100
    max_gen: int = 100
    paciencia: int = 25          # generaciones sin mejorar el frente antes de parar
    timeout_s: float | None = None   # None = parar solo por generaciones/paciencia (reproducible en cualquier máquina)
    sbx_eta: float = 3.0
    pm_eta: float = 5.0
    pm_prob_var: float = 0.15
    semilla: int = 42
    reserva_energia: float = 0.10   # fracción de la batería que NO se puede gastar
    repeticion_mineral: float = 1.0  # 0.5 = el 2.º objetivo del mismo mineral vale la mitad
    max_frente: int = 30
    ordenes_extra: bool = True      # probar orden por riesgo y orden crudo
    perfiles_ruta: bool = True      # probar ruta segura y mixta por tramo
    sembrar: bool = True            # población inicial con greedy y misiones de un objetivo
    busqueda_local: int = 8         # misiones de más ciencia que se pulen al final (0 = no)
    ils_iter: int = 50              # iteraciones de búsqueda local iterada sobre la mejor misión
    prob_visita: float = 0.3        # prob. de que un candidato se visite en la población aleatoria


# ---------------------------------------------------------------- mapa de costos (v2)
def _rugosidad(pend, ventana):
    m1 = uniform_filter(pend, ventana)
    m2 = uniform_filter(pend ** 2, ventana)
    rug = np.sqrt(np.maximum(m2 - m1 ** 2, 0))
    lo, hi = np.percentile(rug, [5, 99])
    if not hi > lo:          # pendiente uniforme: sin rugosidad (antes dividía entre 0 y el costo quedaba NaN)
        return np.zeros_like(rug)
    return np.clip((rug - lo) / (hi - lo), 0, 1)


@dataclass
class Mapa:
    costo: np.ndarray       # costo por celda (inf = bloqueado)
    dem: np.ndarray
    pend: np.ndarray
    riesgo: np.ndarray      # bool: 10-20°
    duna: np.ndarray        # bool: terreno lento (unidad eólica o arena)
    bloqueado: np.ndarray   # bool
    arena: np.ndarray = None      # bool: arena (textura HiRISE, IA o robot)
    incierto: np.ndarray = None   # bool: la IA duda (0.4 <= p <= 0.6) y nadie lo ha verificado -> objetivo del robot
    origen: np.ndarray = None     # uint8 por celda: 0 órbita (pendiente/geología), 1 textura HiRISE, 2 IA, 3 robot ✓
    params: dict = None           # parámetros con que se construyó (P o P_ROVER); None = P

    ORIGENES = {0: "ORBIT", 1: "HIRISE_TEXTURE", 2: "AI", 3: "SCOUT_VERIFIED"}

    @classmethod
    def desde_capas(cls, L, p=P, prob_arena=None, verificadas=None):
        """prob_arena: arreglo 0..1 (salida de la IA) que sustituye a la capa de textura donde no es NaN.
        verificadas: {(fila, col): "arena" | "firme"} o arreglo int8 (1 arena, 0 firme, -1 sin verificar);
        lo que verificó el robot manda sobre la IA y la textura."""
        pend = np.nan_to_num(L["pendiente"]).astype(np.float64)
        if "pendiente_hirise_p95" in L:      # pendiente fina donde hay HiRISE (la de 20 m esconde escarpes)
            pend = np.fmax(pend, np.nan_to_num(L["pendiente_hirise_p95"]))
        bloqueado = np.isnan(L["pendiente"]) | (pend >= p["pend_max"])
        riesgo = ~bloqueado & (pend >= p["pend_riesgo"])
        eolica = L["unidades_geologicas"] == p["duna_unidad"] if "unidades_geologicas" in L \
            else np.zeros(pend.shape, bool)
        origen = np.zeros(pend.shape, np.uint8)
        p_arena = np.zeros(pend.shape)
        if "arena_textura" in L:
            p_arena = L["arena_textura"].astype(np.float64)
            origen[L["arena_textura"] > 0] = 1
        incierto = np.zeros(pend.shape, bool)
        if prob_arena is not None:
            ia = np.isfinite(prob_arena)
            p_arena = np.where(ia, prob_arena, p_arena)
            origen[ia] = 2
            incierto = ia & (prob_arena >= 0.4) & (prob_arena <= 0.6)
        if verificadas is not None:
            ver = _verificadas_a_arreglo(verificadas, pend.shape)
            hecho = ver >= 0
            p_arena = np.where(hecho, ver.astype(np.float64), p_arena)
            origen[hecho] = 3
            incierto &= ~hecho
        arena = p_arena >= 0.5
        costo = (1 + p["w_pend"] * (pend / p["pend_ref"]) ** 2
                 + p["w_rug"] * _rugosidad(pend, p["rug_ventana"]) + p["w_duna"] * eolica
                 + p["w_arena"] * p_arena + p["w_incierto"] * incierto)
        costo[bloqueado] = np.inf
        return cls(costo, L["dem"].astype(np.float64), pend, riesgo, eolica | arena, bloqueado,
                   arena, incierto, origen, dict(p))

    @property
    def forma(self):
        return self.costo.shape


def _verificadas_a_arreglo(verificadas, forma):
    if isinstance(verificadas, np.ndarray):
        return verificadas.astype(np.int8)
    ver = np.full(forma, -1, np.int8)
    for (f, c), estado in verificadas.items():
        ver[f, c] = 1 if estado == "arena" else 0
    return ver


def candidatos_ciencia(mapa: Mapa, L, valor_min=0.6, area_min_celdas=25):
    """Manchas CRISM valiosas y transitables (igual que el notebook v2), de mayor a menor ciencia."""
    tab = lambda d: np.array([d.get(i, 0.0) for i in range(256)], dtype=np.float32)  # noqa: E731
    valor = tab(VALOR_MINERAL)[L["mineralogia"]] * tab(FACTOR_CONF)[L["mineralogia_confianza"]]
    interes = (valor >= valor_min) & ~mapa.bloqueado
    etiquetas, n = ndi.label(interes, structure=np.ones((3, 3)))
    out = []
    for k, sl in enumerate(ndi.find_objects(etiquetas), start=1):
        mask = etiquetas[sl] == k
        if mask.sum() < area_min_celdas:
            continue
        celdas = np.argwhere(mask) + [sl[0].start, sl[1].start]
        area_ha = len(celdas) * 0.04
        calidad = float(valor[sl][mask].mean())
        centro = celdas.mean(axis=0)
        celda = celdas[np.argmin(((celdas - centro) ** 2).sum(axis=1))]
        cod = int(np.bincount(L["mineralogia"][sl][mask]).argmax())
        out.append({"celda": (int(celda[0]), int(celda[1])), "mineral": NOMBRES.get(cod, str(cod)),
                    "area_ha": round(area_ha, 1), "calidad": round(calidad, 2),
                    "ciencia": round(calidad * min(1.0, area_ha / AREA_REF_HA) ** 0.5, 3)})
    out.sort(key=lambda c: -c["ciencia"])
    return out


# ---------------------------------------------------------------- grafo en una ventana
@dataclass
class Ventana:
    """Recorte del mapa (más rápido que buscar en el mapa completo de 1000 x 1000)."""
    mapa: Mapa
    f0: int
    c0: int
    costo: np.ndarray       # recortado (y con lo de fuera del radio bloqueado, si aplica)

    @classmethod
    def alrededor(cls, mapa: Mapa, celdas, margen_m=1500.0, centro=None, radio_m=None):
        celdas = np.asarray(celdas)
        m = int(margen_m // RES)
        n_f, n_c = mapa.forma
        f0, c0 = max(0, celdas[:, 0].min() - m), max(0, celdas[:, 1].min() - m)
        f1, c1 = min(n_f, celdas[:, 0].max() + m + 1), min(n_c, celdas[:, 1].max() + m + 1)
        costo = mapa.costo[f0:f1, c0:c1].copy()
        if radio_m is not None:
            ff, cc = np.ogrid[f0:f1, c0:c1]
            costo[RES * np.hypot(ff - centro[0], cc - centro[1]) > radio_m] = np.inf
        return cls(mapa, int(f0), int(c0), costo)

    def sl(self, a):
        return a[self.f0:self.f0 + self.costo.shape[0], self.c0:self.c0 + self.costo.shape[1]]

    def local(self, celda):
        return (celda[0] - self.f0) * self.costo.shape[1] + (celda[1] - self.c0)

    def grafo(self, seguro: bool, p=P) -> csr_matrix:
        """Mismos pasos y pesos que astar/construir_grafo del notebook v2 (+ castigo si es seguro)."""
        costo = self.costo
        if seguro:
            costo = costo * (1 + p["w_seguro"] * self.sl(self.mapa.riesgo))
        dem = self.sl(self.mapa.dem)
        n, m = costo.shape
        libre = np.isfinite(costo)
        filas, cols = np.meshgrid(np.arange(n), np.arange(m), indexing="ij")
        o, d, w = [], [], []
        for df, dc in VECINOS:
            fa = filas[max(0, -df):min(n, n - df), max(0, -dc):min(m, m - dc)]
            ca = cols[max(0, -df):min(n, n - df), max(0, -dc):min(m, m - dc)]
            fb, cb = fa + df, ca + dc
            ok = libre[fa, ca] & libre[fb, cb]
            if df and dc:
                ok &= libre[fa, cb] & libre[fb, ca]
            fa, ca, fb, cb = fa[ok], ca[ok], fb[ok], cb[ok]
            dz = dem[fb, cb] - dem[fa, ca]
            d3 = np.hypot(RES * math.hypot(df, dc), dz)
            w.append(d3 * (costo[fa, ca] + costo[fb, cb]) / 2 + p["w_subida"] * np.maximum(dz, 0))
            o.append(fa * m + ca)
            d.append(fb * m + cb)
        return csr_matrix((np.concatenate(w), (np.concatenate(o), np.concatenate(d))), shape=(n * m, n * m))


# ---------------------------------------------------------------- matriz de tramos
@dataclass
class Tramos:
    """Métricas de cada tramo i -> j para cada perfil de ruta ('normal', 'seguro')."""
    nodos: list
    perfiles: list
    M: dict = field(default_factory=dict)      # (perfil, métrica) -> matriz N x N
    alcanzable: np.ndarray = None
    caminos: dict = field(default_factory=dict)  # (perfil, i, j) -> [(fila, col), ...] global

    def get(self, perfil, metrica):
        return self.M[(perfil, metrica)]


METRICAS = ("costo", "km", "h", "wh", "riesgo_km", "pend_max")


def _metricas_camino(v: Ventana, cam_local, agente: Agente):
    f, c = cam_local[:, 0], cam_local[:, 1]
    dem, pend = v.sl(v.mapa.dem)[f, c], v.sl(v.mapa.pend)[f, c]
    lento = (v.sl(v.mapa.riesgo) | v.sl(v.mapa.duna))[f, c][1:]
    riesgo = v.sl(v.mapa.riesgo)[f, c][1:]
    dz = np.diff(dem)
    d3 = np.hypot(RES * np.hypot(np.diff(f), np.diff(c)), dz)
    vel = np.where(lento, agente.vel_riesgo_m_h, agente.vel_seguro_m_h)
    t_h = d3 / vel
    if agente.metabolico:
        arena = v.sl(v.mapa.arena)[f, c][1:] if v.mapa.arena is not None else np.zeros(len(d3), bool)
        dh = np.maximum(RES * np.hypot(np.diff(f), np.diff(c)), 1e-6)
        eta = np.where(arena, agente.eta_arena, agente.eta_terreno)
        wh = float((pandolf_w(agente, vel / 3600, 100 * dz / dh, eta) * t_h).sum())
    else:
        wh = agente.wh_por_m * d3.sum() + agente.wh_por_m_subida * dz[dz > 0].sum()
    return dict(km=d3.sum() / 1000, h=float(t_h.sum()), wh=wh,
                riesgo_km=d3[riesgo].sum() / 1000, pend_max=float(pend.max()))


def matriz_tramos(v: Ventana, nodos, agente: Agente, perfiles=("normal", "seguro")) -> Tramos:
    N = len(nodos)
    T = Tramos(list(nodos), list(perfiles))
    T.alcanzable = np.eye(N, dtype=bool)
    m = v.costo.shape[1]
    idx = [v.local(nd) for nd in nodos]
    for perfil in perfiles:
        for k in METRICAS:
            T.M[(perfil, k)] = np.zeros((N, N))
        g = v.grafo(seguro=(perfil == "seguro"))
        dist, pred = dijkstra(g, directed=True, indices=idx, return_predecessors=True)
        for i in range(N):
            for j in range(N):
                if i == j or not np.isfinite(dist[i, idx[j]]):
                    continue
                cam, a = [], idx[j]
                while a != idx[i]:
                    cam.append(a)
                    a = pred[i, a]
                cam.append(idx[i])
                cam = np.array(divmod(np.array(cam[::-1]), m)).T
                met = _metricas_camino(v, cam, agente)
                met["costo"] = float(dist[i, idx[j]])
                for k in METRICAS:
                    T.M[(perfil, k)][i, j] = met[k]
                T.alcanzable[i, j] = True
                T.caminos[(perfil, i, j)] = [(int(a) + v.f0, int(b) + v.c0) for a, b in cam]
    return T


# ---------------------------------------------------------------- evaluación de misiones
class Problema:
    """Nodos: 0 = inicio; si es ida y vuelta, el final también es 0; si no, el final es 1.
    Los candidatos son los nodos `primer` .. N-1."""

    def __init__(self, T: Tramos, ciencia, minerales, agente: Agente, presupuesto: dict,
                 cerrado: bool, op: OpcionesGA):
        self.T, self.agente, self.cerrado, self.op = T, agente, cerrado, op
        self.ciencia, self.minerales = list(ciencia), list(minerales)
        self.primer = 1 if cerrado else 2
        self.K = len(T.nodos) - self.primer
        self.pres = dict(presupuesto)
        if "wh" in self.pres:
            self.pres["wh"] *= (1 - op.reserva_energia)
        self.archivo_F = np.empty((0, 3))
        self.archivo = []              # misiones (dict) del frente
        self.version = 0               # cambia cada vez que el archivo mejora
        self._vistos = set()
        self._pulido = {}
        # Listas de Python: indexarlas es ~10 veces más rápido que indexar numpy escalar a escalar
        self._L = {k: v.tolist() for k, v in T.M.items()}
        self._alc = T.alcanzable.tolist()
        self._busq = {}

    # --- piezas
    def ruta(self, seq):
        return (0, *seq, 0) if self.cerrado else (0, *seq, 1)

    def _ciencia(self, seq):
        total, cuenta = 0.0, {}
        for k in seq:
            mn = self.minerales[k - self.primer]
            r = cuenta.get(mn, 0)
            total += self.ciencia[k - self.primer] * self.op.repeticion_mineral ** r
            cuenta[mn] = r + 1
        return total

    def evaluar(self, seq, perfiles=None):
        """perfiles: un perfil por tramo (None = todo 'normal'). None si algún tramo no tiene camino."""
        nodos = self.ruta(seq)
        tramos = list(zip(nodos[:-1], nodos[1:]))
        perfiles = perfiles or ("normal",) * len(tramos)
        alc, L = self._alc, self._L
        if not all(alc[a][b] for a, b in tramos):
            return None
        g = lambda k: sum(L[(p, k)][a][b] for p, (a, b) in zip(perfiles, tramos))  # noqa: E731
        estudio = self.agente.horas_por_objetivo * len(seq)
        return {"seq": tuple(seq), "perfiles": tuple(perfiles), "ciencia": self._ciencia(seq),
                "h": g("h") + estudio, "wh": g("wh") + self.agente.w_estudio * estudio,
                "km": g("km"), "riesgo_km": g("riesgo_km"), "costo": g("costo"),
                "pend_max": max(L[(p, "pend_max")][a][b] for p, (a, b) in zip(perfiles, tramos))}

    def factible(self, m):
        return m is not None and all(m[k] <= v + 1e-9 for k, v in self.pres.items())

    def violacion(self, m):
        if m is None:
            return [1e6] * len(self.pres)
        return [m[k] - v for k, v in self.pres.items()]

    @staticmethod
    def objetivos(m):
        return np.array([-m["ciencia"], m["h"], m["riesgo_km"]])

    def _two_opt(self, seq, matriz):
        """2-opt sobre `matriz` (lista de listas). Nunca empeora el orden de entrada."""
        mejor = list(seq)
        if len(mejor) < 2:
            return tuple(mejor)
        fin = 0 if self.cerrado else 1

        def costo(s):
            t, prev = 0.0, 0
            for x in s:
                t += matriz[prev][x]
                prev = x
            return t + matriz[prev][fin]

        t = costo(mejor)
        mejoro = True
        while mejoro:
            mejoro = False
            for i in range(len(mejor) - 1):
                for j in range(i + 1, len(mejor)):
                    cand = mejor[:i] + mejor[i:j + 1][::-1] + mejor[j + 1:]
                    tc = costo(cand)
                    if tc < t - 1e-9:
                        mejor, t, mejoro = cand, tc, True
        return tuple(mejor)

    def _or_opt(self, seq, matriz, max_seg=3):
        """Or-opt: mueve tramos de 1 a 3 paradas seguidas a otra posición si baja el costo.
        Complementa al 2-opt (que invierte tramos pero no los cambia de lugar)."""
        mejor = list(seq)
        if len(mejor) < 3:
            return tuple(mejor)
        fin = 0 if self.cerrado else 1

        def costo(s):
            t, prev = 0.0, 0
            for x in s:
                t += matriz[prev][x]
                prev = x
            return t + matriz[prev][fin]

        t = costo(mejor)
        mejoro = True
        while mejoro:
            mejoro = False
            for largo in range(1, min(max_seg, len(mejor) - 1) + 1):
                for i in range(len(mejor) - largo + 1):
                    tramo, resto = mejor[i:i + largo], mejor[:i] + mejor[i + largo:]
                    for j in range(len(resto) + 1):
                        if j == i:
                            continue
                        cand = resto[:j] + tramo + resto[j:]
                        tc = costo(cand)
                        if tc < t - 1e-9:
                            mejor, t, mejoro = cand, tc, True
                            break
                    if mejoro:
                        break
                if mejoro:
                    break
        return tuple(mejor)

    def _pulir(self, seq):
        """Mejor orden conocido para un conjunto: 2-opt + or-opt sobre el recurso limitado."""
        M = self._matriz_busqueda("recurso")
        return list(self._or_opt(self._two_opt(seq, M), M))

    def _matriz_busqueda(self, metrica):
        """Matriz para el 2-opt. 'recurso' = suma de cada recurso limitado / su presupuesto
        (así el orden ahorra lo que de verdad se acaba: horas, energía o esfuerzo)."""
        if metrica not in self._busq:
            if metrica == "recurso":
                M = sum(self.T.get("normal", k) / v for k, v in self.pres.items() if v > 0) \
                    if self.pres else self.T.get("normal", "h")
            else:
                M = self.T.get("normal", metrica)
            self._busq[metrica] = np.where(self.T.alcanzable, M, 1e9).tolist()
        return self._busq[metrica]

    def _uso(self, m):
        """Fracción del presupuesto usada (suma de recursos normalizados)."""
        return sum(m[k] / v for k, v in self.pres.items() if v > 0) if self.pres else m["h"]

    def _mixto(self, m):
        """Cambia a ruta segura los tramos donde más riesgo se ahorra por hora extra, mientras quepa."""
        seq, perf = m["seq"], list(m["perfiles"])
        nodos = self.ruta(seq)
        opciones = []
        for t, (a, b) in enumerate(zip(nodos[:-1], nodos[1:])):
            if not self._alc[a][b]:
                continue
            L = self._L
            ahorro = L[("normal", "riesgo_km")][a][b] - L[("seguro", "riesgo_km")][a][b]
            extra = L[("seguro", "h")][a][b] - L[("normal", "h")][a][b]
            if ahorro > 1e-6:
                opciones.append((ahorro / max(extra, 1e-3), t))
        mejor = m
        for _, t in sorted(opciones, reverse=True):
            perf[t] = "seguro"
            cand = self.evaluar(seq, tuple(perf))
            if self.factible(cand):
                mejor = cand
            else:
                perf[t] = "normal"
        return mejor

    # --- núcleo: una secuencia decodificada -> métricas para el genético (+ archivo)
    def resolver(self, seq):
        fs = frozenset(seq)
        hit = self._pulido.get(fs)
        if hit is None:
            # Orden principal: el que ahorra el recurso que se acaba (energía, horas o esfuerzo).
            # Así un conjunto de objetivos que sí cabe no se descarta por estar mal ordenado.
            ordenes = [tuple(self._pulir(seq))]
            if self.op.ordenes_extra:
                ordenes += [self._two_opt(seq, self._matriz_busqueda("h")),
                            self._two_opt(seq, self._matriz_busqueda("riesgo_km"))]
            principal = self.evaluar(ordenes[0])
            if self.op.perfiles_ruta and principal is not None and not self.factible(principal):
                # Si con todo 'normal' no cabe, probar por tramo el perfil que menos gasta: a veces la ruta
                # 'segura' es más rápida y es la única forma de que el conjunto quepa (punto ciego de v3).
                alt = self._perfil_minimo(ordenes[0])
                if self.factible(alt):
                    principal = alt
            hit = (ordenes, principal)
            self._pulido[fs] = hit
        ordenes, principal = hit
        if self.op.ordenes_extra and len(seq) >= 2:
            ordenes = ordenes + [tuple(seq)]
        for orden in ordenes:
            if orden in self._vistos:
                continue
            self._vistos.add(orden)
            m = principal if orden == ordenes[0] else self.evaluar(orden)
            self._al_archivo(m)
            if self.op.perfiles_ruta and m is not None:
                self._al_archivo(self.evaluar(orden, ("seguro",) * (len(orden) + 1)))
                if self.factible(m):
                    self._al_archivo(self._mixto(m))
        return principal

    def _perfil_minimo(self, seq):
        nodos = self.ruta(seq)
        uso = (lambda p, a, b: sum(self._L[(p, k)][a][b] / v for k, v in self.pres.items() if v > 0)) if self.pres \
            else (lambda p, a, b: self._L[(p, "h")][a][b])
        perf = tuple(min(self.T.perfiles, key=lambda p: uso(p, a, b)) for a, b in zip(nodos[:-1], nodos[1:]))
        return self.evaluar(seq, perf)

    def _al_archivo(self, m):
        if not self.factible(m) or (self.cerrado and not m["seq"]):
            return
        f = self.objetivos(m)
        A = self.archivo_F
        if len(A):
            if np.any(np.all(A <= f + 1e-9, axis=1) & np.any(A < f - 1e-9, axis=1)):
                return
            if np.any(np.all(np.abs(A - f) <= 1e-6, axis=1)):
                return
            keep = ~(np.all(f <= A + 1e-9, axis=1) & np.any(f < A - 1e-9, axis=1))
            self.archivo_F = A[keep]
            self.archivo = [x for x, k in zip(self.archivo, keep, strict=True) if k]
        self.archivo_F = np.vstack([self.archivo_F, f])
        self.archivo.append(m)
        self.version += 1

    def _rellenar(self, seq, rng=None):
        """Inserta, mientras quepa, el candidato con más ciencia ganada por presupuesto gastado.
        Con `rng` elige al azar entre las 3 mejores inserciones (para no caer siempre en la misma).
        Cada inserción se valora con su costo incremental (tramo a->k->b menos a->b, más el
        estudio), sin reevaluar toda la misión: por eso es barato repetirlo miles de veces."""
        seq = list(seq)
        fin = 0 if self.cerrado else 1
        recursos = [(r, v, self._L[("normal", r)]) for r, v in self.pres.items() if v > 0]
        horas = self.agente.horas_por_objetivo
        estudio = {"h": horas, "wh": self.agente.w_estudio * horas}
        alc = self._alc
        while True:
            m = self.evaluar(seq)
            if m is None:
                return seq, None
            ruta = [0, *seq, fin]
            en_seq = set(seq)
            opciones = []
            for k in range(self.primer, len(self.T.nodos)):
                if k in en_seq or self.ciencia[k - self.primer] <= 0:
                    continue
                mejor = None
                gana = self._ciencia(seq + [k]) - m["ciencia"]
                if gana <= 0:
                    continue
                for pos in range(len(ruta) - 1):
                    a, b = ruta[pos], ruta[pos + 1]
                    if not (alc[a][k] and alc[k][b]):
                        continue
                    uso, cabe = 0.0, True
                    for r, tope, M in recursos:
                        d = M[a][k] + M[k][b] - M[a][b] + estudio.get(r, 0.0)
                        if m[r] + d > tope + 1e-9:
                            cabe = False
                            break
                        uso += d / tope
                    if cabe:
                        razon = gana / max(uso, 1e-6)
                        if mejor is None or razon > mejor[0]:
                            mejor = (razon, k, pos)
                if mejor is not None:
                    opciones.append(mejor)          # la mejor posición de cada candidato
            if not opciones:
                return seq, m
            opciones.sort(reverse=True)
            _, k, pos = opciones[0] if rng is None else opciones[int(rng.integers(min(3, len(opciones))))]
            nueva = seq[:pos] + [k] + seq[pos:]
            seq = self._pulir(nueva)
            if not self.factible(self.evaluar(seq)):
                seq = nueva

    def busqueda_local(self, seq, max_rondas=10, pares=True, rng=None):
        """Sube la ciencia de una misión sin pasarse del presupuesto ("destruir y reconstruir"):
        rellena con lo que quepa; luego prueba quitar 1 objetivo, o 2 (para que entre otro
        mejor: "2 por 1"), y volver a rellenar. Se acepta si la ciencia sube.
        Devuelve la mejor misión encontrada (o None)."""
        seq, m = self._rellenar(seq, rng)
        if m is None or not self.factible(m):
            return None
        self._registrar(m)
        for _ in range(max_rondas):
            mejor = m
            quitas = [(i,) for i in range(len(seq))]
            if pares:
                quitas += [(i, j) for i in range(len(seq)) for j in range(i + 1, len(seq))]
            for q in quitas:
                _, m2 = self._rellenar([x for i, x in enumerate(seq) if i not in q])
                if m2 is not None and self.factible(m2) and m2["ciencia"] > mejor["ciencia"] + 1e-9:
                    mejor = m2
            if mejor is m:
                break
            seq, m = list(mejor["seq"]), mejor
            self._registrar(m)
        return m

    def busqueda_iterada(self, m, iteraciones=50, rng=None):
        """Búsqueda local iterada: perturba la mejor misión (quita 2-3 objetivos al azar),
        la reconstruye eligiendo al azar entre las mejores inserciones y se queda con la nueva si tiene más ciencia
        (o la misma ciencia gastando menos presupuesto)."""
        rng = rng or np.random.default_rng(self.op.semilla)
        mejor = m
        for _ in range(iteraciones):
            seq = list(mejor["seq"])
            if not seq:
                break
            n_quitar = min(len(seq), int(rng.integers(2, 4)))
            quitar = set(rng.choice(len(seq), n_quitar, replace=False).tolist())
            m2 = self.busqueda_local([x for i, x in enumerate(seq) if i not in quitar],
                                     max_rondas=2, pares=False, rng=rng)
            if m2 is None:
                continue
            if (m2["ciencia"] > mejor["ciencia"] + 1e-9
                    or (abs(m2["ciencia"] - mejor["ciencia"]) <= 1e-9
                        and self._uso(m2) < self._uso(mejor) - 1e-9)):
                mejor = m2
        return mejor

    def _registrar(self, m):
        """Una misión encontrada por la búsqueda local entra al archivo con sus variantes de ruta."""
        self._al_archivo(m)
        if self.op.perfiles_ruta:
            self._al_archivo(self.evaluar(m["seq"], ("seguro",) * (len(m["seq"]) + 1)))
            self._al_archivo(self._mixto(m))
        if len(m["seq"]) >= 2:
            self.resolver(tuple(m["seq"]))

    def greedy(self, frac=1.0):
        """Inserta el candidato con más ciencia por presupuesto gastado mientras quepa (presupuesto * frac)."""
        pres = {k: v * frac for k, v in self.pres.items()}
        cabe = lambda m: m is not None and all(m[k] <= v + 1e-9 for k, v in pres.items())  # noqa: E731
        seq, pend = [], set(range(self.primer, len(self.T.nodos)))
        base = self.evaluar(seq)
        while True:
            mejor = None
            for k in pend:
                for pos in range(len(seq) + 1):
                    nueva = seq[:pos] + [k] + seq[pos:]
                    m = self.evaluar(nueva)
                    if not cabe(m):
                        continue
                    r = self.ciencia[k - self.primer] / max(self._uso(m) - (self._uso(base) if base else 0), 1e-6)
                    if mejor is None or r > mejor[0]:
                        mejor = (r, nueva, k, m)
            if mejor is None:
                return tuple(seq)
            _, seq, k, base = mejor
            pend.discard(k)


# ---------------------------------------------------------------- NSGA-II mejorado
def _decodificar(claves, primer):
    vis = np.nonzero(claves >= 0.5)[0]
    return tuple(int(i) + primer for i in vis[np.argsort(-claves[vis], kind="stable")])


def _codificar(seq, K, primer, rng):
    x = rng.uniform(0.0, 0.499, K)
    for pos, nodo in enumerate(seq):
        x[nodo - primer] = 0.5 + 0.5 * (len(seq) - pos) / (len(seq) + 1)
    return x


def optimizar(pb: Problema):
    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.core.callback import Callback
    from pymoo.core.problem import Problem
    from pymoo.operators.crossover.sbx import SBX
    from pymoo.operators.mutation.pm import PM
    from pymoo.optimize import minimize
    from pymoo.termination.collection import TerminationCollection
    from pymoo.termination.max_gen import MaximumGenerationTermination
    from pymoo.termination.max_time import TimeBasedTermination

    op, K = pb.op, pb.K
    pb.resolver(())                                  # misión vacía (A -> B directo)
    if K == 0:
        return
    if K == 1:
        pb.resolver((pb.primer,))
        return

    class _P(Problem):
        def __init__(self):
            super().__init__(n_var=K, n_obj=3, n_ieq_constr=len(pb.pres), xl=0.0, xu=1.0)

        def _evaluate(self, X, out, *a, **kw):
            F, G = np.empty((len(X), 3)), np.empty((len(X), len(pb.pres)))
            for i, x in enumerate(X):
                m = pb.resolver(_decodificar(x, pb.primer))
                F[i] = pb.objetivos(m) if m else (0.0, 1e9, 1e9)
                G[i] = pb.violacion(m)
            out["F"], out["G"] = F, G

    class _Paciencia(Callback):
        def __init__(self):
            super().__init__()
            self.ver, self.sin_mejora = -1, 0

        def notify(self, alg):
            if pb.version == self.ver:
                self.sin_mejora += 1
                if self.sin_mejora >= op.paciencia:
                    alg.termination.force_termination = True
            else:
                self.ver, self.sin_mejora = pb.version, 0

    rng = np.random.default_rng(op.semilla)
    forma = (op.pop_size, K)
    X = np.where(rng.random(forma) < op.prob_visita, rng.uniform(0.5, 1, forma), rng.uniform(0, 0.5, forma))
    semillas = []
    if op.sembrar:
        semillas = [pb.greedy(f) for f in (1.0, 0.75, 0.5, 0.25)]
        semillas += [(k,) for k in range(pb.primer, pb.primer + K)]
    for i, s in enumerate([s for s in dict.fromkeys(semillas) if s][:op.pop_size]):
        X[i] = _codificar(s, K, pb.primer, rng)

    alg = NSGA2(pop_size=op.pop_size, sampling=X, crossover=SBX(prob=0.9, eta=op.sbx_eta),
                mutation=PM(eta=op.pm_eta, prob_var=op.pm_prob_var), eliminate_duplicates=True)
    terms = [MaximumGenerationTermination(op.max_gen)]
    if op.timeout_s is not None:          # salvaguarda opcional; con tiempo límite el resultado depende de la máquina
        terms.append(TimeBasedTermination(max_time=op.timeout_s))
    term = TerminationCollection(*terms)
    res = minimize(_P(), alg, term, seed=op.semilla, verbose=False, callback=_Paciencia())
    pb.generaciones = res.algorithm.n_gen
    if op.busqueda_local:
        arranques = sorted(pb.archivo, key=lambda m: -m["ciencia"])[:op.busqueda_local]
        for i, m in enumerate(arranques):
            pb.busqueda_local(m["seq"], pares=(i == 0))   # "2 por 1" solo en la de más ciencia
    mejor = max(pb.archivo, key=lambda m: (m["ciencia"], -pb._uso(m)), default=None)
    if mejor is not None and mejor["seq"] and op.ils_iter:
        pb.busqueda_iterada(mejor, op.ils_iter, rng)


# ---------------------------------------------------------------- frente -> misiones con nombre
def _recortar(misiones, k):
    if len(misiones) <= k:
        return misiones
    F = np.array([Problema.objetivos(m) for m in misiones])
    span = np.where(np.ptp(F, axis=0) > 0, np.ptp(F, axis=0), 1.0)
    Fn = (F - F.min(axis=0)) / span
    dist = np.zeros(len(F))
    for j in range(3):
        o = np.argsort(Fn[:, j], kind="stable")
        dist[o[0]] = dist[o[-1]] = np.inf
        dist[o[1:-1]] += Fn[o[2:], j] - Fn[o[:-2], j]
    keep = sorted(np.argsort(-dist, kind="stable")[:k])
    return [misiones[i] for i in keep]


def elegir(frente, pesos):
    """Misión del frente que minimiza la suma ponderada de objetivos normalizados (0..1).
    pesos = {"ciencia": .., "tiempo": .., "riesgo": ..}"""
    F = np.array([Problema.objetivos(m) for m in frente])
    span = np.where(np.ptp(F, axis=0) > 0, np.ptp(F, axis=0), 1.0)
    Fn = (F - F.min(axis=0)) / span
    w = np.array([pesos.get("ciencia", 0), pesos.get("tiempo", 0), pesos.get("riesgo", 0)])
    return int(np.argmin(Fn @ w + 1e-6 * Fn.sum(axis=1)))


def nombrar(frente):
    F = np.array([Problema.objetivos(m) for m in frente])
    span = np.where(np.ptp(F, axis=0) > 0, np.ptp(F, axis=0), 1.0)
    Fn = (F - F.min(axis=0)) / span
    return {"ciencia": elegir(frente, {"ciencia": 1}),
            "rapida": elegir(frente, {"tiempo": 1}),
            "segura": elegir(frente, {"riesgo": 1}),
            "equilibrada": int(np.argmin(np.linalg.norm(Fn, axis=1)))}


def camino_mision(T: Tramos, pb: Problema, m):
    nodos = pb.ruta(m["seq"])
    camino = []
    for p, (a, b) in zip(m["perfiles"], zip(nodos[:-1], nodos[1:])):
        c = [T.nodos[a]] if a == b else T.caminos[(p, a, b)]
        camino += c if not camino else c[1:]
    return camino


def _celdas_segmento(p0, p1):
    """Todas las celdas que toca el segmento entre dos centros de celda (supercover exacto) y la fracción del
    segmento dentro de cada una. Si el segmento pasa justo por una esquina, se incluyen las dos celdas
    ortogonales (misma regla que las diagonales del grafo)."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    d = p1 - p0
    ts = [0.0, 1.0]
    for k in (0, 1):
        if d[k] != 0:
            lo, hi = sorted((p0[k], p1[k]))
            for b in np.arange(math.floor(lo - 0.5) + 0.5, hi + 0.5, 1.0):
                t = (b - p0[k]) / d[k]
                if 0 < t < 1:
                    ts.append(t)
    ts = np.unique(np.round(ts, 12))
    celdas, peso = [], []
    for t0, t1 in zip(ts[:-1], ts[1:]):
        mid = p0 + d * (t0 + t1) / 2
        celdas.append(np.floor(mid + 0.5).astype(int))
        peso.append(t1 - t0)
    for t in ts[1:-1]:                     # cruces por esquina exacta: las dos celdas ortogonales
        q = p0 + d * t
        frac = np.abs(q - np.floor(q) - 0.5)
        if (frac < 1e-9).all():
            antes, despues = np.floor(p0 + d * (t - 1e-6) + 0.5), np.floor(p0 + d * (t + 1e-6) + 0.5)
            celdas += [np.array([antes[0], despues[1]], int), np.array([despues[0], antes[1]], int)]
            peso += [0.0, 0.0]
    return np.array(celdas), np.array(peso)


def simplificar(mapa: Mapa, camino, tolerancia=0.03, max_salto=60):
    """Pocos waypoints unidos por rectas que no tocan bloqueos ni cuestan > 3 % más que el camino."""
    a = np.asarray(camino)
    if len(a) < 3:
        return [tuple(map(int, x)) for x in a]
    paso = mapa.costo[a[:-1, 0], a[:-1, 1]] + mapa.costo[a[1:, 0], a[1:, 1]]
    acum = np.concatenate([[0], np.cumsum(RES * np.hypot(*np.diff(a, axis=0).T) * paso / 2)])

    def recta(i, j):
        celdas, peso = _celdas_segmento(a[i], a[j])
        v = mapa.costo[celdas[:, 0], celdas[:, 1]]
        if not np.isfinite(v).all():
            return np.inf
        return float((v * peso).sum()) * RES * math.hypot(*(a[j] - a[i]))

    idx, i = [0], 0
    while i < len(a) - 1:
        j = i + 1
        while j + 1 < len(a) and j + 1 - i <= max_salto and recta(i, j + 1) <= (1 + tolerancia) * (acum[j + 1] - acum[i]):
            j += 1
        idx.append(j)
        i = j
    return [tuple(map(int, a[k])) for k in idx]


# ---------------------------------------------------------------- todo junto
def planear(mapa: Mapa, candidatos, inicio, meta=None, agente: Agente = ROVER, presupuesto=None,
            factor=None, radio_m=None, max_candidatos=15, op: OpcionesGA | None = None,
            filtro_elipse=True):
    """Planea una misión.
      - inicio y meta (fila, col): misión A -> B. Con `factor`, el presupuesto es factor x directo.
      - meta=None: misión de ida y vuelta a `inicio` (p. ej. EVA), opcionalmente dentro de `radio_m`.
      - presupuesto: {"h": .., "wh": .., "costo": ..} (se combina con el de `factor`).
    Devuelve dict con frente (misiones), nombradas, tramos, candidatos usados y tiempos."""
    op = op or OpcionesGA()
    t0 = time.perf_counter()
    cerrado = meta is None
    if not cerrado and radio_m is not None:
        raise ValueError("radio_m solo aplica a misiones de ida y vuelta (meta=None).")
    usar = []
    for c in candidatos:
        f, k = c["celda"]
        if mapa.bloqueado[f, k]:
            continue
        if cerrado and radio_m is not None and RES * math.hypot(f - inicio[0], k - inicio[1]) > radio_m:
            continue
        if not cerrado and filtro_elipse and factor is not None:
            d_ab = RES * math.hypot(inicio[0] - meta[0], inicio[1] - meta[1])
            d = RES * (math.hypot(f - inicio[0], k - inicio[1]) + math.hypot(f - meta[0], k - meta[1]))
            if d > factor * max(d_ab, 1.0):
                continue
        usar.append(c)
        if len(usar) == max_candidatos:
            break
    nodos = [tuple(inicio)] + ([] if cerrado else [tuple(meta)]) + [c["celda"] for c in usar]
    v = Ventana.alrededor(mapa, nodos, centro=inicio, radio_m=radio_m if cerrado else None)
    T = matriz_tramos(v, nodos, agente, ("normal", "seguro") if op.perfiles_ruta else ("normal",))
    t_tramos = time.perf_counter() - t0

    pres = dict(presupuesto or {})
    if not cerrado:
        if not T.alcanzable[0, 1]:
            pmax = (mapa.params or P)["pend_max"]
            raise ValueError(f"No hay camino seguro entre A y B (pendientes de {pmax:g}° o más).")
        if factor is not None:
            pres.setdefault("h", factor * T.get("normal", "h")[0, 1])
            if agente.wh_por_m > 0 or agente.metabolico:
                pres.setdefault("wh", factor * T.get("normal", "wh")[0, 1])
    primer = 1 if cerrado else 2
    # candidatos sin ida y vuelta posible no valen nada
    ciencia = [c["ciencia"] if T.alcanzable[0, k + primer] and T.alcanzable[k + primer, 0 if cerrado else 1]
               else 0.0 for k, c in enumerate(usar)]
    pb = Problema(T, ciencia, [c["mineral"] for c in usar], agente, pres, cerrado, op)
    pb.generaciones = 0
    optimizar(pb)
    frente = _recortar(pb.archivo, op.max_frente)
    aviso = None
    if not frente and not cerrado:   # nada cabe: la ruta directa es la única misión
        directa = pb.evaluar(())
        if not pb.factible(directa):
            directa = dict(directa, factible=False)
            aviso = ("La ruta directa NO cabe en el presupuesto (p. ej. por la reserva de energía): "
                     f"usa {', '.join(f'{k} {directa[k]:.1f}/{v:.1f}' for k, v in pb.pres.items())}.")
        frente = [directa]
    frente.sort(key=lambda m: (-m["ciencia"], m["h"], m["riesgo_km"]))
    nombradas = nombrar(frente) if frente else {}
    return {"frente": frente, "nombradas": nombradas, "tramos": T, "problema": pb,
            "candidatos": usar, "presupuesto": pb.pres, "nodos": nodos,
            "seg_tramos": round(t_tramos, 2), "seg_total": round(time.perf_counter() - t0, 2),
            "generaciones": pb.generaciones, "aviso": aviso}


# ---------------------------------------------------------------- Marswalk: replaneo, regreso y punto de no retorno
def replanear_tramo(mapa: Mapa, a, b, agente: Agente = ROVER, perfil="normal"):
    """Ruta de un solo tramo a -> b (lo que se recalcula en vivo cuando el robot marca una celda). ~0.1 s."""
    v = Ventana.alrededor(mapa, [a, b])
    for celda in (a, b):     # el vehículo ya está en a (o llega a b): sus celdas nunca bloquean el tramo
        i, j = celda[0] - v.f0, celda[1] - v.c0
        if not np.isfinite(v.costo[i, j]):
            v.costo[i, j] = 1.0 + (mapa.params or P)["w_pend"]
    T = matriz_tramos(v, [tuple(a), tuple(b)], agente, (perfil,))
    if not T.alcanzable[0, 1]:
        return None
    return {"camino": T.caminos[(perfil, 0, 1)], **{k: float(T.get(perfil, k)[0, 1]) for k in METRICAS}}


def costo_regreso(mapa: Mapa, base, agente: Agente = ASTRONAUTA, radio_m=5000.0):
    """Energía metabólica mínima [Wh] y tiempo mínimo [h] para volver a `base` desde cada celda, con el mismo
    grafo de rutas: Dijkstra desde la base sobre el grafo invertido, con pesos Pandolf + Santee (energía) y
    distancia / velocidad (tiempo).
    Devuelve dict(wh, h, o2_L) como arreglos del tamaño del mapa (NaN = inalcanzable o fuera del radio)."""
    v = Ventana.alrededor(mapa, [base], margen_m=radio_m, centro=base, radio_m=radio_m)
    n, m = v.costo.shape
    libre = np.isfinite(v.costo)
    dem, arena = v.sl(mapa.dem), v.sl(mapa.arena) if mapa.arena is not None else np.zeros((n, m), bool)
    lento = v.sl(mapa.riesgo | mapa.duna)
    filas, cols = np.meshgrid(np.arange(n), np.arange(m), indexing="ij")
    o, d, w_wh, w_h = [], [], [], []
    for df, dc in VECINOS:
        sl_a = (slice(max(0, -df), min(n, n - df)), slice(max(0, -dc), min(m, m - dc)))
        fa, ca = filas[sl_a], cols[sl_a]
        fb, cb = fa + df, ca + dc
        ok = libre[fa, ca] & libre[fb, cb]
        if df and dc:
            ok &= libre[fa, cb] & libre[fb, ca]
        fa, ca, fb, cb = fa[ok], ca[ok], fb[ok], cb[ok]
        dh = RES * math.hypot(df, dc)
        dz = dem[fb, cb] - dem[fa, ca]
        vel = np.where(lento[fb, cb], agente.vel_riesgo_m_h, agente.vel_seguro_m_h)
        t_h = np.hypot(dh, dz) / vel
        eta = np.where(arena[fb, cb], agente.eta_arena, agente.eta_terreno)
        w_wh.append(pandolf_w(agente, vel / 3600, 100 * dz / dh, eta) * t_h)
        w_h.append(t_h)
        o.append(fa * m + ca)
        d.append(fb * m + cb)
    o, d = np.concatenate(o), np.concatenate(d)
    i0 = v.local(base)
    salida = {}
    for clave, w in (("wh", np.concatenate(w_wh)), ("h", np.concatenate(w_h))):
        g = csr_matrix((w, (d, o)), shape=(n * m, n * m))      # aristas invertidas: Dijkstra desde la base
        dist = dijkstra(g, directed=True, indices=i0)
        arr = np.full(mapa.forma, np.nan)
        v.sl(arr)[...] = np.where(np.isfinite(dist), dist, np.nan).reshape(n, m)
        salida[clave] = arr                                     # 'h' = tiempo mínimo de regreso (su propia ruta)
    salida["o2_L"] = salida["wh"] * O2_L_POR_WH
    return salida


def perfil_regreso(mapa: Mapa, camino, regreso, agente: Agente, presupuesto_wh, reserva=0.10, paradas=()):
    """A lo largo de un camino (celdas): energía gastada, energía para volver al hábitat desde ahí y margen.
    El punto de no retorno es el primer punto donde gastado + regreso > presupuesto x (1 - reserva).
    Supone que la caminata empezó en la base. `paradas`: índices del camino donde se hace una parada de estudio
    (se suma horas_por_objetivo x w_estudio desde ahí). Devuelve dict de listas + índice del punto de no retorno."""
    a = np.asarray(camino)
    dz = np.diff(mapa.dem[a[:, 0], a[:, 1]])
    dh = RES * np.hypot(*np.diff(a, axis=0).T)
    lento = (mapa.riesgo | mapa.duna)[a[1:, 0], a[1:, 1]]
    vel = np.where(lento, agente.vel_riesgo_m_h, agente.vel_seguro_m_h)
    t_h = np.hypot(dh, dz) / vel
    arena = mapa.arena[a[1:, 0], a[1:, 1]] if mapa.arena is not None else np.zeros(len(dh), bool)
    eta = np.where(arena, agente.eta_arena, agente.eta_terreno)
    gastado = np.r_[0.0, np.cumsum(pandolf_w(agente, vel / 3600, 100 * dz / np.maximum(dh, 1e-6), eta) * t_h)]
    for i in paradas:
        gastado[i:] += agente.horas_por_objetivo * agente.w_estudio
    volver = regreso["wh"][a[:, 0], a[:, 1]]
    tope = presupuesto_wh * (1 - reserva)
    margen = tope - (gastado + volver)
    fuera = np.nonzero(~(margen >= 0))[0]
    return {"gastado_wh": gastado.tolist(), "regreso_wh": volver.tolist(), "margen_wh": margen.tolist(),
            "o2_gastado_L": (gastado * O2_L_POR_WH).tolist(), "punto_no_retorno": int(fuera[0]) if len(fuera) else None}


def regreso_mision(mapa: Mapa, T: Tramos, pb: Problema, m, regreso, presupuesto_wh, reserva=0.10):
    """perfil_regreso de una misión del frente, con la energía de cada parada de estudio en su lugar."""
    nodos = pb.ruta(m["seq"])
    camino, paradas = [], []
    for k, (p, (a, b)) in enumerate(zip(m["perfiles"], zip(nodos[:-1], nodos[1:]))):
        c = [T.nodos[a]] if a == b else T.caminos[(p, a, b)]
        camino += c if not camino else c[1:]
        if k < len(m["seq"]):
            paradas.append(len(camino) - 1)
    return dict(perfil_regreso(mapa, camino, regreso, pb.agente, presupuesto_wh, reserva, paradas),
                camino=camino, paradas=paradas)
