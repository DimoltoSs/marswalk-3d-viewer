import * as THREE from 'three';

/**
 * Capas de datos encima del terreno: minerales CRISM y mapa de costos.
 * Las genera el notebook (sección 13.4): capa_*.png + capas.json con las leyendas.
 *
 * Truco: una segunda malla que COMPARTE la geometría del terreno. Como es la misma
 * geometría, si cambia la exageración la capa la sigue sola. Se dibuja encima con
 * transparencia y "polygonOffset" (un empujoncito hacia la cámara para que no parpadee
 * peleándose con el terreno, que está exactamente en el mismo lugar).
 */
export async function cargarCapas(terreno, anisotropia = 1) {
  const resp = await fetch('/data/capas.json');
  const esJson = resp.headers.get('content-type')?.includes('json');
  if (!resp.ok || !esJson) throw new Error('No se encontró /data/capas.json (sección 13.4 del notebook)');
  const info = await resp.json();

  const material = new THREE.MeshLambertMaterial({
    transparent: true,
    opacity: 0.8,
    depthWrite: false,            // no tapa a lo que se dibuje después (rutas, pines)
    polygonOffset: true,
    polygonOffsetFactor: -2,
    polygonOffsetUnits: -2,
  });
  const mesh = new THREE.Mesh(terreno.mesh.geometry, material);
  mesh.receiveShadow = true;      // las sombras del relieve también oscurecen la capa
  mesh.visible = false;

  const cargador = new THREE.TextureLoader();
  const texturas = {};            // se cargan la primera vez que se piden

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
    material.needsUpdate = true;  // el shader cambia la primera vez que se pone un map
    mesh.visible = true;
    dibujarLeyenda(info[nombre]);
  }

  function opacidad(valor) {
    material.opacity = valor;
  }

  return { mesh, mostrar, opacidad };
}

/** Leyenda debajo del selector: lista de colores (CRISM) o degradado (costos). */
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
