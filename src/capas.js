import * as THREE from 'three';

/**
 * Capas de datos sobre el terreno: minerales CRISM y mapa de costos.
 * Las genera el notebook (sección 13.4): capa_*.png y capas.json con las leyendas.
 *
 * Se dibujan en una segunda malla que comparte la geometría del terreno, así que siguen
 * la exageración sin reconstruir nada. polygonOffset acerca la capa a la cámara para
 * evitar el parpadeo (z-fighting) con el terreno, que ocupa exactamente el mismo lugar.
 */
export async function cargarCapas(terreno, anisotropia = 1) {
  const resp = await fetch('/data/capas.json');
  const esJson = resp.headers.get('content-type')?.includes('json');
  if (!resp.ok || !esJson) throw new Error('No se encontró /data/capas.json (sección 13.4 del notebook)');
  const info = await resp.json();

  const material = new THREE.MeshLambertMaterial({
    transparent: true,
    opacity: 0.8,
    depthWrite: false,            // no oculta las rutas ni los pines
    polygonOffset: true,
    polygonOffsetFactor: -2,
    polygonOffsetUnits: -2,
  });
  const mesh = new THREE.Mesh(terreno.mesh.geometry, material);
  mesh.receiveShadow = true;      // conserva el sombreado del relieve
  mesh.visible = false;

  const cargador = new THREE.TextureLoader();
  const texturas = {};            // carga diferida: la primera vez que se elige cada capa

  /** Muestra la capa 'crism' | 'costo', o ninguna con null. */
  async function mostrar(nombre) {
    if (!nombre) {
      mesh.visible = false;
      dibujarLeyenda(null);
      return;
    }
    if (!texturas[nombre]) {
      const tex = await cargador.loadAsync(`/data/${info[nombre].archivo}`);
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.anisotropy = anisotropia;
      texturas[nombre] = tex;
    }
    material.map = texturas[nombre];
    material.needsUpdate = true;  // al asignar el primer map el shader se recompila
    mesh.visible = true;
    dibujarLeyenda(info[nombre]);
  }

  function opacidad(valor) {
    material.opacity = valor;
  }

  return { mesh, mostrar, opacidad };
}

/** Leyenda bajo el selector: lista de colores (CRISM) o escala de color (costos). */
function dibujarLeyenda(capa) {
  const caja = document.getElementById('capa-leyenda');
  if (!capa) { caja.innerHTML = ''; return; }

  if (capa.leyenda) {
    caja.innerHTML = capa.leyenda
      .map((m) => `<div><span class="cuadro" style="background:${m.color}"></span>${m.nombre}
                   <i>${m.valor ? `valor ${m.valor}` : ''}</i></div>`)
      .join('');
  } else {
    const e = capa.escala;
    caja.innerHTML = `
      <div class="degradado" style="background:linear-gradient(to right, ${e.colores.join(', ')})"></div>
      <div class="extremos"><span>${e.min} barato</span><span>caro ${e.max}+</span></div>
      <div><span class="cuadro" style="background:${capa.bloqueado}"></span>bloqueado (≥ 20°)</div>`;
  }
}
