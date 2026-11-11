// Capture d'écran du site dans Chrome sans fenêtre (contrôle visuel, README).
//   node shot.mjs <image de sortie> <url> [largeur] [hauteur] [attente ms] [JavaScript à exécuter avant]
// Le site accepte ?section=N, ?theme=day|night et ?t=secondes (vidéo figée à cet instant).
// Nécessite puppeteer-core (npm i puppeteer-core@24 dans un dossier temporaire, y copier ce script).
import puppeteer from 'puppeteer-core';

const [out, url, w = '1280', h = '776', waitMs = '4500', js = ''] = process.argv.slice(2);
const mobile = +w < 600;
const browser = await puppeteer.launch({
  executablePath: process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true,
  args: ['--autoplay-policy=no-user-gesture-required', '--hide-scrollbars'],
});
const page = await browser.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
page.on('console', (m) => m.type() === 'error' && errors.push(`console: ${m.text()}`));
page.on('requestfailed', (r) => errors.push(`requête échouée: ${r.url()}`));
await page.setViewport({ width: +w, height: +h, deviceScaleFactor: 1, isMobile: mobile, hasTouch: mobile });
await page.goto(url, { waitUntil: 'load' });
await new Promise((r) => setTimeout(r, +waitMs));
if (js) {
  const res = await page.evaluate(js);
  if (res !== undefined) console.log('JS ->', JSON.stringify(res));
  await new Promise((r) => setTimeout(r, 1500));
}
await page.screenshot({ path: out, type: out.endsWith('.png') ? 'png' : 'jpeg', ...(out.endsWith('.png') ? {} : { quality: 88 }) });
console.log(errors.length ? `ERREURS (${errors.length})\n${errors.join('\n')}` : 'aucune erreur', '->', out);
await browser.close();
