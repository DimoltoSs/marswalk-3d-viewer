import * as THREE from 'three';
import { crearTubo } from './rutas.js';
import { ESCALA_M } from './terreno.js';

const COLORES = {
  peligro: 0xff8c1a,   // naranja: lo que vio el robot
  desvio: 0x2ee6ff,    // cian: la ruta que decidió el robot solo
};

/** Cilindro semitransparente, sin tapas, que marca el peligro sobre el terreno. */
function crearPeligro(terreno, { x, y, radio_m }) {
  const radio = radio_m / ESCALA_M;                 // 100 m -> 1 unidad de escena
  const alto = 1.5;
  const geometria = new THREE.CylinderGeometry(radio, radio, alto, 48, 1, true);
  const material = new THREE.MeshBasicMaterial({
    color: COLORES.peligro, transparent: true, opacity: 0.4,
    side: THREE.DoubleSide, depthWrite: false,      // se ve por dentro y no tapa las rutas
  });
  const cilindro = new THREE.Mesh(geometria, material);
  cilindro.position.copy(terreno.aEscena(x, y, alto / 2));
  return cilindro;
}

/**
 * Peligro + desvío de replaneo.json (exportar_replaneo.py).
 * Están ocultos hasta que el rover llega al punto de detección: antes, el robot no sabía nada.
 *  - actualizar(distancia_m): llamar en cada cuadro con la distancia recorrida por el rover
 *  - reconstruir(): volver a apoyarlo en el terreno al cambiar la exageración
 */
export function crearReplaneo(terreno, datos) {
  const grupo = new THREE.Group();
  grupo.visible = false;
  const info = document.getElementById('replaneo-info');

  function reconstruir() {
    grupo.traverse((o) => { o.geometry?.dispose(); o.material?.dispose(); });
    grupo.clear();
    grupo.add(crearPeligro(terreno, datos.peligro));
    grupo.add(crearTubo(terreno, datos.desvio, COLORES.desvio, 0.3));
  }
  reconstruir();

  const m = datos.metricas;
  const textoDetectado = `Peligro detectado a ${(datos.deteccion.d_m / 1000).toFixed(2)} km. `
    + `Desvío autónomo: ${m.m_original} m → ${m.m_desvio} m (+${m.extra_pct} %).`;

  function actualizar(distancia_m) {
    const detectado = distancia_m >= datos.deteccion.d_m;
    if (detectado === grupo.visible) return;        // solo actuar cuando cambia
    grupo.visible = detectado;
    if (info) info.textContent = detectado ? textoDetectado : 'Siguiendo el plan enviado desde la Tierra…';
  }

  return { grupo, actualizar, reconstruir, plan: datos.plan };
}
