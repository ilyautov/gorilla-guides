"""Заглушка голоса без синтеза: voice-track.json + assets/audio/voice-track.wav из voice/lines.json.
Каждое показанное слово = тихий гудок длиной по числу букв. Нужна, чтобы проверить сцену, звук и рендер
до установки OmniVoice и Whisper. Формат файла тот же, что пишет voice/trim.py.
Запуск: python3 voice/fake_track.py   (нужны numpy и soundfile)"""
import hashlib, json, re
from pathlib import Path
import numpy as np, soundfile as sf

P = Path(__file__).resolve().parent.parent
SR = 44100
LEAD, WORD_GAP, LINE_GAP, TAIL_SIL = 0.10, 0.06, 0.35, 0.7


def main():
    lines = json.loads((P / 'voice/lines.json').read_text())
    words, cues, t, audio = [], [], LEAD, []
    for li, line in enumerate(lines):
        st = t
        for tok in line.split():
            m = re.match(r'^(.*?)\{(\d+)\}([.,:!?]*)$', tok)
            text = (m.group(1) + m.group(3) if m else tok).replace('_', ' ')
            if not text.strip('—–-'): continue
            d = 0.12 + 0.045 * len(re.sub(r'\W', '', text))         # длинное слово звучит дольше
            words.append({'line': li, 'text': text, 'say': text, 'start': round(t, 3), 'end': round(t + d, 3)})
            t += d + WORD_GAP + (0.18 if text[-1] in '.,:!?' else 0)
        cues.append({'id': li, 'start': round(st, 3), 'end': words[-1]['end'], 'text': line, 'show': line})
        t = words[-1]['end'] + LINE_GAP
    total = words[-1]['end'] + TAIL_SIL
    x = np.zeros(int(total * SR), dtype=np.float32)
    for w in words:   # гудок 180 Гц с мягкими краями, чтобы громкость и даккинг были похожи на речь
        a, b = int(w['start'] * SR), int(w['end'] * SR); n = b - a; tt = np.arange(n) / SR
        x[a:b] += (0.25 * np.sin(2 * np.pi * 180 * tt) * np.sin(np.pi * np.arange(n) / n)).astype(np.float32)
    wav = P / 'assets/audio/voice-track.wav'; wav.parent.mkdir(parents=True, exist_ok=True); sf.write(wav, x, SR)
    out = {'file': 'assets/audio/voice-track.wav', 'sha256': hashlib.sha256(wav.read_bytes()).hexdigest(), 'duration': round(total, 3),
           'cues': cues, 'words': words, 'asr_text': '', 'fake': True}
    (P / 'voice-track.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print('fake voice-track', round(total, 2), 's,', len(words), 'слов')


if __name__ == '__main__':
    main()
