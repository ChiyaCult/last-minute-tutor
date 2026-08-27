#!/bin/bash
# Nachtlauf für das Modul "rest" mit dem lokalen Qwen3 14B.
#
#   caffeinate -i ./nachtlauf.sh
#
# caffeinate ist nicht optional: ohne verhindert nichts, dass macOS in den
# Ruhezustand geht und den Lauf mittendrin anhält.
#
# Abbruch jederzeit per Ctrl-C — der Antwort-Cache unter
# input/rest/extraktion/generierung/ hält jedes fertige Thema fest, ein zweiter
# Anlauf setzt dort auf und kostet nur die noch fehlenden.
set -u
cd "$(dirname "$0")/pipeline" || exit 1

export LERNPAKET_LLM=ollama
# Bewusst das 14B (9,3 GB) und nicht das 27B (14 GB): auf 24 GB RAM blieb
# neben dem 27B kein Platz für macOS — Swap lief auf 6,6 GB voll und ein
# einzelnes Thema brauchte über 14 Minuten statt der berechneten 7.
# Hochgerechnet ~10 h statt 1,3 h, bei unvorhersehbarem Swap-Verhalten.
export LERNPAKET_OLLAMA_MODELL='qwen3:14b'
# Größter Prompt in rest: 14.070 Token plus bis zu 4.096 Token Antwort.
# 20480 reicht für jeden Prompt und spart gegenüber 32768 KV-Cache.
export LERNPAKET_OLLAMA_CTX=20480
unset GEMINI_API_KEY GOOGLE_API_KEY ANTHROPIC_API_KEY   # nichts versehentlich remote

ZIEL=../lernpakete-neu
mkdir -p "$ZIEL"
LOG="$ZIEL/rest.log"

echo "===== rest  Start $(date '+%F %H:%M:%S')  Modell $LERNPAKET_OLLAMA_MODELL =====" | tee -a "$LOG"
./.venv/bin/lernpaket generieren ../input/rest --ziel "$ZIEL" 2>&1 | tee -a "$LOG"
code=${PIPESTATUS[0]}
echo "===== rest  Ende  $(date '+%F %H:%M:%S')  Exit $code =====" | tee -a "$LOG"
exit "$code"
