import * as THREE from 'three';
import { crearPin, crearTubo } from './rutas.js';
import { ESCALA_M } from './terreno.js';
import { conSitio } from './sitio.js';

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
  rescateOk: 0x3ddc84, rescateJusto: 0xffd23f, rescateNo: 0xff3b3b,   // margen si uno se lesiona: >50 L, 0-50 L, <0
  senal: 0x2ee6ff, sinSenal: 0xff3b3b,                               // radio con el hábitat
  sol: 0xffe066, sombra: 0x3a4a9c, noche: 0x111111,                   // luz a la hora en que se pasa por ahí
};

/** Cómo se colorea la ruta de la EVA y qué dice la leyenda. */
const MODOS_COLOR = {
  o2: {
    color: (r, i) => { const p = r.tanque_pct[i]; return p > 25 ? COLORES.o2Sobra : p >= 15 ? COLORES.o2Justo : COLORES.o2Poco; },
    leyenda: [['#3ddc84', '> 25 %'], ['#ffd23f', '15–25 %'], ['#ff3b3b', '10–15 % de O₂ (el peor de los dos)'],
      ['#b45cff', 'esfuerzo alto'], ['#ff8c1a', 'punto más comprometido']],
  },
  rescate: {
    color: (r, i) => { const m = r.margen_rescate_L[i]; return m > 50 ? COLORES.rescateOk : m >= 0 ? COLORES.rescateJusto : COLORES.rescateNo; },
    leyenda: [['#3ddc84', 'sobran > 50 L'], ['#ffd23f', '0–50 L'], ['#ff3b3b', 'no alcanzan a volver si uno se lesiona']],
  },
  radio: {
    color: (r, i) => (r.senal[i] ? COLORES.senal : COLORES.sinSenal),
    leyenda: [['#2ee6ff', 'con señal del hábitat'], ['#ff3b3b', 'sin señal (el relieve tapa la antena)']],
  },
  luz: {
    color: (r, i) => (r.hora_solar[i] < (r.luz?.amanecer ?? 0) || r.hora_solar[i] > (r.luz?.ocaso ?? 24)
      ? COLORES.noche : r.sombra[i] ? COLORES.sombra : COLORES.sol),
    leyenda: [['#ffe066', 'al sol'], ['#3a4a9c', 'en sombra del relieve'], ['#111111', 'de noche']],
  },
};
const horaTexto = (h) => `${Math.floor(h)}:${String(Math.round((h % 1) * 60)).padStart(2, '0')}`;

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
  eva: 'Pareja de astronautas: un clic = hábitat. Aparece el radio de 3 km y la mejor salida de ida y vuelta '
    + 'que cabe en el oxígeno de los dos, en 8 h y en la luz del día. Otro clic lo mueve. Arrastrar = mover la vista.',
};
const BOTON_AUTO = { libre: 'Puntos aleatorios', eva: 'Mejor centroide' };

/** Pide algo al servidor. Sin cuerpo = GET; con cuerpo = POST con JSON. */
async function api(ruta, cuerpo) {
  const opciones = cuerpo === undefined ? {} : {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cuerpo),
  };
  const resp = await fetch(conSitio(`/api/${ruta}`), opciones);
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

  /** EVA: la ruta se colorea según el selector (oxígeno, rescate, radio o luz).
   *  Con "oxígeno", además, los tramos de esfuerzo alto y el punto más comprometido. */
  function dibujarEva(r) {
    const modoColor = MODOS_COLOR[$('eva-color').value] ?? MODOS_COLOR.o2;
    const nivel = r.plan.slice(0, -1).map((_, i) => modoColor.color(r, i));
    for (const [color, i, j] of tramosIguales(nivel)) {
      capas.plan.add(crearTubo(terreno, r.plan.slice(i, j + 1), color, 0.25));
    }
    if ($('eva-color').value === 'rescate' && r.sin_rescate != null) {
      const p = r.plan[r.sin_rescate];
      capas.plan.add(crearPin(terreno, p[0], p[1], COLORES.rescateNo, 3));
    }
    if ($('eva-color').value !== 'o2') return;
    const intenso = r.intensidad_Lh.map((v) => v > (resultado.intensidad_max_ok_Lh ?? 85));
    for (const [es, i, j] of tramosIguales(intenso)) {
      if (es) capas.plan.add(crearTubo(terreno, r.plan.slice(i, j + 1), COLORES.intenso, 0.32));
    }
    const c = r.plan[r.punto_critico];
    if (c) capas.plan.add(crearPin(terreno, c[0], c[1], COLORES.critico, 3));
  }

  const estado = (texto) => { $('vivo-info').textContent = texto; };

  /** Lo que se manda al servidor en una EVA: pareja, radio y luz. */
  function cuerpoEva() {
    const persona = (l) => ({ masa_kg: Number($(`eva-masa-${l}`).value) || 75, o2_L: Number($(`eva-o2-${l}`).value) });
    return {
      prioridad,
      pareja: [persona('a'), persona('b')],
      evitar_sin_senal: $('eva-radio').checked,
      fecha: $('eva-fecha').value || null,
      hora_salida: Number($('eva-hora').value),
    };
  }

  function dibujarLeyenda() {
    const m = MODOS_COLOR[$('eva-color').value] ?? MODOS_COLOR.o2;
    $('eva-leyenda').innerHTML = m.leyenda
      .map(([c, t]) => `<label><span class="muestra" style="background:${c}"></span> ${t}</label>`).join('');
  }

  /** Pide la ruta del modo actual y la dibuja (si nadie hizo otro clic mientras tanto). */
  async function calcular() {
    const id = ++peticion;
    estado('Calculando…');
    try {
      const r = modo === 'eva'
        ? await api('eva', puntos.length ? { habitat: puntos[0], ...cuerpoEva() } : cuerpoEva())
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

  // Controles de la EVA: cualquiera cambia el problema -> volver a calcular (si ya hay hábitat)
  const recalcularEva = () => { if (modo === 'eva' && puntos.length) calcular(); };
  for (const l of ['a', 'b']) {
    $(`eva-o2-${l}`).addEventListener('input', (e) => { $(`eva-o2-${l}-valor`).textContent = `${e.target.value} L`; });
    $(`eva-o2-${l}`).addEventListener('change', recalcularEva);
    $(`eva-masa-${l}`).addEventListener('change', recalcularEva);
  }
  $('eva-hora').addEventListener('input', (e) => { $('eva-hora-valor').textContent = horaTexto(Number(e.target.value)); });
  for (const id of ['eva-hora', 'eva-radio', 'eva-fecha']) $(id).addEventListener('change', recalcularEva);
  $('eva-fecha').value = new Date().toISOString().slice(0, 10);
  // Cambiar el color no recalcula: solo se vuelve a dibujar
  $('eva-color').addEventListener('change', () => { dibujarLeyenda(); dibujar(); });
  dibujarLeyenda();

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
