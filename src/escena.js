import * as THREE from 'three';

const CIELO = 0xc9a27e;   // color "butterscotch" del cielo marciano

export function crearEscena(canvas) {
  // ---- Renderer ----
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));   // 1.5 basta; 2 = casi el doble de píxeles
  renderer.shadowMap.enabled = true;                    // activa el cálculo de sombras
  renderer.shadowMap.type = THREE.PCFShadowMap;         // sombras filtradas (bordes suaves)
  // Sombras "horneadas": el terreno no se mueve, así que el mapa de sombras se calcula
  // una sola vez. Para recalcularlo: renderer.shadowMap.needsUpdate = true
  renderer.shadowMap.autoUpdate = false;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;   // colores más "fotográficos"

  // ---- Escena con cielo y niebla ----
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(CIELO);
  scene.fog = new THREE.Fog(CIELO, 150, 380);           // empieza a 15 km, total a 38 km

  // ---- Cámara ----
  const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 2000);

  // ---- Luz ambiente: cielo cálido arriba, suelo oscuro abajo ----
  scene.add(new THREE.HemisphereLight(0xffe8d0, 0x5a3a28, 1.2));

  // ---- Sol: bajo y desde el oeste, para que el relieve haga sombras largas ----
  const sol = new THREE.DirectionalLight(0xfff1e0, 3.0);
  sol.position.set(-150, 60, -50);                      // (Oeste, altura, Norte)
  sol.castShadow = true;
  sol.shadow.mapSize.set(2048, 2048);                   // resolución de la sombra
  const s = sol.shadow.camera;                          // zona que cubre la sombra
  s.left = -120; s.right = 120; s.top = 120; s.bottom = -120;
  s.near = 1; s.far = 500;
  sol.shadow.bias = -0.0005;                            // evita "rayas" de auto-sombra
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