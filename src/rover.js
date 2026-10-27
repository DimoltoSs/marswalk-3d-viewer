import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { ESCALA_M } from './terreno.js';

/**
 * Carga el modelo .glb de Perseverance y lo prepara:
 * centrado, con las ruedas en y = 0 y a la escala de la escena.
 * escalaVisual: cuántas veces más grande que el real (a escala real mide ~0.03 unidades: invisible).
 */
export async function cargarRover({ url = '/modelos/perseverance.glb', escalaVisual = 60 } = {}) {
  const gltf = await new GLTFLoader().loadAsync(url);
  const modelo = gltf.scene;                       // el modelo viene en metros, con y hacia arriba

  // Centrar el modelo y apoyar las ruedas en el suelo (y = 0)
  const caja = new THREE.Box3().setFromObject(modelo);
  const centro = caja.getCenter(new THREE.Vector3());
  modelo.position.set(-centro.x, -caja.min.y, -centro.z);

  // Sin sombras en el rover: las sombras están "horneadas" (ver escena.js), así que una
  // sombra del rover se quedaría congelada en el inicio. Además ahorra dibujar 200k
  // triángulos extra en cada cuadro.
  modelo.traverse((o) => {
    if (o.isMesh) { o.castShadow = false; o.receiveShadow = false; }
  });

  // "Pivote": un grupo vacío que contiene al modelo. Movemos y giramos el pivote,
  // y el modelo (ya centrado dentro) lo sigue sin desacomodarse.
  const rover = new THREE.Group();
  rover.add(modelo);
  rover.scale.setScalar(escalaVisual / ESCALA_M); // metros -> unidades de escena, agrandado

  const tamano = caja.getSize(new THREE.Vector3());
  console.log(`Rover cargado: ${tamano.x.toFixed(1)} x ${tamano.y.toFixed(1)} x ${tamano.z.toFixed(1)} m`);
  return rover;
}

/**
 * Hace que el rover recorra una ruta [[x, y], ...] en metros, siguiendo el terreno.
 * Devuelve { actualizar(dt), pausado } para llamarlo desde el bucle de animación.
 */
export function crearRecorrido(terreno, rover, xy, { velocidad_m_s = 300, adelanto_m = 150 } = {}) {
  // Distancia acumulada en cada punto: permite ubicar "el punto a d metros del inicio"
  const acumulada = [0];
  for (let i = 1; i < xy.length; i++) {
    const [x0, y0] = xy[i - 1], [x1, y1] = xy[i];
    acumulada.push(acumulada[i - 1] + Math.hypot(x1 - x0, y1 - y0));
  }
  const largo = acumulada[acumulada.length - 1];

  /** Punto (x, y) en metros a una distancia d a lo largo de la ruta (interpolando entre puntos). */
  function puntoEn(d) {
    d = Math.min(Math.max(d, 0), largo);
    let i = 1;
    while (i < acumulada.length - 1 && acumulada[i] < d) i++;
    const t = (d - acumulada[i - 1]) / (acumulada[i] - acumulada[i - 1] || 1);
    const [x0, y0] = xy[i - 1], [x1, y1] = xy[i];
    return [x0 + (x1 - x0) * t, y0 + (y1 - y0) * t];
  }

  const estado = { distancia: 0, pausado: false };

  function colocar() {
    const [x, y] = puntoEn(estado.distancia);
    const [xa, ya] = puntoEn(estado.distancia + adelanto_m);   // un punto más adelante
    rover.position.copy(terreno.aEscena(x, y));
    rover.lookAt(terreno.aEscena(xa, ya));                     // mira hacia allá (y se inclina en las subidas)
  }

  function actualizar(dt) {
    if (!estado.pausado) {
      estado.distancia += velocidad_m_s * dt;
      if (estado.distancia > largo) estado.distancia = 0;      // al llegar, vuelve a empezar
    }
    colocar();
  }
  colocar();

  return { actualizar, estado, largo };
}