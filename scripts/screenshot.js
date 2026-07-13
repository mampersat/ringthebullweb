// Regenerates images/screenshot.png for the README by driving a fresh
// game in headless Chrome against the local index.html (not the deployed
// URL, so it's not subject to CloudFront propagation delay).
const puppeteer = require('puppeteer-core');
const path = require('path');
const fs = require('fs');

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  '/usr/bin/google-chrome',
  '/usr/bin/google-chrome-stable',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
].filter(Boolean);

function findChrome() {
  for (const candidate of CHROME_CANDIDATES) {
    if (fs.existsSync(candidate)) return candidate;
  }
  throw new Error('No Chrome/Chromium binary found. Set CHROME_PATH to override.');
}

(async () => {
  const repoRoot = path.resolve(__dirname, '..');
  const outPath = path.join(repoRoot, 'images', 'screenshot.png');

  const browser = await puppeteer.launch({
    executablePath: findChrome(),
    headless: 'new',
    args: ['--no-sandbox'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 420, height: 900 });

  await page.goto('file://' + path.join(repoRoot, 'index.html'));
  await page.evaluate(() => localStorage.clear());
  await page.reload();

  // Play a partial game so the screenshot shows the grid and score in
  // action, not just an empty board.
  const sequence = ['hitBtn', 'hitBtn', 'missBtn', 'hitBtn', 'hitBtn', 'hitBtn', 'missBtn', 'hitBtn'];
  for (const id of sequence) {
    await page.click('#' + id);
  }

  await page.screenshot({ path: outPath });
  console.log('Wrote', outPath);

  await browser.close();
})().catch(e => {
  console.error('Screenshot generation failed:', e.message);
  process.exit(1);
});
