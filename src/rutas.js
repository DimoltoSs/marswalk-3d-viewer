import * as THREE from 'three';

const COLORES = {
  real: 0xffffff,      // ruta real de Perseverance
  plan: 0xff3b3b,      // tu plan A*
  objetivo: 0xffd23f,  // objetivos científicos
  inicio: 0x3dff6e,
  meta: 0xff3bd8,
};

/** Lee rutas.json (lo genera exportar_rutas.py). */
export async function cargarDatosRutas() {
  return (await fetch('/data/rutas.json')).json();
}

/** Un tubo 3D que sigue una lista de puntos [x, y] en metros, pegado al terreno. */
function crearTubo(terreno, xy, color, radio) {
  const puntos = xy.map(([x, y]) => terreno.aEscena(x, y, radio + 0.1));
  const curva = new THREE.CatmullRomCurve3(puntos, false, 'centripetal');
  const geometria = new THREE.TubeGeometry(curva, puntos.length * 4, radio, 8, false);
  return new THREE.Mesh(geometria, new THREE.MeshBasicMaterial({ color }));
}

/** Un marcador tipo "pin" (cono invertido + esfera) en (x, y) metros. */
function crearPin(terreno, x, y, color, alto = 3) {
  const pin = new THREE.Group();
  const material = new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.4 });
  const cono = new THREE.Mesh(new THREE.ConeGeometry(0.5, alto, 12), material);
  cono.rotation.x = Math.PI;          // punta hacia abajo
  cono.position.y = alto / 2;
  const bola = new THREE.Mesh(new THREE.SphereGeometry(0.8, 16, 12), material);
  bola.position.y = alto;
  pin.add(cono, bola);
  pin.position.copy(terreno.aEscena(x, y));
  pin.traverse((o) => { o.castShadow = true; });
  return pin;
}

/**
 * Crea todas las rutas y marcadores. Devuelve un objeto con:
 *  - grupo: lo que se agrega a la escena
 *  - capas: { real, plan, objetivos } para prender/apagar cada una
 *  - reconstruir(): vuelve a crearlas (p. ej. si cambia la exageración del terreno)
 */
export function crearRutas(terreno, datos) {
  const grupo = new THREE.Group();
  const capas = { real: new THREE.Group(), plan: new THREE.Group(), objetivos: new THREE.Group() };
  grupo.add(capas.real, capas.plan, capas.objetivos);

  function reconstruir() {
    // vaciar lo anterior (y liberar memoria de la GPU)
    for (const capa of Object.values(capas)) {
      capa.traverse((o) => { o.geometry?.dispose(); o.material?.dispose(); });
      capa.clear();
    }
    capas.real.add(crearTubo(terreno, datos.real, COLORES.real, 0.18));
    capas.plan.add(crearTubo(terreno, datos.plan, COLORES.plan, 0.25));
    capas.plan.add(crearPin(terreno, ...datos.inicio, COLORES.inicio));
    capas.plan.add(crearPin(terreno, ...datos.meta, COLORES.meta));
    for (const o of datos.objetivos) {
      capas.objetivos.add(crearPin(terreno, o.x, o.y, COLORES.objetivo, 4));
    }
  }
  reconstruir();

  return { grupo, capas, reconstruir };
}