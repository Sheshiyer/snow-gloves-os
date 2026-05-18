import { chromium } from 'playwright';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { mkdirSync } from 'fs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT = join(__dirname, 'out');
mkdirSync(OUT, { recursive: true });

const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const W = 920, H = 720;

const ctx = await (await chromium.launch()).newContext({
  viewport: { width: W, height: H },
  deviceScaleFactor: 2,
  recordVideo: { dir: OUT, size: { width: W, height: H } },
});
const page = await ctx.newPage();
await page.goto('file://' + join(__dirname, 'demo.html'));
await sleep(600);

// Fake mouse cursor mover
const cursor = '#cursor';
async function moveTo(sel, delay=350) {
  const box = await page.locator(sel).boundingBox();
  if (!box) return;
  const cx = box.x + box.width/2, cy = box.y + box.height/2;
  await page.evaluate(([x,y])=>{const c=document.getElementById('cursor');c.classList.add('show');c.style.left=x+'px';c.style.top=y+'px';},[cx,cy]);
  await sleep(delay);
}
async function click(sel, before=400, after=500) {
  await moveTo(sel, before);
  await page.evaluate(()=>document.getElementById('cursor').classList.add('click'));
  await sleep(120);
  await page.click(sel);
  await page.evaluate(()=>document.getElementById('cursor').classList.remove('click'));
  await sleep(after);
}
async function typeInto(sel, text, perChar=55) {
  await moveTo(sel, 250);
  await page.click(sel);
  for (const ch of text) { await page.keyboard.type(ch); await sleep(perChar); }
}

// ====== SCENE 1: Welcome ======
await sleep(900);
await click('#next', 600, 700);

// ====== SCENE 2: Preflight ======
await sleep(400);
await click('#doctor', 500);
await page.evaluate(()=>window.__mockDoctor());
await sleep(1600);
await click('#next', 500, 600);

// ====== SCENE 3: Tenant ======
await sleep(300);
await typeInto('#biz', 'Tryambakam Noesis', 45);
await sleep(300);
// auto-slug fill
await page.evaluate(()=>{const v='tryambakam-noesis';window.__setState({business:'Tryambakam Noesis',slug:v});});
await sleep(700);
await click('#next', 400, 600);

// ====== SCENE 4: Paperclip ======
await sleep(300);
await typeInto('#cid', '2f554495-a76c-4d5a-bec8-71be115bce76', 22);
await page.evaluate(()=>{window.__setState({company_id:'2f554495-a76c-4d5a-bec8-71be115bce76'});});
await sleep(500);
await click('#next', 400, 600);

// ====== SCENE 5: Sources ======
await sleep(300);
await typeInto('#sources', '/Users/you/Documents/business/\n/Users/you/wiki/handbook.md', 25);
await page.evaluate(()=>{window.__setState({sources:'/Users/you/Documents/business/\n/Users/you/wiki/handbook.md'});});
await sleep(700);
await click('#next', 400, 600);

// ====== SCENE 6: Review ======
await sleep(1200);
await click('#next', 400, 600);

// ====== SCENE 7: Done + Smoke ======
await page.evaluate(()=>window.__mockProvision());
await sleep(1100);
await click('#smoke', 500, 200);
await page.evaluate(()=>window.__mockSmoke());
await sleep(4500); // let smoke log stream
await sleep(900);

const path = await page.video().path();
await ctx.close();
console.log('VIDEO:', path);
