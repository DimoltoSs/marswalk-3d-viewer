"""cliente_rpi.py - Cliente del planificador para la Raspberry Pi (solo necesita `requests`).

    pip install requests
    python cliente_rpi.py --servidor http://192.168.1.50:8000            # usa el escenario de ejemplo
    python cliente_rpi.py --servidor http://192.168.1.50:8000 --inicio -1234 567 --meta 2000 -300

En el código del rover:
    from cliente_rpi import Planificador
    pl = Planificador("http://192.168.1.50:8000")
    plan = pl.planear(inicio=(x, y), meta=(x2, y2), prioridad="segura")
    for x, y in plan["waypoints"]:
        ...mover el rover...
    # si aparece un obstáculo:
    plan = pl.replanear(inicio=(x_actual, y_actual), meta=(x2, y2), visitados=[...])
"""
import argparse
import json
import os
import time

import requests

ARCHIVO_PLAN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ultimo_plan.json")


class Planificador:
    def __init__(self, servidor, api_key=None, timeout=90, reintentos=3):
        self.url = servidor.rstrip("/")
        self.timeout = timeout
        self.reintentos = reintentos
        self.s = requests.Session()
        if api_key:
            self.s.headers["X-API-Key"] = api_key

    def disponible(self):
        try:
            return self.s.get(f"{self.url}/salud", timeout=5).json().get("ok", False)
        except requests.RequestException:
            return False

    def _post(self, ruta, cuerpo):
        ultimo = None
        for intento in range(1, self.reintentos + 1):
            try:
                r = self.s.post(f"{self.url}{ruta}", json=cuerpo, timeout=self.timeout)
                if r.status_code == 422:                       # error de datos: no tiene caso reintentar
                    raise ValueError(r.json().get("detail"))
                r.raise_for_status()
                plan = r.json()
                with open(ARCHIVO_PLAN, "w", encoding="utf-8") as f:
                    json.dump(plan, f)
                return plan
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
                ultimo = e
                print(f"intento {intento} falló: {e}")
                time.sleep(2 * intento)
        print("sin conexión con el servidor: uso el último plan guardado")
        plan = self.ultimo_plan()
        if plan is None:
            raise ConnectionError(f"no hay servidor ni plan guardado ({ultimo})")
        return plan

    def planear(self, inicio, meta=None, prioridad="equilibrada", **extra):
        return self._post("/planear", {"inicio": list(inicio), "meta": list(meta) if meta else None,
                                       "prioridad": prioridad, **extra})

    def replanear(self, inicio, meta=None, visitados=(), prioridad="equilibrada", **extra):
        return self._post("/replanear", {"inicio": list(inicio), "meta": list(meta) if meta else None,
                                         "visitados": [list(v) for v in visitados],
                                         "prioridad": prioridad, **extra})

    def ejemplo(self):
        return self.s.get(f"{self.url}/ejemplo", timeout=5).json()

    @staticmethod
    def ultimo_plan():
        if os.path.exists(ARCHIVO_PLAN):
            with open(ARCHIVO_PLAN, encoding="utf-8") as f:
                return json.load(f)
        return None


def main():
    ap = argparse.ArgumentParser(description="Pide una ruta al planificador")
    ap.add_argument("--servidor", default=os.environ.get("PLANIFICADOR_URL", "http://localhost:8000"))
    ap.add_argument("--api-key", default=os.environ.get("API_KEY"))
    ap.add_argument("--inicio", type=float, nargs=2)
    ap.add_argument("--meta", type=float, nargs=2)
    ap.add_argument("--prioridad", default="equilibrada",
                    choices=["ciencia", "rapida", "segura", "equilibrada", "pesos"])
    ap.add_argument("--factor", type=float, default=2.0)
    a = ap.parse_args()

    pl = Planificador(a.servidor, a.api_key)
    print("servidor disponible:", pl.disponible())
    if a.inicio is None:
        ej = pl.ejemplo()
        a.inicio, a.meta = ej["inicio"], ej["meta"]
    t = time.perf_counter()
    plan = pl.planear(a.inicio, a.meta, a.prioridad, factor=a.factor)
    m = plan["metricas"]
    print(f"plan '{plan['prioridad']}' en {time.perf_counter() - t:.1f} s (cache: {plan.get('cache')})")
    print(f"  {len(plan['waypoints'])} waypoints · {m['objetivos']} objetivos · ciencia {m['ciencia']} · "
          f"{m['horas']} h · {m['km']} km")
    for o in plan["objetivos"]:
        print(f"  parada {o['parada']}: {o['mineral']} en ({o['x']}, {o['y']})")
    print("guardado en", ARCHIVO_PLAN)


if __name__ == "__main__":
    main()
