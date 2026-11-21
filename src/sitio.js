/**
 * Lugar de Marte que muestra el visor. Se elige con el selector "Lugar" (o con ?sitio=gale en la dirección).
 * Cambiar de lugar recarga la página: el relieve, las capas, las rutas y el planificador son los de ese sitio.
 * Los archivos de Jezero están en public/data/ y los de los demás en public/data/<sitio>/ (exportar_sitio.py);
 * el servidor recibe el sitio en cada petición (?sitio=...) y usa el mismo modelo para todos.
 */
const SITIOS = {
  jezero: { titulo: 'Jezero', carpeta: '', rover: 'Perseverance', arena: ' (p. ej. Séítah)', vista: [-25, 0, 0] },
  gale: { titulo: 'Gale', carpeta: 'gale/', rover: 'Curiosity', arena: '', vista: [0, 0, 0] },
};

const pedido = new URLSearchParams(location.search).get('sitio');
export const SITIO = pedido && pedido in SITIOS ? pedido : 'jezero';
export const INFO = SITIOS[SITIO];

/** Dirección de un archivo de datos del sitio activo. */
export const rutaDatos = (archivo) => `${import.meta.env.BASE_URL}data/${INFO.carpeta}${archivo}`;

/** Agrega ?sitio=... a una ruta del servidor. */
export const conSitio = (ruta) => `${ruta}${ruta.includes('?') ? '&' : '?'}sitio=${SITIO}`;

/** Ajusta el panel al sitio: títulos, selector de lugar y misiones que existen ahí (atributo data-sitios). */
export function prepararPanel() {
  document.title = `Visor 3D · ${INFO.titulo}`;
  document.getElementById('panel-titulo').textContent = `${INFO.titulo} · Marswalk`;
  for (const op of document.querySelectorAll('#plan option[data-sitios]')) {
    if (!op.dataset.sitios.split(' ').includes(SITIO)) op.remove();
  }
  const selector = document.getElementById('sitio');
  selector.value = SITIO;
  selector.addEventListener('change', () => {
    const url = new URL(location.href);
    url.searchParams.set('sitio', selector.value);
    location.href = url;                       // recarga con el otro lugar
  });
}
