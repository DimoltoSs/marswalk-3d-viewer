/**
 * Panel de controles. El HTML está en index.html; aquí solo se conectan los eventos.
 *
 * No depende de Three.js: recibe un objeto `acciones` y llama a sus funciones cuando
 * cambia un control. main.js define qué hace cada una.
 *
 * acciones = {
 *   capa(nombre, visible)   'real' | 'plan' | 'objetivos'
 *   exageracion(valor)      1..6
 *   pausa(pausado)          true / false
 *   velocidad(m_s)          m simulados por segundo real
 *   seguir(activo)          cámara que sigue al rover
 *   plan(archivo)           'rutas_v2.json' | 'rutas.json'
 *   capaTerreno(nombre)     'crism' | 'costo' | null
 *   opacidadCapa(valor)     0.1..1
 *   replaneo(activo)        simular un peligro y el desvío autónomo
 * }
 */
export function crearInterfaz(acciones) {
  const $ = (id) => document.getElementById(id);

  // Capas de rutas: un checkbox por capa, identificado con data-capa
  for (const caja of document.querySelectorAll('[data-capa]')) {
    caja.addEventListener('change', () => acciones.capa(caja.dataset.capa, caja.checked));
  }

  // Exageración del relieve
  const exa = $('exageracion');
  exa.addEventListener('input', () => {
    $('exageracion-valor').textContent = `${exa.value}×`;
    acciones.exageracion(Number(exa.value));
  });

  // Capa sobre el terreno (CRISM / costos)
  $('capa').addEventListener('change', (e) => acciones.capaTerreno(e.target.value || null));
  const opa = $('capa-opacidad');
  opa.addEventListener('input', () => {
    $('capa-opacidad-valor').textContent = `${Math.round(opa.value * 100)} %`;
    acciones.opacidadCapa(Number(opa.value));
  });

  // Rover: pausa, velocidad y cámara
  const botonPausa = $('pausa');
  let pausado = false;
  botonPausa.addEventListener('click', () => {
    pausado = !pausado;
    botonPausa.textContent = pausado ? '▶ Reanudar' : '⏸ Pausa';
    acciones.pausa(pausado);
  });

  const vel = $('velocidad');
  vel.addEventListener('input', () => {
    $('velocidad-valor').textContent = `${vel.value} m/s`;
    acciones.velocidad(Number(vel.value));
  });

  $('seguir').addEventListener('change', (e) => acciones.seguir(e.target.checked));

  // Navegación autónoma: peligro simulado
  $('replaneo').addEventListener('change', (e) => acciones.replaneo(e.target.checked));

  // Plan v1 / v2
  $('plan').addEventListener('change', (e) => acciones.plan(e.target.value));

  // Clic en el título: plegar / desplegar el panel
  $('panel-titulo').addEventListener('click', () => $('panel').classList.toggle('plegado'));
}

/** Aviso en la parte inferior de la pantalla (p. ej. un archivo que falta). Se acumulan. */
export function aviso(texto) {
  const caja = document.getElementById('avisos');
  const linea = document.createElement('div');
  linea.textContent = `⚠ ${texto}`;
  caja.appendChild(linea);
  console.warn(texto);
}
