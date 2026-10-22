"""Запустить команду под именованной блокировкой на всю машину.
Зачем: синтез голоса и рендер в Chromium тяжёлые; два параллельных запуска делят GPU/память и падают
или идут втрое дольше. Блокировка ставит их в очередь.
Пример: python3 locked.py voice -- python voice/gen_omni.py
        python3 locked.py render -- python tools/render.py
Каталог файлов блокировки: $LOCK_DIR (по умолчанию системный temp)."""
import fcntl, os, subprocess, sys, tempfile

name = sys.argv[1]
cmd = sys.argv[sys.argv.index('--') + 1:]
lock_dir = os.environ.get('LOCK_DIR', tempfile.gettempdir())
with open(os.path.join(lock_dir, f'quick-reels-{name}.lock'), 'w') as f:
    fcntl.flock(f, fcntl.LOCK_EX)   # ждём, пока предыдущий держатель не отпустит
    sys.exit(subprocess.call(cmd))
