import { defineConfig } from 'vite';

export default defineConfig({
  // chemins relatifs : le dossier dist/ fonctionne à la racine d'un domaine comme dans un sous-dossier
  base: './',
  server: { port: 5173, open: false },
  build: { target: 'es2020', chunkSizeWarningLimit: 1600 },
});
