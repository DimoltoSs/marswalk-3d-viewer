/**
 * Panel de métricas: nuestra misión y su comparación con Perseverance.
 * Datos de rutas_v2.json, generado por el notebook planificador_v2:
 *   metricas, presupuesto, supuestos  -> sección 12
 *   comparacion                       -> sección 13.4
 * El plan v1 (rutas.json) solo tiene costo_total y presupuesto.
 */

// Clic en el título: plegar / desplegar
document.getElementById('metricas-titulo')
  .addEventListener('click', () => document.getElementById('metricas').classList.toggle('plegado'));

const fmt = (v, dec = 0) => v.toLocaleString('es-MX', { minimumFractionDigits: dec, maximumFractionDigits: dec });

/** Uso del presupuesto, p. ej. "144 / 168 h", con barra de progreso. */
function barra(nombre, usado, total, unidad, dec = 0) {
  const pct = Math.min(100, (100 * usado) / total);
  return `
    <div class="kpi">
      <div class="kpi-fila"><span>${nombre}</span><b>${fmt(usado, dec)} / ${fmt(total, dec)} ${unidad}</b></div>
      <div class="barra"><div style="width:${pct}%"></div></div>
    </div>`;
}

/** Fila NASA vs. nuestra misión; el cambio en % va en verde si es mejora. */
function filaVs(nombre, nasa, nuestra, dec, masEsMejor = false) {
  const cambio = (100 * (nuestra - nasa)) / nasa;
  const mejor = masEsMejor ? cambio > 0 : cambio < 0;
  const signo = cambio > 0 ? '+' : '';
  return `<tr><td>${nombre}</td><td>${fmt(nasa, dec)}</td><td>${fmt(nuestra, dec)}</td>
          <td class="${mejor ? 'bien' : 'mal'}">${signo}${fmt(cambio)} %</td></tr>`;
}

/** Barra apilada con los tramos ganados / empatados / perdidos de una métrica. */
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

/** Dibuja el panel para el plan cargado (null = sin datos). */
export function mostrarMetricas(datos) {
  const caja = document.getElementById('metricas-contenido');

  if (!datos) { caja.innerHTML = '<p class="nota">Sin datos de rutas.</p>'; return; }

  // ---- Plan v1: solo costo ----
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

/** Panel para la misión libre (A → B) o la EVA, calculadas en vivo por servidor.py. */
export function mostrarMetricasVivo(modo, r) {
  const caja = document.getElementById('metricas-contenido');
  const eva = modo === 'eva';
  const titulo = eva ? 'EVA del astronauta · 3 km' : 'Misión libre · A → B';
  if (!r || !r.plan) {
    const pista = eva ? 'Haz clic en el terreno para poner el hábitat.'
      : 'Haz clic en el terreno para poner el inicio (A) y luego el final (B).';
    caja.innerHTML = `<div class="seccion"><h3>${titulo}</h3><p class="nota">${pista}</p></div>`;
    return;
  }

  const ciencia = r.objetivos.reduce((suma, o) => suma + o.puntaje, 0);
  const presupuesto = eva
    ? `${barra('Esfuerzo', r.esfuerzo, r.esfuerzo_max, '')}
       ${barra('Alejamiento máx.', r.max_alejamiento_m, r.radio_m, 'm')}
       <p class="nota">Esfuerzo = costo del mapa (1 ≈ 1 m en plano). Ida y vuelta al hábitat.</p>`
    : `${barra('Costo', r.costo, r.presupuesto, '')}
       <p class="nota">Ruta directa A → B: costo ${fmt(r.costo_directo)}. El presupuesto es 1.5 × directo:
       el extra se gasta en pasar por minerales. ${r.candidatos} candidatos considerados.</p>`;
  const filas = r.objetivos.map((o) =>
    `<tr><td>${o.parada}. ${o.mineral}</td><td>${fmt(o.area_ha, 1)} ha</td><td>${fmt(o.puntaje)}</td></tr>`).join('');

  caja.innerHTML = `
    <div class="seccion"><h3>${titulo}</h3>
      <div class="kpi-grande">
        <div><b>${r.objetivos.length}</b><span>objetivos</span></div>
        <div><b>${fmt(r.km, 2)}</b><span>km</span></div>
        <div><b>${fmt(ciencia)}</b><span>ciencia</span></div>
      </div>
      ${presupuesto}
    </div>
    <div class="seccion"><h3>Objetivos en orden</h3>
      ${filas ? `<table class="vs"><tr><th></th><th>Área</th><th>Puntaje</th></tr>${filas}</table>`
              : '<p class="nota">Ninguno cabe en el presupuesto: ruta directa.</p>'}
      <p class="nota">${r.waypoints.length} waypoints. Pendiente ≥ 20° = obstáculo.</p>
    </div>`;
}
