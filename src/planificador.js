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
 * El servidor (planificador v3) devuelve el frente de Pareto completo y cuatro misiones con nombre.
 * El selector "Prioridad" cambia de misión sin volver a calcular.
 *
 * avisos.alCambiar(resultado | null): main.js actualiza el rover y las métricas.
 */
const COLORES = {
  inicio: 0x3dff6e,    // A (mismo verde que el inicio de los planes)
  fin: 0xff3bd8,       // B (mismo morado que la meta)
  habitat: 0x4da3ff,   // hábitat del astronauta y su radio
  ruta: 0xff3b3b,      // mismo rojo que "Nuestro plan"
  objetivo: 0xffd23f,  // mismo amarillo que "Objetivos"
  o2Sobra: 0x3ddc84,   // EVA: % del tanque que quedaría al volver desde ese punto: > 25 %
  o2Justo: 0xffd23f,   //       15-25 %
  o2Poco: 0xff3b3b,    //       10-15 % (menos de 10 % = misión descartada por el servidor)
  intenso: 0xb45cff,   // EVA: tramos de más de 85 L/h de O2
  critico: 0xff8c1a,   // EVA: punto desde donde volver cuesta más O2
};

/** Tramos seguidos del mismo valor: [[valor, desde, hasta], ...] (índices de puntos, inclusivos). */
function tramosIguales(valores) {
  const tramos = [];
  valores.forEach((v, i) => {
    const ultimo = tramos[tramos.length - 1];
    if (ultimo && ultimo[0] === v) ultimo[2] = i + 1;
    else tramos.push([v, i, i + 1]);
  });
  return tramos;
}
const RADIO_EVA_M = 3000;
const AYUDA = {
  libre: 'Robot: clic 1 = inicio (A), clic 2 = final (B). Se calcula la ruta que pasa por más '
    + 'minerales sin agotar la batería. Un 3.er clic empieza de nuevo. Arrastrar = mover la vista.',
  eva: 'Astronautas: un clic = hábitat. Aparece el radio de 3 km y la mejor salida de ida y vuelta '
    + 'que cabe en el oxígeno del traje y en 8 h. Otro clic lo mueve. Arrastrar = mover la vista.',
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
  let resultado = null;   // última respuesta del servidor (con la misión de la prioridad elegida arriba)
  let prioridad = 'equilibrada';
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
    if (resultado?.plan && modo === 'eva' && resultado.tanque_pct) dibujarEva(resultado);
    else if (resultado?.plan) capas.plan.add(crearTubo(terreno, resultado.plan, COLORES.ruta, 0.25));
    for (const o of resultado?.objetivos ?? []) {
      const pin = crearPin(terreno, o.x, o.y, COLORES.objetivo, 4);
      pin.userData.objetivo = o;                // para la ficha al hacer clic (seleccion.js)
      capas.objetivos.add(pin);
    }
  }

  /** EVA: la ruta se colorea por el margen de O2 para volver; encima, los tramos de esfuerzo alto. */
  function dibujarEva(r) {
    const nivel = r.tanque_pct.slice(0, -1).map((p) => (
      p > 25 ? COLORES.o2Sobra : p >= 15 ? COLORES.o2Justo : COLORES.o2Poco));
    for (const [color, i, j] of tramosIguales(nivel)) {
      capas.plan.add(crearTubo(terreno, r.plan.slice(i, j + 1), color, 0.25));
    }
    const intenso = r.intensidad_Lh.map((v) => v > (resultado.intensidad_max_ok_Lh ?? 85));
    for (const [es, i, j] of tramosIguales(intenso)) {
      if (es) capas.plan.add(crearTubo(terreno, r.plan.slice(i, j + 1), COLORES.intenso, 0.32));
    }
    const c = r.plan[r.punto_critico];
    if (c) capas.plan.add(crearPin(terreno, c[0], c[1], COLORES.critico, 3));
  }

  const estado = (texto) => { $('vivo-info').textContent = texto; };
  const o2Traje = () => Number($('vivo-o2').value);

  /** Pide la ruta del modo actual y la dibuja (si nadie hizo otro clic mientras tanto). */
  async function calcular() {
    const id = ++peticion;
    estado('Calculando…');
    try {
      const r = modo === 'eva'
        ? await api('eva', puntos.length ? { habitat: puntos[0], prioridad, o2_L: o2Traje() }
          : { prioridad, o2_L: o2Traje() })
        : await api('libre', { inicio: puntos[0], fin: puntos[1], prioridad });
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

  /** Cambia a otra misión del frente ya calculado (ciencia, rápida, segura o equilibrada). */
  function aplicarPrioridad(nombre) {
    prioridad = nombre;
    const i = resultado?.nombradas?.[nombre];
    if (i === undefined) return;
    resultado = { ...resultado, ...resultado.frente[i], prioridad: nombre };
    dibujar();
    avisos.alCambiar(resultado);
  }
  $('vivo-prioridad').addEventListener('change', (e) => aplicarPrioridad(e.target.value));

  // O2 del traje: cambia el presupuesto de la EVA -> hay que volver a calcular
  $('vivo-o2').addEventListener('input', (e) => { $('vivo-o2-valor').textContent = `${e.target.value} L`; });
  $('vivo-o2').addEventListener('change', () => { if (modo === 'eva' && puntos.length) calcular(); });

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
