"""Синтез реплик клоном голоса OmniVoice (k2-fsa) -> voice/raw-N.wav.
Читает voice/chunks.json: [{"text": "...", "pause": 0.12}, ...]. Одна реплика = один дубль.

Окружение (все пути через переменные, абсолютных путей в коде нет):
  OMNI_MODEL   папка с весами k2-fsa/OmniVoice (скачать с Hugging Face; веса CC-BY-NC — только некоммерчески)
  OMNI_REF     референс голоса .wav (10-20 с чистой речи); рядом обязателен .txt с точной расшифровкой
  OMNI_SPEED   родной параметр темпа модели, 1.0 по умолчанию; 1.1 — если рил не влезает. НЕ ускорять ffmpeg atempo
  OMNI_DEVICE  mps (Apple Silicon, по умолчанию) | cuda | cpu

Запуск (из папки starter):
  python3 locked.py voice -- $OMNI_PY voice/gen_omni.py        # все реплики
  python3 locked.py voice -- $OMNI_PY voice/gen_omni.py 1 2    # только реплики 1 и 2

Обрыв окончания: если последние 30 мс громче (пик −30 dB), слово срезано. Тогда дубль переделывается
с жертвенным хвостом «Вот так вот.», а trim.py потом отрезает хвост по ASR. В chunks.json пишется tail: true/false.
Сид фиксирован (42): тот же текст даёт тот же дубль. Плохой дубль лечится правкой текста, не перебором сидов."""
import json, os, sys
from pathlib import Path
import numpy as np, soundfile as sf, torch

P = Path(__file__).resolve().parent.parent          # папка проекта ролика (starter/)
OUT = P / 'voice'
TAIL = 'Вот так вот.'
SR = 24000                                          # частота выхода OmniVoice
SPEED = float(os.environ.get('OMNI_SPEED', '1.0'))
DEVICE = os.environ.get('OMNI_DEVICE', 'mps')


def env_path(name):
    v = os.environ.get(name)
    if not v or not Path(v).exists():
        sys.exit(f'{name} не задан или не существует: {v!r}. См. README, шаг «Голос».')
    return Path(v)


def clipped(x, sr):
    """True, если речь обрывается прямо на конце файла (последние 30 мс громче пик −30 dB)."""
    hop = int(.01 * sr)
    db = np.array([20 * np.log10(np.sqrt(np.mean(x[i:i + hop] ** 2)) + 1e-9) for i in range(0, len(x) - hop, hop)])
    nz = np.nonzero(db > db.max() - 50)[0]
    last = db[nz[-1] - 2:nz[-1] + 1]
    return bool(nz[-1] >= len(db) - 4 and last.max() > db.max() - 30)


def main():
    from omnivoice import OmniVoice
    model_dir, ref = env_path('OMNI_MODEL'), env_path('OMNI_REF')
    ref_txt = ref.with_suffix('.txt')
    if not ref_txt.exists():
        sys.exit(f'нет расшифровки референса {ref_txt}')
    chunks = json.loads((OUT / 'chunks.json').read_text())
    dtype = torch.float32 if DEVICE == 'cpu' else torch.float16
    m = OmniVoice.from_pretrained(str(model_dir), device_map=DEVICE, dtype=dtype)    # ~1 мин на загрузку
    prompt = m.create_voice_clone_prompt(ref_audio=str(ref), ref_text=ref_txt.read_text().strip())
    only = [int(a) for a in sys.argv[1:] if a.isdigit()]
    for i in (only or range(len(chunks))):
        ch = chunks[i]
        for tail in (False, True):
            torch.manual_seed(42); np.random.seed(42)
            text = ch['text'] + (' ' + TAIL if tail else '')
            x = np.asarray(m.generate(text=text, voice_clone_prompt=prompt, speed=None if SPEED == 1.0 else SPEED)[0], dtype=np.float32).squeeze()
            if tail or not clipped(x, SR):
                break
            print(i, 'конец рвётся, повтор с хвостом', flush=True)
        sf.write(OUT / f'raw-{i}.wav', x, SR)
        ch['tail'] = tail; ch['engine'] = 'omnivoice'; ch['omni_speed'] = SPEED
        print(i, f'{len(x) / SR:.2f}s tail={tail}', flush=True)
    (OUT / 'chunks.json').write_text(json.dumps(chunks, ensure_ascii=False, indent=1) + '\n')


if __name__ == '__main__':
    main()
