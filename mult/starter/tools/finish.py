"""Сведение и QA: output/picture.mp4 + assets/audio/master.wav -> output/final.mp4, потом проверки:
  - ffmpeg -xerror: файл декодируется без ошибок;
  - faststart: moov в начале файла (площадки начинают показ, не докачав весь файл);
  - громкость ebur128: интегральная −15 ±1 LUFS, true peak ≤ −1,5 dBTP;
  - статика: самый длинный кусок, где кадр почти не меняется (> 1,5 с = зритель уходит);
  - ASR финала (faster-whisper) против текста реплик: ratio ≥ 0,9;
  - контактный лист qa/sheet.jpg (кадр каждые 0,75 с с меткой времени);
  -> qa/final-result.json. technical_pass = все проверки зелёные. Это НЕ одобрение: artistic_approval и
     publication_approved ставит только человек, посмотрев ролик.
Запуск (из папки starter): python3 locked.py render -- $PY tools/finish.py [--no-asr]
--no-asr: для заглушки fake_track.py (гудки вместо речи) или если Whisper ещё не поставлен."""
import argparse, difflib, hashlib, json, os, re, subprocess
from pathlib import Path
import numpy as np

P = Path(__file__).resolve().parent.parent
OUT = P / 'output/final.mp4'
NUM = {'200': 'двести'}            # как ASR пишет цифры -> как в тексте (тот же словарь, что в voice/trim.py)


def run(c): return subprocess.run(c, check=True, capture_output=True, text=True)


def sheet(step=.75, cols=8):
    from PIL import Image, ImageDraw, ImageFont
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(OUT), '-vf', f'fps=1/{step},scale=270:480', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 480, 270, 3); rows = (len(fr) + cols - 1) // cols
    im = Image.new('RGB', (270 * cols, 480 * rows)); dr = ImageDraw.Draw(im)
    font = None
    for f in ('/System/Library/Fonts/Menlo.ttc', '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'):
        if os.path.exists(f): font = ImageFont.truetype(f, 22); break
    font = font or ImageFont.load_default()
    for i, f in enumerate(fr):
        x, y = 270 * (i % cols), 480 * (i // cols); im.paste(Image.fromarray(f), (x, y))
        dr.rectangle([x, y, x + 84, y + 28], fill=(0, 0, 0)); dr.text((x + 4, y + 2), f'{i * step + step / 2:5.2f}', fill=(255, 230, 0), font=font)
    im.save(P / 'qa/sheet.jpg', quality=85)


def longest_still(fps):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(OUT), '-vf', 'scale=135:240,format=gray', '-f', 'rawvideo', '-'], capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 240, 135).astype(np.float32)
    still = np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2)) < 0.15     # средняя разница соседних кадров < 0,15 из 255
    longest = cur = at = 0
    for i, st in enumerate(still):
        cur = cur + 1 if st else 0
        if cur > longest: longest, at = cur, i - cur + 1
    return round(longest / fps, 2), round(at / fps, 2)


def asr_check(vt):
    from faster_whisper import WhisperModel
    asr = WhisperModel(os.environ.get('ASR_MODEL', 'large-v3'), device='cpu', compute_type='int8')
    segs, _ = asr.transcribe(str(OUT), language='ru', beam_size=5)
    text = ' '.join(x.text.strip() for x in segs)
    nz = lambda x: [NUM.get(w, w) for w in re.sub(r'[^a-zа-я0-9 ]', ' ', x.lower().replace('ё', 'е').replace('-', ' ')).split() if w]
    want = nz(' '.join(c['text'] for c in vt['cues'])); got = nz(text)
    return text, round(difflib.SequenceMatcher(None, want, got, autojunk=False).ratio(), 3)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--no-asr', action='store_true'); a = ap.parse_args()
    run(['ffmpeg', '-y', '-v', 'error', '-i', str(P / 'output/picture.mp4'), '-i', str(P / 'assets/audio/master.wav'), '-map', '0:v', '-map', '1:a',
         '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-shortest', '-movflags', '+faststart', str(OUT)])
    pr = json.loads(run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=width,height,r_frame_rate,codec_type', '-of', 'json', str(OUT)]).stdout)
    dur = float(pr['format']['duration']); vs = next(x for x in pr['streams'] if x['codec_type'] == 'video')
    num, den = map(int, vs['r_frame_rate'].split('/')); fps = num / den
    xerr = subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(OUT), '-f', 'null', '-'], capture_output=True, text=True)
    sheet(); still, still_at = longest_still(fps)
    eb = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(OUT), '-af', 'ebur128=peak=true', '-f', 'null', '-'], capture_output=True, text=True).stderr
    I = float(re.findall(r'I:\s+(-?[\d.]+) LUFS', eb)[-1]); TP = float(re.findall(r'Peak:\s+(-?[\d.]+) dBFS', eb)[-1]); LRA = float(re.findall(r'LRA:\s+(-?[\d.]+) LU', eb)[-1])
    vt = json.loads((P / 'voice-track.json').read_text()); reel = json.loads((P / 'reel.json').read_text())
    asr_text, asr_ratio = ('', None) if a.no_asr else asr_check(vt)
    size_mb = round(OUT.stat().st_size / 1e6, 1)
    head = OUT.read_bytes()[:200000]; faststart = head.find(b'moov') != -1 and (head.find(b'mdat') == -1 or head.find(b'moov') < head.find(b'mdat'))
    checks = {'decodes': xerr.returncode == 0, 'faststart': faststart, 'loudness': abs(I + 15) <= 1 and TP <= -1.5, 'static_le_1_5s': still <= 1.5,
              'duration_ok': dur <= reel.get('max_duration', 60), 'size_le_100mb': size_mb <= 100, 'asr_ge_0_9': None if a.no_asr else asr_ratio >= .9}
    res = {'status': 'ready_for_user_preview', 'technical_pass': all(v is not False for v in checks.values()), 'checks': checks,
           'artistic_approval': False, 'publication_approved': False,
           'video': 'output/final.mp4', 'video_sha256': hashlib.sha256(OUT.read_bytes()).hexdigest(), 'duration': round(dur, 3), 'size_mb': size_mb,
           'size': f"{vs['width']}x{vs['height']}", 'fps': vs['r_frame_rate'], 'ffmpeg_xerror': 'pass' if xerr.returncode == 0 else xerr.stderr[:300],
           'loudness': {'integrated_lufs': I, 'true_peak_dbfs': TP, 'lra': LRA}, 'longest_static_s': still, 'longest_static_at_s': still_at,
           'asr_final': asr_text, 'asr_vs_script_ratio': asr_ratio, 'voice_fake': bool(vt.get('fake')), 'voice_track_sha256': vt['sha256'],
           'music': reel['music'], 'sheet': 'qa/sheet.jpg'}
    (P / 'qa/final-result.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
