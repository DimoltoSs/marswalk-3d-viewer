import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { ESCALA_M } from './terreno.js';

/**
 * Carga el modelo de Perseverance (NASA/JPL), centrado y con las ruedas en y = 0.
 * escalaVisual: factor de agrandamiento; a escala real mediría menos de un píxel.
 */
export async function cargarRover({ url = '/modelos/perseverance.glb', escalaVisual = 60 } = {}) {
  const gltf = await new GLTFLoader().loadAsync(url);
  const modelo = gltf.scene;                       // en metros, y hacia arriba

  const caja = new THREE.Box3().setFromObject(modelo);
  const centro = caja.getCenter(new THREE.Vector3());
  modelo.position.set(-centro.x, -caja.min.y, -centro.z);

  // Sin sombras: con el mapa de sombras precalculado, la sombra del rover se quedaría
  // fija en el inicio. También evita dibujar sus ~200k triángulos una vez más por cuadro.
  modelo.traverse((o) => {
    if (o.isMesh) { o.castShadow = false; o.receiveShadow = false; }
  });

  // Pivote: se mueve y gira el grupo, y el modelo centrado dentro lo sigue.
  const rover = new THREE.Group();
  rover.add(modelo);
  rover.scale.setScalar(escalaVisual / ESCALA_M);

  const tamano = caja.getSize(new THREE.Vector3());
  console.log(`Rover cargado: ${tamano.x.toFixed(1)} x ${tamano.y.toFixed(1)} x ${tamano.z.toFixed(1)} m`);
  return rover;
}

/**
 * Mueve el rover a lo largo de una ruta [[x, y], ...] en metros, pegado al terreno.
 * estado.pausado y estado.velocidad (m simulados por segundo real) se pueden cambiar en vivo.
 */
export function crearRecorrido(terreno, rover, xy, { velocidad_m_s = 300, adelanto_m = 150 } = {}) {
  // Distancia acumulada en cada punto, para ubicar "el punto a d metros del inicio"
  const acumulada = [0];
  for (let i = 1; i < xy.length; i++) {
    const [x0, y0] = xy[i - 1], [x1, y1] = xy[i];
    acumulada.push(acumulada[i - 1] + Math.hypot(x1 - x0, y1 - y0));
  }
  const largo = acumulada[acumulada.length - 1];

  /** Punto (x, y) a d metros del inicio, interpolando entre los puntos de la ruta. */
  function puntoEn(d) {
    d = Math.min(Math.max(d, 0), largo);
    let i = 1;
    while (i < acumulada.length - 1 && acumulada[i] < d) i++;
    const t = (d - acumulada[i - 1]) / (acumulada[i] - acumulada[i - 1] || 1);
    const [x0, y0] = xy[i - 1], [x1, y1] = xy[i];
    return [x0 + (x1 - x0) * t, y0 + (y1 - y0) * t];
  }

  const estado = { distancia: 0, pausado: false, velocidad: velocidad_m_s };

  function colocar() {
    const [x, y] = puntoEn(estado.distancia);
    const [xa, ya] = puntoEn(estado.distancia + adelanto_m);
    rover.position.copy(terreno.aEscena(x, y));
    rover.lookAt(terreno.aEscena(xa, ya));                     // mirar un punto adelante: orienta e inclina en pendientes
  }

  function actualizar(dt) {
    if (!estado.pausado) {
      estado.distancia += estado.velocidad * dt;
      if (estado.distancia > largo) estado.distancia = 0;      // reinicia al llegar a la meta
    }
    colocar();
  }
  colocar();

  return { actualizar, estado, largo };
}
