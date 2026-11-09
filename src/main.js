import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { crearEscena } from './escena.js';
import { cargarTerreno } from './terreno.js';
import { cargarDatosRutas, crearRutas } from './rutas.js';
import { cargarRover, crearRecorrido } from './rover.js';
import { crearInterfaz, aviso } from './interfaz.js';
import { crearSeleccion } from './seleccion.js';
import { mostrarMetricas, mostrarMetricasVivo } from './metricas.js';
import { cargarCapas } from './capas.js';
import { crearReplaneo } from './replaneo.js';
import { crearPlanificador } from './planificador.js';

async function iniciar() {
  const canvas = document.getElementById('lienzo');
  const { renderer, scene, camera } = crearEscena(canvas);

  // Ratón: arrastrar = girar, rueda = zoom, clic derecho = desplazar
  const controles = new OrbitControls(camera, canvas);
  controles.enableDamping = true;
  controles.maxPolarAngle = Math.PI * 0.48;     // la cámara no baja del horizonte
  controles.minDistance = 2;
  controles.maxDistance = 400;
  camera.position.set(40, 70, 90);              // vista inicial sobre la zona de las rutas
  controles.target.set(-25, 0, 0);

  // Cada parte se carga por separado: si una falla queda en null y el resto sigue funcionando.
  let terreno = null, rutas = null, rover = null, recorrido = null, capas = null;
  let replaneo = null, conReplaneo = false;   // peligro simulado y desvío autónomo
  let planificador = null;                     // misión libre y EVA (servidor.py)
  let modo = 'rutas_v2.json';                  // valor del selector de misión
  const esVivo = () => modo === 'libre' || modo === 'eva';
  let seguir = false;
  const opcionesRecorrido = { velocidad_m_s: 300 };
  const seleccion = crearSeleccion(camera, canvas,
    () => (esVivo() ? planificador?.capas.objetivos : rutas?.capas.objetivos));

  // ---- Bucle de animación: arranca antes de cargar los datos ----
  const delta = new THREE.Vector3();
  let antes = performance.now();
  function animar(ahora) {
    const dt = Math.min((ahora - antes) / 1000, 0.1);   // tope por si la pestaña estuvo en segundo plano
    antes = ahora;
    recorrido?.actualizar(dt);
    if (conReplaneo) replaneo?.actualizar(recorrido?.estado.distancia ?? 0);
    if (seguir && rover) {
      // Desplazar cámara y objetivo lo mismo que el rover: se conserva el ángulo de vista
      delta.subVectors(rover.position, controles.target);
      controles.target.add(delta);
      camera.position.add(delta);
    }
    controles.update();
    seleccion.actualizar();
    renderer.render(scene, camera);
    requestAnimationFrame(animar);
  }
  requestAnimationFrame(animar);

  // Las sombras están precalculadas (escena.js): se regeneran solo cuando algo cambia
  const recalcularSombras = () => { renderer.shadowMap.needsUpdate = true; };

  // ---- 1. Terreno (obligatorio) ----
  try {
    terreno = await cargarTerreno({
      exageracion: 3,
      anisotropia: renderer.capabilities.getMaxAnisotropy(),
    });
    scene.add(terreno.mesh);
    recalcularSombras();                        // el mapa de sombras debe existir antes del primer cuadro
  } catch (err) {
    aviso(`No se pudo cargar el terreno: ${err.message} (se genera con exportar_terrenos.py)`);
    return;
  }

  // ---- 2. Capas sobre el terreno: CRISM y costos (opcionales) ----
  try {
    capas = await cargarCapas(terreno, renderer.capabilities.getMaxAnisotropy());
    scene.add(capas.mesh);
  } catch (err) {
    aviso(err.message);
    document.getElementById('capa').disabled = true;
  }

  // ---- 3. Rutas y métricas ----
  let datosRutas = null;
  try {
    datosRutas = await cargarDatosRutas('rutas_v2.json');
    rutas = crearRutas(terreno, datosRutas);
    scene.add(rutas.grupo);
    mostrarMetricas(datosRutas);
  } catch (err) {
    aviso(`${err.message}. Se muestra solo el terreno.`);
    mostrarMetricas(null);
  }

  // ---- 4. Rover ----
  try {
    rover = await cargarRover({ escalaVisual: 60 });
    scene.add(rover);
    if (datosRutas) recorrido = crearRecorrido(terreno, rover, datosRutas.plan, opcionesRecorrido);
  } catch (err) {
    aviso(`No se pudo cargar el rover (public/modelos/perseverance.glb).`);
    console.error(err);
  }

  // ---- 4b. Replaneo: peligro simulado y desvío (opcional) ----
  try {
    replaneo = crearReplaneo(terreno, await cargarDatosRutas('replaneo.json'));
    scene.add(replaneo.grupo);
  } catch (err) {
    aviso(`${err.message} (se genera con exportar_replaneo.py)`);
    document.getElementById('replaneo').disabled = true;
  }

  /** (Re)inicia el rover sobre `camino` (null = sin ruta: se oculta).
   *  Por defecto: en vivo, nada hasta que haya ruta; si no, el plan con desvío o el original. */
  function arrancarRecorrido(camino = esVivo() ? null : (conReplaneo ? replaneo.plan : datosRutas?.plan)) {
    if (!rover) return;
    rover.visible = !!camino;
    recorrido = camino ? crearRecorrido(terreno, rover, camino, opcionesRecorrido) : null;
    if (recorrido) recorrido.estado.pausado = !!opcionesRecorrido.pausado;
  }

  /** Apaga el peligro simulado y su casilla. */
  function apagarReplaneo() {
    document.getElementById('replaneo').checked = false;
    conReplaneo = false;
    if (replaneo) replaneo.grupo.visible = false;
    document.getElementById('replaneo-info').textContent = 'Solo con el plan v2.';
  }

  /** Qué se ve: las casillas de "Capas" aplican a la misión activa (precalculada o en vivo). */
  const casilla = (nombre) => document.querySelector(`[data-capa="${nombre}"]`).checked;
  function aplicarCapas() {
    const vivo = esVivo();
    if (rutas) {
      rutas.capas.real.visible = casilla('real');
      rutas.capas.plan.visible = !vivo && casilla('plan');
      rutas.capas.objetivos.visible = !vivo && casilla('objetivos');
    }
    planificador.grupo.visible = vivo;
    planificador.capas.plan.visible = casilla('plan');
    planificador.capas.objetivos.visible = casilla('objetivos');
  }

  /** Secciones del panel que solo aplican a ciertos modos (atributo data-modos en index.html). */
  function mostrarSecciones() {
    for (const s of document.querySelectorAll('[data-modos]')) {
      s.hidden = !s.dataset.modos.split(' ').includes(modo);
    }
  }

  // ---- 4c. Planificador en vivo (necesita servidor.py) ----
  planificador = crearPlanificador(terreno, camera, canvas, {
    alCambiar(resultado) {                      // hay ruta nueva, o se borró
      if (!esVivo()) return;
      mostrarMetricasVivo(modo, resultado);
      arrancarRecorrido(resultado?.plan ?? null);
      seleccion.refrescar();
      recalcularSombras();
    },
  });
  scene.add(planificador.grupo);
  mostrarSecciones();
  aplicarCapas();

  recalcularSombras();                          // ahora con rutas y pines

  // ---- 5. Panel de controles: qué hace cada control ----
  crearInterfaz({
    capa() {
      aplicarCapas();
    },
    exageracion(valor) {
      terreno.aplicarExageracion(valor);
      rutas?.reconstruir();                     // tubos y pines se vuelven a apoyar en el nuevo relieve
      replaneo?.reconstruir();
      planificador.reconstruir();
      seleccion.refrescar();
      recalcularSombras();
    },
    pausa(pausado) {
      if (recorrido) recorrido.estado.pausado = pausado;
      opcionesRecorrido.pausado = pausado;      // se conserva si se cambia de plan
    },
    velocidad(m_s) {
      if (recorrido) recorrido.estado.velocidad = m_s;
      opcionesRecorrido.velocidad_m_s = m_s;
    },
    seguir(activo) {
      seguir = activo && !!rover;
    },
    async capaTerreno(nombre) {
      try {
        await capas?.mostrar(nombre);
      } catch (err) {
        aviso(`No se pudo cargar la capa "${nombre}": ${err.message}`);
      }
    },
    opacidadCapa(valor) {
      capas?.opacidad(valor);
    },
    replaneo(activo) {
      conReplaneo = activo && !!replaneo;
      if (replaneo) replaneo.grupo.visible = false;
      document.getElementById('replaneo-info').textContent = conReplaneo
        ? 'Siguiendo el plan enviado desde la Tierra…' : 'Solo con el plan v2.';
      arrancarRecorrido();                      // el rover vuelve al inicio para ver la detección
    },
    async plan(valor) {
      modo = valor;
      mostrarSecciones();
      if (modo !== 'rutas_v2.json') apagarReplaneo();   // el peligro simulado es sobre el plan v2
      if (esVivo()) {
        planificador.cambiarModo(modo);         // mapa limpio, a esperar clics
      } else {
        planificador.cambiarModo(null);
        try {
          datosRutas = await cargarDatosRutas(modo);
        } catch (err) {
          aviso(err.message);
          return;
        }
        mostrarMetricas(datosRutas);
        if (rutas) rutas.reconstruir(datosRutas);
        else { rutas = crearRutas(terreno, datosRutas); scene.add(rutas.grupo); }
        arrancarRecorrido();
      }
      aplicarCapas();
      seleccion.refrescar();
      recalcularSombras();
    },
  });
}

iniciar().catch((err) => {
  aviso(`Error inesperado: ${err.message}`);
  console.error(err);
});
