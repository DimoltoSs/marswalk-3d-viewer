import * as THREE from 'three';

/**
 * Clic sobre un pin de objetivo -> ficha con sus datos, anclada al pin en pantalla.
 *
 * obtenerGrupo() devuelve el grupo de pines (rutas.capas.objetivos). Es una función
 * porque las rutas pueden cargarse después o reconstruirse.
 * Los datos de cada pin están en pin.userData.objetivo (los asigna rutas.js).
 */
export function crearSeleccion(camera, canvas, obtenerGrupo) {
  const ficha = document.getElementById('ficha');
  const raycaster = new THREE.Raycaster();
  const raton = new THREE.Vector2();
  const arriba = new THREE.Vector3();
  let elegido = null;

  /** Pin bajo el ratón, o null. */
  function pinEn(evento) {
    const grupo = obtenerGrupo();
    if (!grupo || !grupo.visible) return null;
    // Píxeles -> coordenadas normalizadas (-1..1) que usa el raycaster
    const caja = canvas.getBoundingClientRect();
    raton.x = ((evento.clientX - caja.left) / caja.width) * 2 - 1;
    raton.y = -((evento.clientY - caja.top) / caja.height) * 2 + 1;
    raycaster.setFromCamera(raton, camera);
    const toque = raycaster.intersectObjects(grupo.children, true)[0];
    // El rayo toca el cono o la esfera: se sube hasta el grupo del pin, que guarda los datos
    let o = toque?.object;
    while (o && !o.userData.objetivo) o = o.parent;
    return o ?? null;
  }

  function resaltar(pin, encendido) {
    pin.scale.setScalar(encendido ? 1.4 : 1);
    pin.traverse((m) => { if (m.material) m.material.emissiveIntensity = encendido ? 1.2 : 0.4; });
  }

  function elegir(pin) {
    if (elegido) resaltar(elegido, false);
    elegido = pin;
    if (!pin) { ficha.hidden = true; return; }
    resaltar(pin, true);
    const o = pin.userData.objetivo;
    // El plan v2 trae "ciencia" (0..1); el v1, "puntaje"
    const valor = o.ciencia !== undefined
      ? `<tr><td>Ciencia</td><td>${o.ciencia.toFixed(2)}</td></tr>`
      : `<tr><td>Puntaje</td><td>${o.puntaje}</td></tr>`;
    ficha.innerHTML = `
      <b>Parada ${o.parada} · ${o.mineral}</b>
      <table>
        <tr><td>Área</td><td>${o.area_ha} ha</td></tr>
        ${valor}
        <tr><td>Posición</td><td>${(o.x / 1000).toFixed(2)}, ${(o.y / 1000).toFixed(2)} km</td></tr>
      </table>`;
    ficha.hidden = false;
  }

  // Clic vs. arrastre: si el ratón se movió más de 5 px, se estaba girando la cámara
  let inicio = null;
  canvas.addEventListener('pointerdown', (e) => { inicio = [e.clientX, e.clientY]; });
  canvas.addEventListener('pointerup', (e) => {
    if (!inicio || Math.hypot(e.clientX - inicio[0], e.clientY - inicio[1]) > 5) return;
    elegir(pinEn(e));                           // clic fuera de un pin = cerrar la ficha
  });
  // Cursor de mano sobre los pines
  canvas.addEventListener('pointermove', (e) => {
    if (e.buttons) return;                      // no mientras se arrastra
    canvas.style.cursor = pinEn(e) ? 'pointer' : '';
  });

  /** En cada cuadro: proyecta el pin a pantalla y mueve la ficha con él. */
  function actualizar() {
    if (!elegido) return;
    elegido.getWorldPosition(arriba);
    arriba.y += 5.5;                            // justo encima de la esfera del pin
    arriba.project(camera);                     // x, y en -1..1; z > 1 = detrás de la cámara
    const visible = arriba.z < 1 && elegido.parent?.visible;
    ficha.style.display = visible ? '' : 'none';
    ficha.style.left = `${(arriba.x + 1) / 2 * canvas.clientWidth}px`;
    ficha.style.top = `${(1 - arriba.y) / 2 * canvas.clientHeight}px`;
  }

  /**
   * Tras rutas.reconstruir() los pines son nuevos. Si el mismo objetivo sigue existiendo
   * (cambió solo la exageración) se vuelve a seleccionar; si cambió el plan, se cierra la ficha.
   */
  function refrescar() {
    const o = elegido?.userData.objetivo;
    elegido = null;
    const nuevo = obtenerGrupo()?.children.find((p) => p.userData.objetivo === o);
    elegir(nuevo ?? null);
  }

  return { actualizar, refrescar };
}
