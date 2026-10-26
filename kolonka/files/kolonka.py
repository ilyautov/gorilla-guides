"""Колонка Горо: своя «Алиса» на Claude. Голос → текст локально (faster-whisper),
ответ через `claude -p` по подписке (без инструментов), текст → голос локально (macOS say или OmniVoice).

Запуск (из папки kolonka/):
  ./run.sh                    — push-to-talk: Enter начать, Enter закончить
  ./run.sh --wake             — слово-будильник «Горо» (Vosk, офлайн), потом говорите вопрос
  ./run.sh --wav a.wav b.wav  — тест на файлах без микрофона, печатает замеры
  ./run.sh --text "вопрос"    — без ASR, проверить Claude и голос
Флаги: --asr-model small|base|medium, --model sonnet|haiku (haiku быстрее на ~0,5 с, но ошибается чаще), --tts say|omnivoice, --voice Milena, --no-speak.
"""
import argparse, collections, json, os, queue, re, subprocess, sys, tempfile, threading, time, wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SR = 16000
SYSTEM_PROMPT = (HERE / 'prompt.txt').read_text(encoding='utf-8').strip()
VOSK_MODEL = HERE / 'models/vosk-model-small-ru-0.22'
WAKE_WORDS = {'горо', 'гора', 'гор', 'горе'}  # в словаре Vosk нет «горо», он слышит «гора»
BEEP = '/System/Library/Sounds/Tink.aiff'


def log(*a):
    print(*a, flush=True)


# ---------- ASR ----------
class ASR:
    def __init__(self, name):
        from faster_whisper import WhisperModel
        t = time.time()
        self.m = WhisperModel(name, device='cpu', compute_type='int8')
        log(f'[asr] faster-whisper {name} загружен за {time.time() - t:.1f} с')

    def __call__(self, audio):  # путь к wav или float32 numpy 16 кГц
        segs, _ = self.m.transcribe(audio, language='ru', beam_size=1, vad_filter=False)
        return ' '.join(s.text.strip() for s in segs).strip()


# ---------- Claude ----------
class Claude:
    """`claude -p` без инструментов, без MCP, без CLAUDE.md и плагинов (--safe-mode), без записи сессий.
    ANTHROPIC_API_KEY из окружения убираем, чтобы шло по подписке, а не по ключу."""

    def __init__(self, model, history=3):
        self.model, self.history, self.turns = model, history, []
        self.cwd = tempfile.mkdtemp(prefix='kolonka-')  # пустая папка: Claude не видит файлов проекта
        self.env = {k: v for k, v in os.environ.items() if k not in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN')}
        self.env['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'] = '1'  # без телеметрии и фоновых запросов Claude Code

    def __call__(self, text):
        ctx = ''.join(f'Пользователь: {q}\nТы: {a}\n' for q, a in self.turns[-self.history:])
        prompt = (f'Предыдущие реплики:\n{ctx}\nНовый вопрос: {text}' if ctx else text)
        cmd = ['claude', '-p', '--safe-mode', '--tools', '', '--strict-mcp-config', '--no-session-persistence',
               '--model', self.model, '--effort', 'low', '--system-prompt', SYSTEM_PROMPT, '--output-format', 'text', prompt]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=self.cwd, env=self.env, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(f'claude -p упал ({r.returncode}): {r.stderr.strip()[:300] or r.stdout.strip()[:300]}')
        ans = clean(r.stdout)
        self.turns.append((text, ans))
        return ans


def clean(s):
    s = re.sub(r'[*_#`>]+', '', s)          # markdown вслух не читаем
    s = re.sub(r'https?://\S+', '', s)
    return ' '.join(s.split())


# ---------- TTS ----------
class SayTTS:
    def __init__(self, voice, rate):
        self.voice, self.rate = voice, rate

    def synth(self, text, out):
        subprocess.run(['say', '-v', self.voice, '-r', str(self.rate), '-o', out, '--file-format=WAVE', '--data-format=LEI16@22050', text], check=True)


class OmniTTS:
    """OmniVoice держим загруженным в отдельном процессе (своя среда .runtime/tts-omnivoice) под общим замком voice."""

    def __init__(self, ref):
        py = ROOT / '.runtime/tts-omnivoice/venv/bin/python'
        if not py.exists():
            sys.exit('OmniVoice не установлен (нужна среда .runtime/tts-omnivoice из video-pipeline-agent). Без него: --tts say')
        cmd = [sys.executable, str(ROOT / 'quick-common/locked.py'), 'voice', '--', str(py), str(HERE / 'omni_worker.py'), str(ref)]
        t = time.time()
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, cwd=ROOT)
        line = self._read()
        if line != 'READY':
            raise RuntimeError(f'OmniVoice не поднялся: {line!r}')
        log(f'[tts] OmniVoice загружен за {time.time() - t:.1f} с')

    def _read(self):  # библиотеки иногда печатают в stdout; ждём только наши служебные строки
        while (line := self.p.stdout.readline()):
            line = line.strip()
            if line in ('READY', 'OK') or line.startswith('ERR'): return line
        return 'EOF'

    def synth(self, text, out):
        self.p.stdin.write(json.dumps({'text': text, 'out': out}, ensure_ascii=False) + '\n'); self.p.stdin.flush()
        r = self._read()
        if r != 'OK':
            raise RuntimeError(f'OmniVoice: {r}')


def play(path):
    subprocess.run(['afplay', path])


# ---------- микрофон ----------
def mic_check(sd, np):
    """macOS без разрешения на микрофон не падает, а отдаёт тишину из нулей. Ловим это явно."""
    try:
        x = sd.rec(int(0.5 * SR), samplerate=SR, channels=1, dtype='float32'); sd.wait()
    except Exception as e:
        stop_mic(f'PortAudio не открыл микрофон: {e}')
    if float(np.abs(x).max()) == 0.0:
        stop_mic('микрофон отдаёт ровные нули — похоже, macOS не дал доступ.')


def stop_mic(why):
    log(f'\n[микрофон] {why}\n'
        'Что сделать: Системные настройки → Конфиденциальность и безопасность → Микрофон →\n'
        'включить переключатель у приложения, из которого запускаете (Терминал, iTerm, VS Code),\n'
        'закрыть это приложение полностью (Cmd+Q) и открыть снова. Затем ./run.sh ещё раз.\n'
        'Пока без микрофона работает ./run.sh --wav файл.wav и ./run.sh --text "вопрос".')
    sys.exit(2)


def record_ptt(sd, np):
    input('\n⏎ Enter — говорить (Ctrl+C — выход) ')
    chunks = []
    with sd.InputStream(samplerate=SR, channels=1, dtype='float32', callback=lambda d, *_: chunks.append(d.copy())):
        input('● Слушаю… Enter — готово ')
    return np.concatenate(chunks).ravel() if chunks else np.zeros(0, 'float32')


def wake_listen(chunks, np, rec_vosk, beep=True, silence=1.0, max_s=12.0):
    """chunks — поток кусков int16 по 0,25 с (микрофон или файл). Ждём «Горо» через Vosk (офлайн),
    потом копим фразу до секунды тишины. Хвост после «Горо» не выбрасываем: «Горо, который час?» можно сказать слитно."""
    rec_vosk.Reset()
    floor = 1.0  # минимальная громкость, пока ждём слово: оценка шума комнаты
    pre = collections.deque(maxlen=8)  # последние 2 с до срабатывания: в них начало фразы
    for d in chunks:
        pre.append(d)
        x = np.frombuffer(d, 'int16').astype('float32') / 32768
        floor = min(floor, float(np.sqrt((x ** 2).mean())) or floor)
        done = rec_vosk.AcceptWaveform(d)
        words = json.loads(rec_vosk.Result() if done else rec_vosk.PartialResult()).get('text' if done else 'partial', '').split()
        if WAKE_WORDS & set(words):
            break
    else:
        return None
    rec_vosk.Reset()
    if beep: subprocess.Popen(['afplay', BEEP])
    log('● Слушаю…')
    thr = max(0.01, floor * 3)
    buf = [np.frombuffer(d, 'int16').astype('float32') / 32768 for d in pre]
    quiet, n, spoke = 0.0, 0, False
    for d in chunks:
        x = np.frombuffer(d, 'int16').astype('float32') / 32768
        buf.append(x); n += len(x)
        e = float(np.sqrt((x ** 2).mean()))
        speaking = e > thr
        spoke |= speaking
        quiet = 0.0 if speaking else quiet + len(x) / SR
        if (spoke and quiet >= silence) or n >= max_s * SR or (not spoke and n >= 5 * SR): break
    return np.concatenate(buf) if spoke else np.zeros(0, 'float32')


def mic_chunks(q):
    while True: yield q.get()


def file_chunks(path, pad_s=3.0):
    """Подаём wav как будто с микрофона, с тишиной в конце."""
    w = wave.open(str(path)); assert w.getframerate() == SR and w.getnchannels() == 1
    while (d := w.readframes(4000)): yield d
    for _ in range(int(pad_s * 4)): yield bytes(8000)


def vosk_recognizer():
    from vosk import Model, KaldiRecognizer, SetLogLevel
    SetLogLevel(-1)
    if not VOSK_MODEL.exists(): sys.exit('Нет модели Vosk: запустите ./setup.sh')
    return KaldiRecognizer(Model(str(VOSK_MODEL)), SR)


def strip_wake(text):
    return re.sub(r'^\s*(горо|гора|гор|горе|go?ro)\b[\s,.!?…-]*', '', text, flags=re.I).strip()


# ---------- цикл ----------
def turn(asr, claude, tts, audio=None, text=None, speak=True):
    m = {}
    if text is None:
        t = time.time(); text = strip_wake(asr(audio)); m['asr'] = time.time() - t
    log(f'Вы: {text}')
    if not text:
        log('(ничего не расслышал)'); return m
    t = time.time(); ans = claude(text); m['claude'] = time.time() - t
    log(f'Горо: {ans}')
    out = tempfile.mktemp(suffix='.wav', prefix='kolonka-')
    t = time.time(); tts.synth(ans, out); m['tts'] = time.time() - t
    m['total'] = sum(m.values())
    log('[замер] ' + ' · '.join(f'{k} {v:.2f} с' for k, v in m.items()))
    if speak: play(out)
    os.unlink(out)
    m.update(question=text, answer=ans)
    return m


def main():
    ap = argparse.ArgumentParser(description='Колонка Горо на Claude')
    ap.add_argument('--wav', nargs='+'); ap.add_argument('--text')
    ap.add_argument('--wake', action='store_true')
    ap.add_argument('--asr-model', default='small'); ap.add_argument('--model', default='sonnet')
    ap.add_argument('--tts', default='say', choices=['say', 'omnivoice'])
    ap.add_argument('--voice', default='Milena'); ap.add_argument('--rate', type=int, default=190)
    ap.add_argument('--omni-ref', default=str(ROOT / 'voice-live/refs/ref-03-dc.wav'))
    ap.add_argument('--no-speak', action='store_true'); ap.add_argument('--json', help='сохранить замеры в файл')
    a = ap.parse_args()

    tts = OmniTTS(a.omni_ref) if a.tts == 'omnivoice' else SayTTS(a.voice, a.rate)
    claude = Claude(a.model)
    if a.text:
        turn(None, claude, tts, text=a.text, speak=not a.no_speak); return
    asr = ASR(a.asr_model)
    if a.wav and a.wake:  # проверка будильника на файле: «… Горо, вопрос»
        rec = vosk_recognizer()
        for f in a.wav:
            ch = file_chunks(f)
            audio = wake_listen(ch, __import__('numpy'), rec, beep=False)
            if audio is None: log(f'{f}: «Горо» не услышан'); continue
            if not len(audio): log(f'{f}: «Горо» услышан, но вопроса нет'); continue
            log(f'{f}: «Горо» услышан, фраза {len(audio) / SR:.1f} с')
            turn(asr, claude, tts, audio=audio, speak=not a.no_speak)
        return
    if a.wav:
        rows = [turn(asr, claude, tts, audio=f, speak=not a.no_speak) for f in a.wav]
        if a.json: Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
        return

    import numpy as np, sounddevice as sd
    mic_check(sd, np)
    rec_vosk = mic_q = stream = None
    if a.wake:
        rec_vosk = vosk_recognizer()
        mic_q = queue.Queue()
        stream = sd.RawInputStream(samplerate=SR, channels=1, dtype='int16', blocksize=4000, callback=lambda d, *_: mic_q.put(bytes(d)))
        stream.start()
    log('Колонка Горо готова. Звук не уходит из Mac: в Claude отправляется только распознанный текст.')
    try:
        while True:
            if a.wake:
                while not mic_q.empty(): mic_q.get_nowait()  # выкидываем звук, пока колонка думала и говорила сама
                log('\n… жду «Горо»')
                audio = wake_listen(mic_chunks(mic_q), np, rec_vosk)
            else:
                audio = record_ptt(sd, np)
            if len(audio) < SR * 0.3: log('(слишком коротко)'); continue
            if float(abs(audio).max()) == 0.0: stop_mic('записалась абсолютная тишина.')
            try:
                turn(asr, claude, tts, audio=audio, speak=not a.no_speak)
            except Exception as e:
                log(f'[ошибка] {e}')
    except (KeyboardInterrupt, EOFError):
        log('\nПока!')


if __name__ == '__main__':
    main()
