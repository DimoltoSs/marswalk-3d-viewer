import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { crearEscena } from './escena.js';
import { cargarTerreno } from './terreno.js';
import { cargarDatosRutas, crearRutas } from './rutas.js';
import { cargarRover, crearRecorrido } from './rover.js';
import { crearInterfaz, aviso } from './interfaz.js';
import { crearSeleccion } from './seleccion.js';
import { mostrarMetricas } from './metricas.js';

async function iniciar() {
  const canvas = document.getElementById('lienzo');
  const { renderer, scene, camera } = crearEscena(canvas);

  // Controles de ratón: arrastrar = girar, rueda = zoom, clic derecho = mover
  const controles = new OrbitControls(camera, canvas);
  controles.enableDamping = true;               // movimiento suave
  controles.maxPolarAngle = Math.PI * 0.48;     // no dejar que la cámara pase bajo el suelo
  controles.minDistance = 2;
  controles.maxDistance = 400;
  camera.position.set(40, 70, 90);              // vista inicial: centrada en la zona de las rutas
  controles.target.set(-25, 0, 0);

  // Lo que se va cargando. Si algo falla queda en null y el resto sigue funcionando.
  let terreno = null, rutas = null, rover = null, recorrido = null;
  let seguir = false;
  const opcionesRecorrido = { velocidad_m_s: 300 };
  const seleccion = crearSeleccion(camera, canvas, () => rutas?.capas.objetivos);

  // ---- Bucle de animación: arranca YA, aunque todavía no haya nada cargado ----
  const delta = new THREE.Vector3();
  let antes = performance.now();
  function animar(ahora) {
    const dt = Math.min((ahora - antes) / 1000, 0.1);   // tope: si la pestaña estuvo oculta
    antes = ahora;
    recorrido?.actualizar(dt);
    if (seguir && rover) {
      // mover cámara y objetivo lo mismo que se movió el rover: se conserva el ángulo de vista
      delta.subVectors(rover.position, controles.target);
      controles.target.add(delta);
      camera.position.add(delta);
    }
    controles.update();
    seleccion.actualizar();                     // la ficha del objetivo sigue a su pin
    renderer.render(scene, camera);
    requestAnimationFrame(animar);
  }
  requestAnimationFrame(animar);

  const recalcularSombras = () => { renderer.shadowMap.needsUpdate = true; };

  // ---- 1. Terreno (sin él no hay nada que mostrar) ----
  try {
    terreno = await cargarTerreno({
      exageracion: 3,
      anisotropia: renderer.capabilities.getMaxAnisotropy(),
    });
    scene.add(terreno.mesh);
    recalcularSombras();                        // primera sombra (el mapa de sombras debe existir antes de dibujar)
  } catch (err) {
    aviso(`No se pudo cargar el terreno: ${err.message}. ¿Corriste exportar_terrenos.py?`);
    return;
  }

  // ---- 2. Rutas ----
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

  // ---- 3. Rover ----
  try {
    rover = await cargarRover({ escalaVisual: 60 });
    scene.add(rover);
    if (datosRutas) recorrido = crearRecorrido(terreno, rover, datosRutas.plan, opcionesRecorrido);
  } catch (err) {
    aviso(`No se pudo cargar el rover (public/modelos/perseverance.glb).`);
    console.error(err);
  }

  recalcularSombras();                          // de nuevo, ya con rutas y pines

  // ---- 4. Panel de controles ----
  crearInterfaz({
    capa(nombre, visible) {
      if (rutas) rutas.capas[nombre].visible = visible;
    },
    exageracion(valor) {
      terreno.aplicarExageracion(valor);
      rutas?.reconstruir();                     // los tubos y pines se vuelven a pegar al suelo
      seleccion.refrescar();
      recalcularSombras();                      // el relieve cambió: hay que recalcular sombras
    },
    pausa(pausado) {
      if (recorrido) recorrido.estado.pausado = pausado;
      opcionesRecorrido.pausado = pausado;
    },
    velocidad(m_s) {
      if (recorrido) recorrido.estado.velocidad = m_s;
      opcionesRecorrido.velocidad_m_s = m_s;
    },
    seguir(activo) {
      seguir = activo && !!rover;
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
      seleccion.refrescar();                    // el plan cambió: se cierra la ficha
      if (rover) {
        recorrido = crearRecorrido(terreno, rover, datosRutas.plan, opcionesRecorrido);
        recorrido.estado.pausado = !!opcionesRecorrido.pausado;
      }
      recalcularSombras();                      // los pines cambiaron de lugar
    },
  });
}

iniciar().catch((err) => {
  aviso(`Error inesperado: ${err.message}`);
  console.error(err);
});
