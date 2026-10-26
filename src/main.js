import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { crearEscena } from './escena.js';
import { cargarTerreno } from './terreno.js';
import { cargarDatosRutas, crearRutas } from './rutas.js';
import { cargarRover, crearRecorrido } from './rover.js';

async function iniciar() {
  const canvas = document.getElementById('lienzo');
  const { renderer, scene, camera } = crearEscena(canvas);

  // Controles de ratón: arrastrar = girar, rueda = zoom, clic derecho = mover
  const controles = new OrbitControls(camera, canvas);
  controles.enableDamping = true;               // movimiento suave
  controles.maxPolarAngle = Math.PI * 0.48;     // no dejar que la cámara pase bajo el suelo
  controles.minDistance = 2;
  controles.maxDistance = 400;

  const terreno = await cargarTerreno({
    exageracion: 3,
    anisotropia: renderer.capabilities.getMaxAnisotropy(),
  });
  scene.add(terreno.mesh);

  const datosRutas = await cargarDatosRutas();
  const rutas = crearRutas(terreno, datosRutas);
  scene.add(rutas.grupo);

  const rover = await cargarRover({ escalaVisual: 60 });
  scene.add(rover);
  const recorrido = crearRecorrido(terreno, rover, datosRutas.plan, { velocidad_m_s: 300 });

  camera.position.set(40, 70, 90);              // vista inicial: centrada en la zona de las rutas
  controles.target.set(-25, 0, 0);

  // Bucle: dt = segundos desde el cuadro anterior (para que la velocidad no dependa de los FPS)
  let antes = performance.now();
  function animar(ahora) {
    const dt = Math.min((ahora - antes) / 1000, 0.1);   // tope: si la pestaña estuvo oculta
    antes = ahora;
    recorrido.actualizar(dt);
    controles.update();
    renderer.render(scene, camera);
    requestAnimationFrame(animar);
  }
  requestAnimationFrame(animar);
}

iniciar().catch((err) => console.error('No se pudo iniciar el visor:', err));