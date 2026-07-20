# Aufbereitung als Container: alle Extraktionswerkzeuge (OCR, PDF-Rendering,
# Audio/Video, ASR, Folien) sind im Image — auf dem Server ist nur Docker nötig.
FROM python:3.12-slim

# Systempakete: OCR-Engine tesseract (mit deutschen Sprachdaten) plus die
# Runtime-Libs, die das volle OpenCV unter Linux zum Laden braucht (libGL,
# libglib). ffmpeg und PDF-Rendering bringen die pip-Wheels (av/opencv, PyMuPDF)
# selbst mit — kein apt-ffmpeg/poppler nötig.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-deu \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# uv als Installer — installiert exakt die in uv.lock gepinnten Versionen,
# identisch zur lokalen Umgebung (reproduzierbar).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY lernpaket_pipeline ./lernpaket_pipeline
RUN uv sync --frozen --extra asr --extra ocr --extra folien

# Whisper-/HuggingFace-Modelle (~3 GB) leben in einem Volume, nicht im Image.
ENV HF_HOME=/modelle
VOLUME ["/modelle"]

ENTRYPOINT ["/app/.venv/bin/lernpaket"]
CMD ["--help"]
