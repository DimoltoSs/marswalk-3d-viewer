import * as THREE from 'three';

const COLORES = {
  real: 0xffffff,      // ruta real de Perseverance
  plan: 0xff3b3b,      // nuestro plan
  objetivo: 0xffd23f,  // objetivos científicos
  inicio: 0x3dff6e,
  meta: 0xff3bd8,
};

/**
 * Lee un archivo de rutas de public/data/:
 *  - rutas_v2.json: misión del notebook planificador_v2 (por defecto)
 *  - rutas.json:    plan v1 de prototipo_uno (exportar_rutas.py)
 */
export async function cargarDatosRutas(archivo = 'rutas_v2.json') {
  const resp = await fetch(`/data/${archivo}`);
  // Si el archivo no existe, Vite responde 200 con index.html: hay que revisar el tipo
  const esJson = resp.headers.get('content-type')?.includes('json');
  if (!resp.ok || !esJson) throw new Error(`No se encontró /data/${archivo}`);
  return resp.json();
}

/** Tubo 3D que sigue una lista de puntos [x, y] en metros, apoyado en el terreno. */
export function crearTubo(terreno, xy, color, radio) {
  const puntos = xy.map(([x, y]) => terreno.aEscena(x, y, radio + 0.1));
  const curva = new THREE.CatmullRomCurve3(puntos, false, 'centripetal');   // centrípeta: sin bucles en curvas cerradas
  const geometria = new THREE.TubeGeometry(curva, puntos.length * 4, radio, 8, false);
  return new THREE.Mesh(geometria, new THREE.MeshBasicMaterial({ color }));
}

/** Marcador tipo pin (cono invertido + esfera) en (x, y) metros. */
export function crearPin(terreno, x, y, color, alto = 3) {
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
 * Crea las rutas y marcadores. Devuelve:
 *  - grupo: lo que se agrega a la escena
 *  - capas: { real, plan, objetivos }, para mostrar u ocultar cada una
 *  - reconstruir(nuevosDatos?): las vuelve a crear al cambiar la exageración o el plan
 */
export function crearRutas(terreno, datos) {
  const grupo = new THREE.Group();
  const capas = { real: new THREE.Group(), plan: new THREE.Group(), objetivos: new THREE.Group() };
  grupo.add(capas.real, capas.plan, capas.objetivos);

  function reconstruir(nuevosDatos) {
    if (nuevosDatos) datos = nuevosDatos;
    // Liberar la memoria de GPU de lo anterior antes de crear lo nuevo
    for (const capa of Object.values(capas)) {
      capa.traverse((o) => { o.geometry?.dispose(); o.material?.dispose(); });
      capa.clear();
    }
    capas.real.add(crearTubo(terreno, datos.real, COLORES.real, 0.18));
    capas.plan.add(crearTubo(terreno, datos.plan, COLORES.plan, 0.25));
    capas.plan.add(crearPin(terreno, ...datos.inicio, COLORES.inicio));
    capas.plan.add(crearPin(terreno, ...datos.meta, COLORES.meta));
    for (const o of datos.objetivos) {
      const pin = crearPin(terreno, o.x, o.y, COLORES.objetivo, 4);
      pin.userData.objetivo = o;      // lo usa seleccion.js para la ficha
      capas.objetivos.add(pin);
    }
  }
  reconstruir();

  return { grupo, capas, reconstruir };
}
