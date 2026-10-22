#!/usr/bin/env bash
# Скачать шрифты сцены в assets/fonts: Onest (OFL-1.1) и PT Serif Italic (OFL-1.1) из npm-пакетов @fontsource.
# Лицензии кладутся рядом. Без шрифтов сцена тоже работает, но рисует системными.
set -euo pipefail
cd "$(dirname "$0")/../assets/fonts"
CDN=https://cdn.jsdelivr.net/npm/@fontsource
for f in onest-cyrillic-700-normal onest-latin-700-normal onest-cyrillic-400-normal onest-latin-400-normal; do
  curl -fsSL -o "$f.woff2" "$CDN/onest@5.2.5/files/$f.woff2"; done
for f in pt-serif-cyrillic-400-italic pt-serif-latin-400-italic; do
  curl -fsSL -o "$f.woff2" "$CDN/pt-serif@5.2.5/files/$f.woff2"; done
curl -fsSL -o LICENSE-onest.txt "$CDN/onest@5.2.5/LICENSE"
curl -fsSL -o LICENSE-pt-serif.txt "$CDN/pt-serif@5.2.5/LICENSE"
ls -1
