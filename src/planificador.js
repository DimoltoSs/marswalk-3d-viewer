import * as THREE from 'three';
import { crearPin, crearTubo } from './rutas.js';
import { ESCALA_M } from './terreno.js';

/**
 * Planificador en vivo: el visor le pide rutas a servidor.py (FastAPI, puerto 8000).
 * Vite reenvía todo lo que empieza con /api al servidor (ver vite.config.js).
 *
 * Dos modos (los elige el selector de misión):
 *  - 'libre': clic 1 = inicio (A), clic 2 = final (B) -> ruta segura A→B que pasa por la mayor
 *             ciencia posible. Un 3.er clic empieza de nuevo con ese punto como A.
 *  - 'eva':   un clic = hábitat del astronauta -> radio de 3 km y la mejor salida de ida y vuelta.
 *             Otro clic mueve el hábitat y se recalcula todo.
 * Arrastrar sigue moviendo la vista: solo cuenta como clic si el ratón casi no se movió.
 *
 * avisos.alCambiar(resultado | null): main.js actualiza el rover y las métricas.
 */
const COLORES = {
  inicio: 0x3dff6e,    // A (mismo verde que el inicio de los planes)
  fin: 0xff3bd8,       // B (mismo morado que la meta)
  habitat: 0x4da3ff,   // hábitat del astronauta y su radio
  ruta: 0xff3b3b,      // mismo rojo que "Nuestro plan"
  objetivo: 0xffd23f,  // mismo amarillo que "Objetivos"
};
const RADIO_EVA_M = 3000;
const AYUDA = {
  libre: 'Clic 1 = inicio (A), clic 2 = final (B): se calcula la ruta segura que pasa por más '
    + 'minerales. Un 3.er clic empieza de nuevo. Arrastrar = mover la vista.',
  eva: 'Un clic = hábitat del astronauta: aparece el radio de 3 km y la mejor salida de ida y '
    + 'vuelta. Otro clic lo mueve. Arrastrar = mover la vista.',
};
const BOTON_AUTO = { libre: 'Puntos aleatorios', eva: 'Mejor centroide' };

/** Pide algo al servidor. Sin cuerpo = GET; con cuerpo = POST con JSON. */
async function api(ruta, cuerpo) {
  const opciones = cuerpo === undefined ? {} : {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cuerpo),
  };
  const resp = await fetch(`/api/${ruta}`, opciones);
  const esJson = resp.headers.get('content-type')?.includes('json');
  if (!esJson) throw new Error('El servidor no responde: arranca servidor.py (puerto 8000).');
  const datos = await resp.json();
  if (!resp.ok) {
    // FastAPI manda el motivo en "detail" (texto, o una lista si falló la validación)
    throw new Error(typeof datos.detail === 'string' ? datos.detail : 'Petición inválida.');
  }
  return datos;
}

/** Círculo de radio_m alrededor de (x, y), como lista de puntos [x, y] cerrada. */
function puntosCirculo(x, y, radio_m, n = 128) {
  return Array.from({ length: n + 1 }, (_, i) => {
    const a = (2 * Math.PI * i) / n;
    return [x + radio_m * Math.cos(a), y + radio_m * Math.sin(a)];
  });
}

export function crearPlanificador(terreno, camera, canvas, avisos) {
  const $ = (id) => document.getElementById(id);
  const grupo = new THREE.Group();
  // Separadas para que las casillas "Nuestro plan" y "Objetivos" también apliquen aquí
  const capas = { marcas: new THREE.Group(), plan: new THREE.Group(), objetivos: new THREE.Group() };
  grupo.add(capas.marcas, capas.plan, capas.objetivos);

  let modo = null;        // 'libre' | 'eva' | null (misión precalculada)
  let puntos = [];        // [[x, y], ...] en metros: [A, B] o [hábitat]
  let resultado = null;   // última respuesta del servidor
  let peticion = 0;       // cada clic nuevo invalida las respuestas que vengan en camino

  // ---- Dibujo ----
  function dibujar() {
    for (const capa of Object.values(capas)) {
      capa.traverse((o) => { o.geometry?.dispose(); o.material?.dispose(); });
      capa.clear();
    }
    if (modo === 'libre') {
      if (puntos[0]) capas.marcas.add(crearPin(terreno, ...puntos[0], COLORES.inicio, 4));
      if (puntos[1]) capas.marcas.add(crearPin(terreno, ...puntos[1], COLORES.fin, 4));
    } else if (modo === 'eva' && puntos[0]) {
      const [hx, hy] = puntos[0];
      capas.marcas.add(crearPin(terreno, hx, hy, COLORES.habitat, 5));
      capas.marcas.add(crearTubo(terreno, puntosCirculo(hx, hy, RADIO_EVA_M), COLORES.habitat, 0.15));
    }
    if (resultado?.plan) capas.plan.add(crearTubo(terreno, resultado.plan, COLORES.ruta, 0.25));
    for (const o of resultado?.objetivos ?? []) {
      const pin = crearPin(terreno, o.x, o.y, COLORES.objetivo, 4);
      pin.userData.objetivo = o;                // para la ficha al hacer clic (seleccion.js)
      capas.objetivos.add(pin);
    }
  }

  const estado = (texto) => { $('vivo-info').textContent = texto; };

  /** Pide la ruta del modo actual y la dibuja (si nadie hizo otro clic mientras tanto). */
  async function calcular() {
    const id = ++peticion;
    estado('Calculando…');
    try {
      const r = modo === 'eva'
        ? await api('eva', puntos.length ? { habitat: puntos[0] } : {})
        : await api('libre', { inicio: puntos[0], fin: puntos[1] });
      if (id !== peticion) return;              // llegó tarde: ya hay un clic más nuevo
      resultado = r;
      puntos = modo === 'eva' ? [r.habitat] : [r.inicio, r.fin];   // pueden venir ajustados
      dibujar();
      estado(r.avisos.join(' '));
      avisos.alCambiar(r);
    } catch (err) {
      if (id === peticion) estado(`⚠ ${err.message}`);
    }
  }

  function nuevoPunto(xy) {
    if (modo === 'eva') puntos = [xy];
    else puntos = puntos.length >= 2 ? [xy] : [...puntos, xy];   // 3.er clic = nuevo A
    resultado = null;
    peticion++;
    dibujar();
    avisos.alCambiar(null);
    if (modo === 'eva' || puntos.length === 2) calcular();
    else estado('Ahora haz clic en el final (B).');
  }

  // ---- Clic en el terreno ----
  const raycaster = new THREE.Raycaster();
  const raton = new THREE.Vector2();
  let inicio = null;
  canvas.addEventListener('pointerdown', (e) => { inicio = [e.clientX, e.clientY]; });
  canvas.addEventListener('pointerup', (e) => {
    if (!modo || !inicio) return;
    if (Math.hypot(e.clientX - inicio[0], e.clientY - inicio[1]) > 5) return;   // fue un arrastre
    const caja = canvas.getBoundingClientRect();
    raton.x = ((e.clientX - caja.left) / caja.width) * 2 - 1;
    raton.y = -((e.clientY - caja.top) / caja.height) * 2 + 1;
    raycaster.setFromCamera(raton, camera);
    // Clic sobre un objetivo = ver su ficha (seleccion.js), no poner un punto
    if (capas.objetivos.visible && raycaster.intersectObjects(capas.objetivos.children, true).length) return;
    const toque = raycaster.intersectObject(terreno.mesh)[0];
    // Escena -> metros: x = Este, y = Norte (el eje z de la escena apunta al Sur)
    if (toque) nuevoPunto([toque.point.x * ESCALA_M, -toque.point.z * ESCALA_M]);
  });

  // ---- Botones ----
  $('vivo-auto').addEventListener('click', async () => {
    if (modo === 'eva') {                       // sin hábitat: el servidor usa el mejor centroide
      puntos = [];
      calcular();
      return;
    }
    try {
      puntos = (await api('aleatorios?n=2')).puntos;
    } catch (err) {
      estado(`⚠ ${err.message}`);
      return;
    }
    resultado = null;
    dibujar();
    calcular();
  });

  function limpiar() {
    puntos = [];
    resultado = null;
    peticion++;
    dibujar();
    estado('');
    avisos.alCambiar(null);
  }
  $('vivo-limpiar').addEventListener('click', limpiar);

  /** 'libre' | 'eva' | null. Cambiar de modo limpia el mapa. */
  function cambiarModo(nuevo) {
    modo = nuevo;
    limpiar();
    if (!modo) return;
    $('vivo-ayuda').textContent = AYUDA[modo];
    $('vivo-auto').textContent = BOTON_AUTO[modo];
  }

  return { grupo, capas, reconstruir: dibujar, cambiarModo };
}
