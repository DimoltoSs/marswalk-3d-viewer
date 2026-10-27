/**
 * Panel de controles (el HTML está en index.html, aquí solo se conectan los eventos).
 *
 * interfaz.js no sabe nada de Three.js: recibe un objeto "acciones" con funciones
 * y las llama cuando el usuario toca algo. Así main.js decide QUÉ hace cada control.
 *
 * acciones = {
 *   capa(nombre, visible)   nombre: 'real' | 'plan' | 'objetivos'
 *   exageracion(valor)      1..6
 *   pausa(pausado)          true / false
 *   velocidad(m_s)          m/s simulados por segundo real
 *   seguir(activo)          cámara que sigue al rover
 *   plan(archivo)           'rutas_v2.json' | 'rutas.json'
 * }
 */
export function crearInterfaz(acciones) {
  const $ = (id) => document.getElementById(id);

  // ---- Capas: un checkbox por capa, con data-capa="real" etc. ----
  for (const caja of document.querySelectorAll('[data-capa]')) {
    caja.addEventListener('change', () => acciones.capa(caja.dataset.capa, caja.checked));
  }

  // ---- Exageración del relieve ----
  const exa = $('exageracion');
  exa.addEventListener('input', () => {
    $('exageracion-valor').textContent = `${exa.value}×`;
    acciones.exageracion(Number(exa.value));
  });

  // ---- Rover: pausa y velocidad ----
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

  // ---- Plan v1 / v2 ----
  $('plan').addEventListener('change', (e) => acciones.plan(e.target.value));

  // ---- Plegar / desplegar el panel ----
  $('panel-titulo').addEventListener('click', () => $('panel').classList.toggle('plegado'));
}

/** Muestra un aviso abajo de la pantalla (p. ej. si falta un archivo). Se acumulan. */
export function aviso(texto) {
  const caja = document.getElementById('avisos');
  const linea = document.createElement('div');
  linea.textContent = `⚠ ${texto}`;
  caja.appendChild(linea);
  console.warn(texto);
}
