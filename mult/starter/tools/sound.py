"""Звук ролика: голос + музыка с даккингом + синтезированные SFX -> assets/audio/master.wav (−15 LUFS, пик ≤ −1,5 dBTP).
Сэмплов нет: каждый звук — несколько строк numpy (синус с затуханием, полосовой шум, их сумма).
Где ставить звук, берём из сцены: qa/shots.json (склейки) и qa/events.json (метки по словам). Их пишет tools/render.py --probe.

Запуск (из папки starter): python3 locked.py render -- $PY tools/sound.py
Чтобы добавить звук: найди метку в window.events (scene.ts, объект E) и допиши put(sfx, E['метка'], звук, громкость)."""
import json, subprocess
from pathlib import Path
import numpy as np, soundfile as sf
from scipy.signal import butter, sosfilt

P = Path(__file__).resolve().parent.parent
SR = 48000
rng = np.random.default_rng(1023)                     # сид: звук собирается одинаково при каждом запуске


def run(c): subprocess.run(c, check=True, capture_output=True)


# ---------- каркас: четыре функции ----------
def T(d): return np.arange(int(d * SR)) / SR
def sine(f, d, decay):            # тон f Гц длиной d с, экспоненциальное затухание, атака 3 мс (без щелчка)
    t = T(d); return np.sin(2 * np.pi * f * t) * np.exp(-t * decay) * np.minimum(1, t / .003)
def bp(x, lo, hi):                # полосовой фильтр Баттерворта 2-го порядка
    return sosfilt(butter(2, [lo, hi], btype='band', fs=SR, output='sos'), x)
def noise(d, decay):              # белый шум с затуханием
    return rng.normal(size=len(T(d))) * np.exp(-T(d) * decay)
def add(a, b):                    # сложить звуки разной длины
    o = np.zeros(max(len(a), len(b))); o[:len(a)] += a; o[:len(b)] += b; return o


# ---------- палитра ----------
def whoosh(d=.42):                # «вжух» на склейку: шум переезжает из низкой полосы в высокую, громкость колоколом
    n = int(d * SR); t = np.arange(n) / n; w = rng.normal(size=n)
    return (bp(w, 300, 1400) * (1 - t) + bp(w, 1400, 7000) * t) * np.sin(np.pi * t) ** 2
click = bp(noise(.03, 170), 1800, 8000) * .8 + np.pad(sine(2600, .02, 240), (0, int(.01 * SR))) * .3
key = lambda: bp(noise(.025, 220), 1500, 6000) * .7          # клавиша: каждый вызов — новый шум, звучит не одинаково
tick = sine(3400, .018, 300) * .5                               # тик счётчика
thud = add(sine(62, .4, 10), bp(noise(.14, 32), 80, 900) * .9) * .9   # удар: низкий синус + глухой шум
def pop(f=900): return add(sine(f, .09, 40) * .6, bp(noise(.02, 300), 2000, 7000) * .2)
def chord(fs, d=.9, decay=4): return sum(sine(f, d, decay) for f in fs) / len(fs)


def pad_music(n):
    """Запасная музыка, если в reel.json нет трека: четыре аккорда по 2 с, мягкая атака. Своя, без лицензий."""
    prog = [[220, 277, 330], [196, 247, 294], [175, 220, 262], [196, 247, 311]]; m = np.zeros(n)
    for j in range(n // (2 * SR) + 1):
        seg = sum(np.sin(2 * np.pi * f * T(2.0)) + .3 * np.sin(4 * np.pi * f * T(2.0)) for f in prog[j % 4]) / 4
        seg *= np.minimum(1, T(2.0) / .3) * np.minimum(1, (2.0 - T(2.0)) / .3)
        a = j * 2 * SR; b = min(n, a + len(seg)); m[a:b] += seg[:b - a]
    return np.stack([m, m], 1) * .25


def main():
    s = json.loads((P / 'story.json').read_text()); reel = json.loads((P / 'reel.json').read_text())
    E = json.loads((P / 'qa/events.json').read_text()); shots = json.loads((P / 'qa/shots.json').read_text())
    n = round(s['duration'] * SR); audio = P / 'assets/audio'
    if reel['music'].get('file'):
        run(['ffmpeg', '-y', '-v', 'error', '-stream_loop', '-1', '-ss', str(reel['music'].get('offset', 0)), '-i', str(P / reel['music']['file']),
             '-t', str(s['duration']), '-ar', str(SR), '-ac', '2', str(audio / 'music-cut.wav')])
        m, _ = sf.read(audio / 'music-cut.wav'); music = np.zeros((n, 2)); music[:min(n, len(m))] = m[:n]
    else:
        music = pad_music(n)
    speech, sfx, duck = np.zeros((n, 2)), np.zeros((n, 2)), np.ones(n)

    def put(track, at, x, g=1., pan=0.):     # положить звук x на дорожку в момент at (с), громкость g, панорама −1..1
        a = round(at * SR); a0 = max(0, a); b = min(n, a + len(x))
        if b > a0:
            v = x[a0 - a:b - a] * g; track[a0:b, 0] += v * np.sqrt((1 - pan) / 2) * 1.414; track[a0:b, 1] += v * np.sqrt((1 + pan) / 2) * 1.414

    # голос: выровнять до −18 LUFS, положить с нуля (паузы уже внутри voice-track.wav)
    run(['ffmpeg', '-y', '-v', 'error', '-i', str(P / s['voice_track']), '-af', 'loudnorm=I=-18:TP=-4:LRA=7', '-ar', str(SR), '-ac', '1', str(audio / 'normalized-track.wav')])
    x, _ = sf.read(audio / 'normalized-track.wav'); put(speech, 0, x, .9)
    # даккинг: под репликой музыка ×0,3, огибающая сглажена окном 0,25 с (иначе «качает»)
    for c in s['cues']: duck[round(c['start'] * SR):round(c['end'] * SR)] = .3
    k = np.ones(int(.25 * SR)) / int(.25 * SR); duck = np.convolve(duck, k, mode='same')
    music *= duck[:, None] * reel['music'].get('gain', .3)

    # ---------- расстановка: склейки + события сцены ----------
    for at in shots[1:]: put(sfx, at - .2, whoosh(), .16, rng.uniform(-.5, .5))      # вжух начинается за 0,2 с до склейки
    t = E['l0'] + .1
    while t < E['l0'] + .7: put(sfx, t, key(), .18, rng.uniform(-.3, .3)); t += rng.uniform(.05, .09)   # печать команды
    for i in range(4): put(sfx, E['kod'] + .12 * i, pop(700 + 120 * i), .22)          # строки «✓»
    put(sfx, E['montazh'] + .05, thud, .45); put(sfx, E['montazh'] + .05, chord([196, 233], .7, 4), .2)   # крест
    for j, at in enumerate([E['golos'], E['kadry'], E['zvuk']]): put(sfx, at - .05, pop(800 + 150 * j), .3)
    put(sfx, E['paru'], click, .35)
    t = E['n200'] - .05
    while t < E['n200End'] + .3: put(sfx, t, tick, .14); t += .045                     # счётчик 0 -> 200
    put(sfx, E['n200End'] + .3, thud, .4); put(sfx, E['n200End'] + .3, pop(1300), .3)
    for i in range(3): put(sfx, E['povtori'] + .1 + .25 * i, click, .4); put(sfx, E['povtori'] + .13 + .25 * i, pop(1000 + 100 * i), .2)
    put(sfx, E['povtori'] + .9, chord([523, 784, 1046], 1.2, 2.5), .25)                 # финальный аккорд

    fade = np.minimum(1, np.arange(n) / (.03 * SR)) * np.minimum(1, (n - np.arange(n)) / (.5 * SR))
    mix = (music + speech + sfx) * fade[:, None]; sf.write(audio / 'mix.wav', mix, SR, subtype='PCM_24')
    # мастер: громкость под площадки −15 LUFS; лимитер страхует пики
    run(['ffmpeg', '-y', '-v', 'error', '-i', str(audio / 'mix.wav'), '-af', 'loudnorm=I=-15:TP=-3:LRA=7,alimiter=limit=0.7:level=false',
         '-ar', str(SR), '-ac', '2', str(audio / 'master.wav')])
    print('master', audio / 'master.wav', s['duration'], 's')


if __name__ == '__main__':
    main()
