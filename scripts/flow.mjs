// Contrôle du parcours complet dans Chrome sans fenêtre : réservation, reçu, guidage,
// sortie, historique, API, mode administrateur, thème jour. Une capture par étape.
//   node flow.mjs <dossier de sortie> [url]
import puppeteer from 'puppeteer-core';

const out = process.argv[2];
const base = process.argv[3] || 'http://localhost:5173/';
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const browser = await puppeteer.launch({
  executablePath: process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true,
  args: ['--autoplay-policy=no-user-gesture-required', '--hide-scrollbars'],
});
const page = await browser.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
page.on('console', (m) => m.type() === 'error' && errors.push(`console: ${m.text()}`));
await page.setViewport({ width: 1280, height: 776, deviceScaleFactor: 1 });
const shot = async (name) => {
  await wait(700);
  await page.screenshot({ path: `${out}/${name}.jpg`, type: 'jpeg', quality: 86 });
  console.log('capture', name);
};
const text = (sel) => page.$eval(sel, (e) => e.textContent.trim());

await page.goto(base, { waitUntil: 'load' });
await page.evaluate(() => localStorage.clear());
await page.goto(base, { waitUntil: 'load' });
await wait(5000);

// 1. réservation depuis l'accueil
await page.click('.hero-copy [data-action="reserve-best"]');
await wait(500);
await page.type('#res-plate', 'fk-482-lm');
await page.click('#durations [data-h="4"]');
console.log('total affiché :', await text('#res-total'), '| place :', await text('#res-spot'));
await shot('01_reserver');
await page.click('#res-confirm');
await shot('02_recu');
console.log('reçu :', await text('#rec-spot'), await text('#rec-plate'), await text('#rec-total'));

// 2. guidage vers la place (explorateur)
await page.click('#rec-navigate');
await wait(2600);
await shot('03_guidage');
console.log('carte :', await text('#spot-id'), '/', await text('#spot-status'), '| barre :', await text('#ar-id'), await text('#ar-timer'));
await wait(6500); // la voiture arrive sur la place
await shot('04_arrivee');
console.log('après arrivée :', await text('#spot-status'), await text('#spot-plate'));

// 3. clic sur une place libre du plan, changement de niveau, recherche
await page.click('#levels [data-level="0"]');
await wait(900);
const box = await (await page.$('#level-canvas')).boundingBox();
await page.mouse.move(box.x + box.width * 0.42, box.y + box.height * 0.78);
await wait(300);
await page.mouse.click(box.x + box.width * 0.42, box.y + box.height * 0.78);
await shot('05_niveau_p0');
console.log('place cliquée :', await text('#spot-id'), '/', await text('#spot-status'), '/', await text('#spot-type'));
await page.type('#search-input', 'FK4');
await wait(400);
console.log('recherche :', await page.$$eval('#search-results button', (b) => b.map((x) => x.textContent.trim())));

// 4. mode administrateur
await page.click('#mode-switch [data-mode="admin"]');
await wait(300);
await page.click('#btn-sim-in');
await shot('06_admin');
console.log('admin :', await text('#adm-rate'), await text('#adm-revenue'), await text('#adm-active'));

// 5. sortie et historique
await page.click('#ar-end');
await shot('07_sortie');
console.log('sortie :', await text('#ex-dur'), '|', await text('#ex-over'), '|', await text('#ex-total'));
await page.click('#ex-pay');
await wait(500);
await page.click('#btn-history');
await shot('08_historique');
console.log('historique :', await page.$$eval('.history__item', (n) => n.length), 'ligne(s)');
await page.keyboard.press('Escape');

// 6. API
await page.click('.nav__links [data-goto="5"]');
await wait(2200);
await page.click('.endpoint[data-ep="stats"]');
await wait(700);
await shot('09_api');
console.log('API :', (await text('#api-response')).slice(0, 90).replace(/\s+/g, ' '));
await page.click('#api-tabs [data-tab="log"]');
console.log('journal :', await page.$$eval('#api-log div', (n) => n.length), 'ligne(s) ·', await text('#api-usage'));

// 7. thème jour sur les trois scènes
await page.click('#theme-btn');
for (const [i, name] of [[0, 'accueil'], [1, 'entree'], [2, 'guidage'], [3, 'niveaux'], [4, 'dashboard']]) {
  await page.click(`.dots [data-goto="${i}"]`);
  await wait(2600);
  await shot(`10_jour_${name}`);
}
console.log(errors.length ? `ERREURS (${errors.length})\n${errors.join('\n')}` : 'aucune erreur JavaScript');
await browser.close();
