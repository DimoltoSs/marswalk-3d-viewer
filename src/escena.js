import * as THREE from 'three';

const CIELO = 0xc9a27e;   // tono "butterscotch" del cielo marciano

/** Renderer, escena, cámara y luces. */
export function crearEscena(canvas) {
  // ---- Renderer ----
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));   // 2 casi duplica los píxeles sin mejora visible
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  // Sombras precalculadas: el terreno no se mueve, así que el mapa de sombras se genera
  // solo cuando algo cambia (renderer.shadowMap.needsUpdate = true) y no en cada cuadro.
  renderer.shadowMap.autoUpdate = false;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;

  // ---- Escena: cielo y niebla ----
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(CIELO);
  scene.fog = new THREE.Fog(CIELO, 150, 380);           // de 15 a 38 km

  const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 2000);

  // ---- Luces ----
  scene.add(new THREE.HemisphereLight(0xffe8d0, 0x5a3a28, 1.2));   // cielo cálido / suelo oscuro

  // Sol bajo desde el Oeste: sombras largas que resaltan el relieve
  const sol = new THREE.DirectionalLight(0xfff1e0, 3.0);
  sol.position.set(-150, 60, -50);                      // al Oeste (x < 0) y un poco al Norte (z < 0)
  sol.castShadow = true;
  sol.shadow.mapSize.set(2048, 2048);
  const s = sol.shadow.camera;                          // área que cubre el mapa de sombras
  s.left = -120; s.right = 120; s.top = 120; s.bottom = -120;
  s.near = 1; s.far = 500;
  sol.shadow.bias = -0.0005;                            // evita rayas de auto-sombra
  sol.shadow.normalBias = 0.5;
  scene.add(sol);

  function ajustarTamano() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  window.addEventListener('resize', ajustarTamano);
  ajustarTamano();

  return { renderer, scene, camera, sol };
}
