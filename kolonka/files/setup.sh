#!/bin/bash
# Ставит всё в папку kolonka/: venv с Python-библиотеками и модель Vosk для слова «Горо». Системные настройки не трогает.
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-$(command -v python3.11 || command -v python3)}
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
if [ ! -d models/vosk-model-small-ru-0.22 ]; then
  mkdir -p models
  curl -sSL -o models/vosk-ru.zip https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip
  (cd models && unzip -q vosk-ru.zip && rm vosk-ru.zip)
fi
# первая загрузка модели распознавания (~460 МБ) в кэш Hugging Face
.venv/bin/python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"
command -v claude >/dev/null || echo "Нет claude: поставьте Claude Code и войдите своей подпиской (claude, затем /login)."
say -v '?' | grep -q ru_RU || echo "Нет русского голоса: Системные настройки → Универсальный доступ → Устной контент → Голоса → Русский."
echo "Готово. Запуск: ./run.sh"
