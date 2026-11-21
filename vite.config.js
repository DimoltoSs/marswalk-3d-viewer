// En desarrollo, todo lo que el visor pide a /api/... se reenvía al servidor de Python (servidor.py).
// Al construir para GitHub Pages, el sitio vive en /marswalk-3d-viewer/ (no en la raíz del dominio).
export default ({ command }) => ({
  base: command === 'build' ? '/marswalk-3d-viewer/' : '/',
  server: { proxy: { '/api': 'http://localhost:8000' } },
  preview: { proxy: { '/api': 'http://localhost:8000' } },
});
