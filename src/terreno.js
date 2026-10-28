import * as THREE from 'three';

// Escala de la escena: 1 unidad = 100 m (el mapa de 20 km mide 200 unidades).
export const ESCALA_M = 100;

/**
 * Construye la malla 3D del terreno a partir de dem.bin + meta.json (exportar_terrenos.py).
 * Devuelve la malla y utilidades para que otros módulos ubiquen cosas sobre el relieve.
 */
export async function cargarTerreno({ exageracion = 3, anisotropia = 1 } = {}) {
  // ---- 1. Datos ----
  const meta = await (await fetch('/data/meta.json')).json();
  const buffer = await (await fetch('/data/dem.bin')).arrayBuffer();
  const elev = new Float32Array(buffer);          // n × n alturas en metros, fila 0 = Norte
  const n = meta.n;
  if (elev.length !== n * n) {
    throw new Error(`dem.bin trae ${elev.length} valores, se esperaban ${n * n}`);
  }

  let suma = 0;
  for (const z of elev) suma += z;
  const elevMedia = suma / elev.length;           // se usa como y = 0 para centrar el relieve
  const lado = meta.extension_m / ESCALA_M;

  // ---- 2. Vértices y UV: uno por celda del DEM ----
  const posiciones = new Float32Array(n * n * 3);
  const uvs = new Float32Array(n * n * 2);
  for (let i = 0; i < n; i++) {                   // fila: Norte -> Sur  (z de la escena)
    for (let j = 0; j < n; j++) {                 // columna: Oeste -> Este (x de la escena)
      const k = i * n + j;
      posiciones[k * 3] = -lado / 2 + (lado * j) / (n - 1);
      posiciones[k * 3 + 2] = -lado / 2 + (lado * i) / (n - 1);
      // la altura (y) la pone aplicarExageracion()
      uvs[k * 2] = j / (n - 1);
      uvs[k * 2 + 1] = 1 - i / (n - 1);           // v = 1 arriba de la imagen = Norte
    }
  }

  // ---- 3. Triángulos: dos por cada cuadro de 4 vértices ----
  const indices = new Uint32Array((n - 1) * (n - 1) * 6);
  let t = 0;
  for (let i = 0; i < n - 1; i++) {
    for (let j = 0; j < n - 1; j++) {
      const a = i * n + j, b = a + 1, c = a + n, d = c + 1;
      indices.set([a, c, b, b, c, d], t);
      t += 6;
    }
  }

  const geometria = new THREE.BufferGeometry();
  geometria.setAttribute('position', new THREE.BufferAttribute(posiciones, 3));
  geometria.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
  geometria.setIndex(new THREE.BufferAttribute(indices, 1));

  // ---- 4. Alturas: se puede volver a llamar para cambiar la exageración en vivo ----
  function aplicarExageracion(ex) {
    exageracion = ex;
    for (let k = 0; k < n * n; k++) {
      posiciones[k * 3 + 1] = ((elev[k] - elevMedia) * ex) / ESCALA_M;
    }
    geometria.attributes.position.needsUpdate = true;
    geometria.computeVertexNormals();   // las normales definen el sombreado del relieve
    geometria.computeBoundingSphere();
  }
  aplicarExageracion(exageracion);

  // ---- 5. Textura CTX y material ----
  const textura = await new THREE.TextureLoader().loadAsync('/data/textura.jpg');
  textura.colorSpace = THREE.SRGBColorSpace;      // sin esto la imagen se ve deslavada
  textura.anisotropy = anisotropia;               // nitidez en vistas rasantes

  const material = new THREE.MeshStandardMaterial({
    map: textura,
    roughness: 1,      // polvo mate, sin brillos
    metalness: 0,
  });
  const mesh = new THREE.Mesh(geometria, material);
  mesh.castShadow = true;      // el relieve se sombrea a sí mismo
  mesh.receiveShadow = true;

  // ---- 6. Utilidades para otros módulos ----
  /** Altura en metros en (x Este, y Norte), con interpolación bilineal entre celdas. */
  function alturaEn(xm, ym) {
    const fx = ((xm + meta.extension_m / 2) / meta.extension_m) * (n - 1);
    const fy = ((meta.extension_m / 2 - ym) / meta.extension_m) * (n - 1);
    const j = Math.min(n - 2, Math.max(0, Math.floor(fx)));
    const i = Math.min(n - 2, Math.max(0, Math.floor(fy)));
    const tx = fx - j, ty = fy - i;
    const z00 = elev[i * n + j], z01 = elev[i * n + j + 1];
    const z10 = elev[(i + 1) * n + j], z11 = elev[(i + 1) * n + j + 1];
    return (z00 * (1 - tx) + z01 * tx) * (1 - ty) + (z10 * (1 - tx) + z11 * tx) * ty;
  }

  /** Metros locales (x Este, y Norte) -> punto de la escena apoyado en el terreno. */
  function aEscena(xm, ym, sobreSuelo = 0) {
    const y = ((alturaEn(xm, ym) - elevMedia) * exageracion) / ESCALA_M;
    return new THREE.Vector3(xm / ESCALA_M, y + sobreSuelo, -ym / ESCALA_M);
  }

  return { mesh, meta, aplicarExageracion, alturaEn, aEscena };
}
