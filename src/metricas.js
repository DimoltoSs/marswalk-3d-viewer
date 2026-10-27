/**
 * Panel de métricas (derecha): números de la misión y comparación con Perseverance.
 * Lee lo que exporta el notebook en rutas_v2.json:
 *   metricas, presupuesto, supuestos  -> sección 12
 *   comparacion                       -> sección 13.4
 * Con rutas.json (v1) solo hay costo_total / presupuesto: se muestra eso.
 */

// Clic en el título: plegar / desplegar
document.getElementById('metricas-titulo')
  .addEventListener('click', () => document.getElementById('metricas').classList.toggle('plegado'));

const fmt = (v, dec = 0) => v.toLocaleString('es-MX', { minimumFractionDigits: dec, maximumFractionDigits: dec });

/** Barra de uso del presupuesto: "144 / 168 h" con una barrita que se llena. */
function barra(nombre, usado, total, unidad, dec = 0) {
  const pct = Math.min(100, (100 * usado) / total);
  return `
    <div class="kpi">
      <div class="kpi-fila"><span>${nombre}</span><b>${fmt(usado, dec)} / ${fmt(total, dec)} ${unidad}</b></div>
      <div class="barra"><div style="width:${pct}%"></div></div>
    </div>`;
}

/** Fila NASA vs nosotros, con el cambio en % pintado de verde si es mejor. */
function filaVs(nombre, nasa, nuestra, dec, masEsMejor = false) {
  const cambio = (100 * (nuestra - nasa)) / nasa;
  const mejor = masEsMejor ? cambio > 0 : cambio < 0;
  const signo = cambio > 0 ? '+' : '';
  return `<tr><td>${nombre}</td><td>${fmt(nasa, dec)}</td><td>${fmt(nuestra, dec)}</td>
          <td class="${mejor ? 'bien' : 'mal'}">${signo}${fmt(cambio)} %</td></tr>`;
}

/** Barra apilada: tramos ganados / empatados / perdidos. */
function marcador(m, total) {
  const ancho = (n) => `${(100 * n) / total}%`;
  return `
    <div class="marcador" title="${m.ganamos} ganamos · ${m.empate} empate · ${m.perdemos} perdemos">
      <span>${m.metrica.replace(' (10–20°)', '')}</span>
      <div class="apilada">
        <div class="g" style="width:${ancho(m.ganamos)}">${m.ganamos || ''}</div>
        <div class="e" style="width:${ancho(m.empate)}">${m.empate || ''}</div>
        <div class="p" style="width:${ancho(m.perdemos)}">${m.perdemos || ''}</div>
      </div>
    </div>`;
}

export function mostrarMetricas(datos) {
  const caja = document.getElementById('metricas-contenido');

  if (!datos) { caja.innerHTML = '<p class="nota">Sin datos de rutas.</p>'; return; }

  // ---- Plan v1: solo hay costo ----
  if (!datos.metricas) {
    caja.innerHTML = `
      <div class="seccion"><h3>Plan v1 · prototipo_uno</h3>
        ${barra('Costo', datos.costo_total, datos.presupuesto, '')}
        <p class="nota">${datos.objetivos.length} objetivos. Las métricas físicas y la comparación con
        Perseverance están en el plan v2 (notebook).</p>
      </div>`;
    return;
  }

  // ---- Plan v2 ----
  const m = datos.metricas, pres = datos.presupuesto, sup = datos.supuestos;
  let html = `
    <div class="seccion"><h3>Nuestra misión</h3>
      <div class="kpi-grande">
        <div><b>${fmt(m.ciencia, 2)}</b><span>ciencia</span></div>
        <div><b>${datos.objetivos.length}</b><span>objetivos</span></div>
        <div><b>${fmt(m.km, 1)}</b><span>km</span></div>
      </div>
      ${barra('Tiempo', m.horas, pres.horas, 'h')}
      ${barra('Energía', m.wh, pres.wh, 'Wh')}
      <p class="nota">Incluye ${sup ? sup.horas_por_objetivo : 4} h de estudio por objetivo.
      Riesgo (10–20°): ${fmt(m.riesgo_km * 1000)} m.</p>
    </div>`;

  const c = datos.comparacion;
  if (c) {
    const n = c.nasa, t = c.nuestra;
    html += `
      <div class="seccion"><h3>vs Perseverance · misión completa</h3>
        <table class="vs">
          <tr><th></th><th>NASA</th><th>Nuestra</th><th></th></tr>
          ${filaVs('Distancia (km)', n.km, t.km, 1)}
          ${filaVs('Sols de manejo', n.sols_manejo, t.sols_manejo, 1)}
          ${filaVs('Energía (Wh)', n.energia_manejo_wh, t.energia_manejo_wh, 0)}
          ${filaVs('Subida (m)', n.subida_m, t.subida_m, 0)}
          ${filaVs('Pend. máx (°)', n.pend_max_deg, t.pend_max_deg, 1)}
          ${filaVs('Ciencia', n.ciencia, t.ciencia, 2, true)}
          ${filaVs('Ciencia / kWh', n.ciencia_por_kWh, t.ciencia_por_kWh, 2, true)}
        </table>
        <p class="nota">Mismo inicio y meta. Solo manejo (sin estudio). Ciencia = manchas CRISM a &lt;200 m de la ruta.</p>
      </div>
      <div class="seccion"><h3>Tramo a tramo · ${c.tramos} tramos</h3>
        ${c.marcador.map((fila) => marcador(fila, c.tramos)).join('')}
        <p class="nota"><span class="cuadro g"></span>ganamos <span class="cuadro e"></span>empate
        <span class="cuadro p"></span>perdemos · entre las mismas paradas reales</p>
      </div>`;
  } else {
    html += `<p class="nota">Corre la sección 13.4 del notebook para ver la comparación con Perseverance.</p>`;
  }
  caja.innerHTML = html;
}
