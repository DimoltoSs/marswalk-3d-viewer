import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { crearEscena } from './escena.js';
import { cargarTerreno } from './terreno.js';
import { cargarDatosRutas, crearRutas } from './rutas.js';
import { cargarRover, crearRecorrido } from './rover.js';
import { crearInterfaz, aviso } from './interfaz.js';
import { crearSeleccion } from './seleccion.js';
import { mostrarMetricas } from './metricas.js';
import { cargarCapas } from './capas.js';
import { crearReplaneo } from './replaneo.js';

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
  let seguir = false;
  const opcionesRecorrido = { velocidad_m_s: 300 };
  const seleccion = crearSeleccion(camera, canvas, () => rutas?.capas.objetivos);

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

  /** (Re)inicia el rover: con replaneo sigue el plan con desvío; sin él, el plan original. */
  function arrancarRecorrido() {
    if (!rover || !datosRutas) return;
    const camino = conReplaneo ? replaneo.plan : datosRutas.plan;
    recorrido = crearRecorrido(terreno, rover, camino, opcionesRecorrido);
    recorrido.estado.pausado = !!opcionesRecorrido.pausado;
  }

  recalcularSombras();                          // ahora con rutas y pines

  // ---- 5. Panel de controles: qué hace cada control ----
  crearInterfaz({
    capa(nombre, visible) {
      if (rutas) rutas.capas[nombre].visible = visible;
    },
    exageracion(valor) {
      terreno.aplicarExageracion(valor);
      rutas?.reconstruir();                     // tubos y pines se vuelven a apoyar en el nuevo relieve
      replaneo?.reconstruir();
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
    async plan(archivo) {
      try {
        datosRutas = await cargarDatosRutas(archivo);
      } catch (err) {
        aviso(err.message);
        return;
      }
      mostrarMetricas(datosRutas);
      if (rutas) rutas.reconstruir(datosRutas);
      else { rutas = crearRutas(terreno, datosRutas); scene.add(rutas.grupo); }
      seleccion.refrescar();
      // El replaneo se calculó sobre el plan v2: con otro plan se apaga
      const caja = document.getElementById('replaneo');
      caja.disabled = !replaneo || archivo !== 'rutas_v2.json';
      if (caja.disabled && conReplaneo) {
        caja.checked = false;
        conReplaneo = false;
        replaneo.grupo.visible = false;
        document.getElementById('replaneo-info').textContent = 'Solo con el plan v2.';
      }
      arrancarRecorrido();
      recalcularSombras();
    },
  });
}

iniciar().catch((err) => {
  aviso(`Error inesperado: ${err.message}`);
  console.error(err);
});
