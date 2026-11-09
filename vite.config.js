// Todo lo que el visor pide a /api/... se reenvía al servidor de Python (servidor.py).
export default {
  server: { proxy: { '/api': 'http://localhost:8000' } },
  preview: { proxy: { '/api': 'http://localhost:8000' } },
};
