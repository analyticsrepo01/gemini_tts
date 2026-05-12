FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY serve.py index.html ./
ENV AUDIO_DIR=/tmp/audio_output
RUN mkdir -p /tmp/audio_output

EXPOSE 8080

CMD ["uvicorn", "serve:app", "--host", "0.0.0.0", "--port", "8080"]
