# Aufbereitung als Container: alle Extraktionswerkzeuge (OCR, PDF-Rendering,
# Audio/Video, ASR, Folien) sind im Image — auf dem Server ist nur Docker nötig.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-deu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY lernpaket_pipeline ./lernpaket_pipeline
# Folien-Extra mit headless-OpenCV (im Container gibt es kein Display); die
# opencv-Variante aus pyproject würde GUI-Bibliotheken verlangen.
RUN pip install --no-cache-dir '.[asr,ocr]' 'scenedetect[opencv-headless]>=0.6'

# Whisper-/HuggingFace-Modelle (~3 GB) leben in einem Volume, nicht im Image.
ENV HF_HOME=/modelle
VOLUME ["/modelle"]

ENTRYPOINT ["lernpaket"]
CMD ["--help"]
