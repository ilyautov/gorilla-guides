// Минимальная сцена рила серии N: весь кадр рисуется на <canvas> кодом, время задаёт рендерер.
// Правила, которые нельзя ломать:
//  1. setTime(t) — чистая функция от t: никакого состояния между кадрами, никакого Math.random и Date.now.
//     Тогда кадр 241 рендерится одинаково в превью, в полном рендере и после перезапуска.
//  2. Всё случайное — из сидированного PRNG (rng(seed)), посчитано один раз при загрузке.
//  3. Время событий берётся из слов голоса (wt): сменил текст или голос — сцена сама переехала.
//  4. Наружу: window.ready, window.setTime, window.shotTimes (склейки для звука), window.events (метки для SFX).
// Сборка: tsc -p scene (см. scene/tsconfig.json) -> build/scene.js.
type Cue = {id: number; start: number; end: number; text: string};
type Word = {line: number; text: string; start: number; end: number};
type Story = {duration: number; cues: Cue[]; words: Word[]};
interface Window {ready: boolean; setTime: (t: number) => Promise<void>; shotTimes: number[]; events: Record<string, number>}

const FW = 1080, FH = 1920;
const LIME = '#d6ff43', RED = '#ff4d42', WHITE = '#ffffff', INK = '#1a2023', GREY = '#8b929b';
const SANS = 'Onest, "Helvetica Neue", Arial, sans-serif', ACCENT = 'Accent, Georgia, serif', MONO = 'Menlo, "DejaVu Sans Mono", monospace';
const canvas = document.querySelector<HTMLCanvasElement>('#film')!;
const out = canvas.getContext('2d')!;                       // финальный кадр: камера, виньетка, зерно, субтитры
const world = document.createElement('canvas'); world.width = FW; world.height = FH;
const c = world.getContext('2d')!;                          // «мир» плана, его снимает камера

// ---------- математика времени ----------
const clamp = (v: number, a = 0, b = 1) => Math.max(a, Math.min(b, v));
const ease = (v: number) => 1 - Math.pow(1 - clamp(v), 3);                       // быстрое начало, мягкая остановка
const inout = (v: number) => {const x = clamp(v); return x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;};
const back = (v: number) => {const x = clamp(v), k = 1.7; return 1 + (k + 1) * Math.pow(x - 1, 3) + k * Math.pow(x - 1, 2);};  // с перелётом
const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
const sines = (t: number, l: [number, number, number][]) => l.reduce((s, [amp, f, ph]) => s + amp * Math.sin(t * f + ph), 0);
function rng(seed: number) {   // mulberry32: один сид — одна и та же последовательность на любой машине
  let a = seed >>> 0;
  return () => {a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296;};
}

// ---------- рисование ----------
function font(size: number, fam = SANS, w = 700) {c.font = `${fam === ACCENT ? 'italic 400' : w} ${size}px ${fam}`;}
function text(s: string, x: number, y: number, size: number, col = WHITE, align: CanvasTextAlign = 'center', fam = SANS, w = 700) {
  font(size, fam, w); c.textAlign = align; c.textBaseline = 'alphabetic'; c.fillStyle = col; c.fillText(s, x, y); return c.measureText(s).width;
}
function box(x: number, y: number, w: number, h: number, col: string, r = 24) {c.beginPath(); c.roundRect(x, y, w, h, r); c.fillStyle = col; c.fill();}
function glow(col: string, blur: number) {c.shadowColor = col; c.shadowBlur = blur;}
function noGlow() {c.shadowBlur = 0; c.shadowColor = 'transparent';}
function bg(col: string) {c.fillStyle = col; c.fillRect(-600, -600, FW + 1200, FH + 1200);}   // с запасом под камеру
function cam(cx: number, cy: number, s: number, rot = 0) {c.translate(FW / 2, FH / 2); c.rotate(rot); c.scale(s, s); c.translate(-cx, -cy);}
function typed(s: string, t: number, at: number, d: number) {return t < at ? '' : s.slice(0, Math.ceil(clamp((t - at) / d) * s.length));}

async function main() {
  const s: Story = await (await fetch('story.json')).json();
  for (const f of ['700 80px Onest', '400 80px Onest', 'italic 400 80px Accent']) {   // нет файлов шрифтов — рисуем запасными
    const ok = await document.fonts.load(f, 'Жw').then(l => l.length > 0, () => false);
    if (!ok) console.warn('шрифт не найден, будет запасной:', f);}
  const W = s.words, END = s.duration;
  const norm = (x: string) => x.toLowerCase().replace(/ё/g, 'е').replace(/[^a-zа-я0-9]/g, '');
  // wt(реплика, начало слова) -> время начала слова (end=true — конца). Нет слова — падаем сразу, а не рисуем мимо.
  function wt(line: number, prefix: string, end = false) {
    const w = W.find(x => x.line === line && norm(x.text).startsWith(norm(prefix)));
    if (!w) throw new Error(`нет слова «${prefix}» в реплике ${line}`);
    return end ? w.end : w.start;
  }
  const cue = (i: number) => s.cues[i].start;
  const E = {l0: cue(0), kod: wt(0, 'кода'), bez: wt(0, 'без'), montazh: wt(0, 'монтажки'),
    l1: cue(1), golos: wt(1, 'голос'), kadry: wt(1, 'кадры'), zvuk: wt(1, 'звук'), paru: wt(1, 'пару'),
    l2: cue(2), n200: wt(2, '200'), n200End: wt(2, '200', true), strok: wt(2, 'строк'), povtori: wt(2, 'повтори')};

  // ---------- то, что считается один раз ----------
  const grain = document.createElement('canvas'); grain.width = 540; grain.height = 960;
  {const g = grain.getContext('2d')!, d = g.createImageData(540, 960), r = rng(7);
    for (let i = 0; i < d.data.length; i += 4) {const v = r() * 255; d.data[i] = d.data[i + 1] = d.data[i + 2] = v; d.data[i + 3] = 255;}
    g.putImageData(d, 0, 0);}
  const codeRows = (() => {const r = rng(42); return Array.from({length: 40}, () => ({indent: Math.floor(r() * 4), w: 120 + r() * 520, hue: r() < .2 ? LIME : r() < .5 ? '#5d6b73' : '#3a464d'}));})();

  // ---------- планы: один крупный предмет на кадр ----------
  function terminalShot(t: number) {          // «собран из кода»: печатается команда, бегут строки
    bg('#07090b'); const x = 70, y = 640, w = 940, h = 620;
    box(x, y, w, h, '#0b0f0d', 28); box(x, y, w, 64, '#151b18', 28);
    ['#ff5f57', '#febc2e', '#28c840'].forEach((col, i) => {c.beginPath(); c.arc(x + 40 + i * 30, y + 32, 10, 0, 7); c.fillStyle = col; c.fill();});
    c.font = `54px ${MONO}`; c.textAlign = 'left'; c.fillStyle = LIME;
    c.fillText(typed('$ ./make.sh all', t, E.l0 + .1, .6), x + 44, y + 160);
    ['voice    ✓', 'scene    ✓', 'sound    ✓', 'render   ✓'].forEach((l, i) => {
      const k = clamp((t - E.kod - .12 * i) / .15); if (k <= 0) return;
      c.globalAlpha = k; c.fillStyle = '#cfe8d8'; c.fillText(l, x + 44, y + 270 + i * 80); c.globalAlpha = 1;});
  }
  function timelineShot(t: number) {          // «без монтажки»: дорожки монтажной программы перечёркиваются
    bg('#0a0b0d'); const k = ease((t - E.bez) / .4);
    for (let r = 0; r < 4; r++) for (let j = 0; j < 5; j++) {
      const x = 120 + j * 170 + (r % 2) * 40 - (1 - k) * 200, y = 760 + r * 110;
      box(x, y, 150, 86, ['#3554a0', '#8a2f4a', '#2a7a5a', '#806020'][r], 14);}
    const p = ease((t - E.montazh - .05) / .35);        // крест рисуется за 0,35 с от слова «монтажки»
    if (p > 0) {c.save(); c.strokeStyle = RED; c.lineWidth = 26; c.lineCap = 'round'; glow(RED, 30); c.beginPath();
      c.moveTo(160, 700); c.lineTo(lerp(160, 920, p), lerp(700, 1300, p));
      if (p > .5) {const q = (p - .5) * 2; c.moveTo(920, 700); c.lineTo(lerp(920, 160, q), lerp(700, 1300, q));}
      c.stroke(); c.restore();}
  }
  function tilesShot(t: number) {             // «голос, кадры и звук»: три плитки выскакивают на своих словах
    bg('#07080a');
    ([['Голос', E.golos], ['Кадры', E.kadry], ['Звук', E.zvuk]] as [string, number][]).forEach(([name, at], i) => {
      const k = back((t - at + .05) / .3); if (k <= 0) return;
      const cx = 540, cy = 760 + i * 300;
      c.save(); c.translate(cx, cy); c.scale(k, k); box(-420, -120, 840, 240, '#14181c', 32);
      text(name, -360, 25, 84, WHITE, 'left');
      for (let b = 0; b < 9; b++) {                     // мини-эквалайзер: высота — функция от t, не состояние
        const hgt = 30 + 70 * Math.abs(Math.sin(t * (3 + i) + b * 1.3));
        box(70 + b * 34, -hgt / 2, 20, hgt, i === 0 ? LIME : '#5d6b73', 6);}
      c.restore();});
    const p = back((t - E.paru) / .3);
    if (p > 0) {c.save(); c.translate(540, 1720); c.scale(p, p); box(-210, -70, 420, 120, LIME, 60); text('≈ 2 мин', 0, 20, 64, INK); c.restore();}
  }
  function counterShot(t: number) {           // огромная лаймовая цифра со счётчиком 0 -> 200
    bg('#060809'); c.font = `30px ${MONO}`;
    codeRows.forEach((r, i) => box(120 + r.indent * 40, 300 + i * 34 - (t - E.n200) * 60, r.w, 14, r.hue, 7));   // код уезжает вверх
    const dim = c.createLinearGradient(0, 0, 0, FH); dim.addColorStop(0, 'rgba(6,8,9,.4)'); dim.addColorStop(.5, 'rgba(6,8,9,.9)'); dim.addColorStop(1, 'rgba(6,8,9,.4)');
    c.fillStyle = dim; c.fillRect(-600, -600, FW + 1200, FH + 1200);
    const k = inout((t - E.n200 + .05) / (E.n200End - E.n200 + .35)), n = Math.round(200 * k);
    const pop = 1 + .08 * Math.max(0, 1 - Math.abs(t - E.n200End - .3) / .2);         // толчок в момент, когда счётчик встал
    c.save(); c.translate(540, 1080); c.scale(pop, pop); glow('rgba(214,255,67,.55)', 60); text(String(n), 0, 0, 420, LIME); noGlow(); c.restore();
    if (t > E.strok - .05) text('строк', 540, 1220, 72, '#c8ced6', 'center', SANS, 400);
  }
  function readmeShot(t: number) {            // «повтори по инструкции»: чек-лист отмечается по шагам
    bg('#0a0c0e'); box(130, 620, 820, 760, '#f4f3ee', 36); text('README.md', 540, 730, 64, INK);
    ['поставить зависимости', 'записать голос', 'собрать ролик'].forEach((l, i) => {
      const y = 880 + i * 150, k = back((t - E.povtori - .1 - .25 * i) / .25);
      text(l, 300, y + 18, 52, INK, 'left', SANS, 400);
      if (k > 0) {c.save(); c.translate(220, y); c.scale(k, k); c.beginPath(); c.arc(0, 0, 44, 0, 7); c.fillStyle = LIME; c.fill();
        c.strokeStyle = INK; c.lineWidth = 10; c.lineCap = 'round'; c.beginPath(); c.moveTo(-18, 0); c.lineTo(-4, 14); c.lineTo(20, -14); c.stroke(); c.restore();}});
  }

  // ---------- монтаж: склейка на фразу, whip = направление переброса (+1 вправо, −1 влево) ----------
  type Shot = {at: number; whip?: number; draw: (t: number, lt: number) => void};
  const shots: Shot[] = [
    {at: 0, draw: (t, lt) => {cam(540, lerp(980, 940, inout(lt / 2)), lerp(1.0, 1.08, inout(lt / 2))); terminalShot(t);}},
    {at: E.bez - .05, whip: 1, draw: (t, lt) => {cam(540, 1000, lerp(1.04, 1.1, lt / 1.5), lerp(.02, -.01, lt / 1.5)); timelineShot(t);}},
    {at: E.l1 - .05, whip: -1, draw: (t, lt) => {cam(540, lerp(1100, 1180, inout(lt / 3)), lerp(.98, 1.04, inout(lt / 3))); tilesShot(t);}},
    {at: E.n200 - .05, whip: 1, draw: (t, lt) => {cam(540, 1080, lerp(1.0, 1.08, ease(lt / 1.5)), sines(t, [[.01, .8, 0]])); counterShot(t);}},
    {at: E.povtori - .05, draw: (t, lt) => {cam(540, lerp(1040, 1000, inout(lt / 2)), lerp(1.0, 1.06, inout(lt / 2))); readmeShot(t);}},   // без whip = панч
  ];
  for (let i = 1; i < shots.length; i++) if (!(shots[i].at > shots[i - 1].at)) throw new Error('склейки не по порядку: ' + i);
  window.shotTimes = shots.map(x => x.at);
  window.events = E;

  // ---------- субтитры по слову: мелкая строка + крупная, акцент антиквой, цифры лаймом ----------
  const ACC = new Set(['кода', 'монтажки', 'скрипт', 'инструкции']);
  type Ph = {words: Word[]; start: number; end: number};
  const phrases: Ph[] = [];
  {let cur: Word[] = []; const flush = () => {if (cur.length) phrases.push({words: cur, start: cur[0].start, end: cur[cur.length - 1].end}); cur = [];};
    W.forEach((w, i) => {if (cur.length && cur[0].line !== w.line) flush(); cur.push(w); const n = W[i + 1];
      if ((/[.,:!?»]$/.test(w.text) && cur.length >= 2) || cur.length >= 5 || (n && n.start - w.end > .3)) flush();});
    flush(); phrases.forEach((p, i) => {const n = phrases[i + 1]; p.end = n ? Math.min(n.start - .02, p.end + .7) : END;});}
  function captions(t: number) {
    const p = phrases.find(x => t >= x.start - .06 && t < x.end); if (!p) return;
    const fade = 1 - clamp((t - p.end + .12) / .12);
    const parts = p.words.map(w => {const n = norm(w.text), num = /^\d+$/.test(n), acc = ACC.has(n);
      const fam = acc ? ACCENT : SANS, size = num ? 96 : acc ? 84 : 76; out.font = `${acc ? 'italic 400' : 700} ${size}px ${fam}`;
      return {w, fam, size, num, acc, width: out.measureText(w.text).width};});
    const gap = 22, lines: (typeof parts)[] = [[]]; let lw = 0;      // перенос, если строка шире 960 px
    for (const q of parts) {if (lw + q.width > 960 && lines[lines.length - 1].length) {lines.push([]); lw = 0;} lines[lines.length - 1].push(q); lw += q.width + gap;}
    out.save(); out.shadowColor = 'rgba(0,0,0,.75)'; out.shadowBlur = 24; out.textAlign = 'left';
    lines.forEach((ln, li) => {let x = 540 - (ln.reduce((a, q) => a + q.width, 0) + gap * (ln.length - 1)) / 2; const y = 330 + li * 104;
      for (const q of ln) {const k = clamp((t - q.w.start + .04) / .14);   // слово проявляется к моменту, когда его произносят
        if (k > 0) {out.globalAlpha = fade * k; out.font = `${q.acc ? 'italic 400' : 700} ${q.size}px ${q.fam}`;
          out.fillStyle = q.num ? LIME : WHITE; out.fillText(q.w.text, x, y + (1 - ease(k)) * 18);}
        x += q.width + gap;}});
    out.restore();
  }

  // ---------- кадр целиком ----------
  function render(t: number) {
    let i = 0; for (let k = 0; k < shots.length; k++) if (t >= shots[k].at) i = k;
    const sh = shots[i], lt = t - sh.at;
    c.setTransform(1, 0, 0, 1, 0, 0); c.globalAlpha = 1; noGlow(); c.clearRect(0, 0, FW, FH); c.save(); sh.draw(t, lt); c.restore();
    out.setTransform(1, 0, 0, 1, 0, 0); out.globalAlpha = 1; out.fillStyle = '#000'; out.fillRect(0, 0, FW, FH);
    // ручная камера: сумма синусов с некратными частотами — дрожь живая, но повторяемая
    const hs = 1.04 + .03 * ease(lt / 3) + .012 * Math.sin(t * 1.3);
    const hx = sines(t, [[16, .8, 0], [7, 2.1, 1]]), hy = sines(t, [[13, .7, 2], [5, 1.7, 0]]), hr = sines(t, [[.007, .6, 0]]);
    const put = (sc: number, dx: number, alpha = 1) => {out.globalAlpha = alpha; out.setTransform(1, 0, 0, 1, 0, 0);
      out.translate(FW / 2 + hx + dx, FH / 2 + hy); out.rotate(hr); out.scale(hs * sc, hs * sc); out.drawImage(world, -FW / 2, -FH / 2);};
    const TW = .2, wd = sh.whip ?? 0;
    if (i > 0 && wd !== 0 && lt < TW) {      // whip: 0,2 с, кадр въезжает со сдвигом 420 px и четырьмя «шлейфами» по 22 %
      const k = 1 - ease(lt / TW); for (let g = 0; g < 5; g++) put(1 + k * .08, wd * k * 420 + wd * g * k * 60, g === 0 ? 1 : .22);
    } else if (i > 0 && lt < .16) put(1 + (1 - ease(lt / .16)) * .06, 0);   // панч: +6 % масштаба, спадает за 0,16 с
    else put(1, 0);
    out.globalAlpha = 1; out.setTransform(1, 0, 0, 1, 0, 0);
    const v = out.createRadialGradient(540, 960, 600, 540, 960, 1300); v.addColorStop(0, 'rgba(0,0,0,0)'); v.addColorStop(1, 'rgba(0,0,0,.45)');
    out.fillStyle = v; out.fillRect(0, 0, FW, FH);                                   // виньетка
    const top = out.createLinearGradient(0, 0, 0, 640); top.addColorStop(0, 'rgba(0,0,0,.55)'); top.addColorStop(1, 'rgba(0,0,0,0)');
    out.fillStyle = top; out.fillRect(0, 0, FW, 640);                                // подложка под субтитры
    const fr = Math.floor(t * 30);                                                   // зерно: сдвиг текстуры зависит от номера кадра
    out.globalAlpha = .07; out.globalCompositeOperation = 'overlay'; out.drawImage(grain, -(fr * 37 % 200), -(fr * 91 % 300), FW + 400, FH + 600);
    out.globalCompositeOperation = 'source-over'; out.globalAlpha = 1;
    captions(t);
  }
  window.setTime = async (t: number) => render(clamp(t, 0, END));
  await window.setTime(0); window.ready = true;
}
main().catch(e => {console.error(e); throw e;});
