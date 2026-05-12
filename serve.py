#!/usr/bin/env python3
import asyncio, io, json, os, re, time, threading, uuid, wave
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from google import genai
from google.genai import types

app = FastAPI()

PROJECT_ID  = "my-project-0004-346516"
LOCATION    = "global"
SAMPLE_RATE = 24000
SAMPLE_W    = 2  # PCM16 bytes per sample

# Cloud Run: use GEMINI_API_KEY env var; locally: fall back to Vertex AI ADC
_api_key = os.getenv("GEMINI_API_KEY", "")
client = (genai.Client(api_key=_api_key) if _api_key
          else genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION))

# Use /tmp on Cloud Run (writable), local audio_output otherwise
AUDIO_DIR = Path(os.getenv("AUDIO_DIR", str(Path(__file__).parent / "audio_output")))
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

MODELS = {
    "A": ("gemini-2.5-flash-tts",              "One-Shot",              "Full audio before return. Baseline."),
    "B": ("gemini-2.5-flash-lite-preview-tts", "Chunked (Lite)",        "Text split into chunks, stitched."),
    "C": ("gemini-3.1-flash-tts-preview",      "Streaming ⭐",          "Single stream, sub-2s TTFB."),
    "D": ("gemini-2.5-flash-tts",              "Streaming (2.5 Flash)", "2.5 Flash via generate_content_stream. Vertex AI only."),
    "E": ("gemini-2.5-flash-lite-preview-tts", "Streaming (2.5 Lite)",  "2.5 Lite streaming. Auto-chunks >160 words (512-token limit). Vertex AI only."),
}

VOICES = ["Aoede", "Charon", "Fenrir", "Kore", "Puck", "Orus", "Zephyr", "Leda",
          "Sulafat", "Iapetus", "Umbriel", "Algenib", "Rasalgethi"]


def save_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> str:
    """Save PCM bytes to a WAV file, return filename (not full path)."""
    filename = f"tts_{uuid.uuid4().hex[:8]}.wav"
    path = AUDIO_DIR / filename
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(SAMPLE_W)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return filename


def pcm_dur(pcm: bytes) -> float:
    return len(pcm) / (SAMPLE_RATE * SAMPLE_W)


def speech_cfg(voice: str) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
            )
        )
    )

def apply_instruction(text: str, instruction: str) -> str:
    """TTS models don't support system_instruction — prepend style guidance to the content."""
    if not instruction.strip():
        return text
    return f"{instruction.strip()}\n\nNow say the following:\n{text}"


def split_sentences(text: str, max_words: int = 40) -> list:
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks, current, wc = [], [], 0
    for s in sentences:
        w = len(s.split())
        if wc + w > max_words and current:
            chunks.append(" ".join(current))
            current, wc = [s], w
        else:
            current.append(s)
            wc += w
    if current:
        chunks.append(" ".join(current))
    return chunks or [text]


def downsample_8k(pcm24: bytes) -> bytes:
    """Downsample PCM16 from 24kHz to 8kHz (3:1 decimation) for telephony."""
    import array
    samples = array.array('h', pcm24)
    out = array.array('h', samples[::3])
    return out.tobytes()


def run_generation_sync(text: str, model_key: str, voice: str, instruction: str = "", telephony: bool = True) -> dict:
    """Blocking TTS generation — returns result dict directly."""
    model_name, approach, _ = MODELS.get(model_key, MODELS["C"])
    content = apply_instruction(text, instruction)

    def finish(pcm24: bytes, ttfb: float, total: float, chunks: int) -> dict:
        pcm_out = downsample_8k(pcm24) if telephony else pcm24
        sr_out  = 8000 if telephony else SAMPLE_RATE
        dur     = len(pcm_out) / (sr_out * SAMPLE_W)
        return {
            "filename": save_wav(pcm_out, sr_out),
            "metrics": {
                "ttfb": round(ttfb, 3), "total_time": round(total, 3),
                "audio_duration": round(dur, 2), "chunks": chunks,
                "rtf": round(dur / total, 2),
                "size_kb": round(len(pcm_out) / 1024, 1),
                "sample_rate": f"{sr_out // 1000}kHz",
                "model": model_name, "approach": approach,
            }
        }

    # ── Option A: one-shot ─────────────────────────────────────────────────
    if model_key == "A":
        t0 = time.perf_counter()
        r = client.models.generate_content(model=model_name, contents=content, config=speech_cfg(voice))
        total = time.perf_counter() - t0
        pcm = r.candidates[0].content.parts[0].inline_data.data
        return finish(pcm, total, total, 1)

    # ── Option B: chunked ──────────────────────────────────────────────────
    elif model_key == "B":
        chunks = split_sentences(text)
        # Only apply instruction to first chunk to avoid repetition
        t0 = time.perf_counter()
        ttfb, all_pcm = None, b""
        for i, chunk in enumerate(chunks):
            c = apply_instruction(chunk, instruction) if i == 0 else chunk
            r = client.models.generate_content(model=model_name, contents=c, config=speech_cfg(voice))
            if ttfb is None:
                ttfb = time.perf_counter() - t0
            all_pcm += r.candidates[0].content.parts[0].inline_data.data
        return finish(all_pcm, ttfb, time.perf_counter() - t0, len(chunks))

    # ── Options C / D: streaming ───────────────────────────────────────────
    elif model_key in ("C", "D"):
        t0 = time.perf_counter()
        ttfb, all_pcm, n = None, b"", 0
        for chunk in client.models.generate_content_stream(
            model=model_name, contents=content, config=speech_cfg(voice)
        ):
            try:
                pcm = chunk.candidates[0].content.parts[0].inline_data.data
            except (IndexError, AttributeError):
                continue
            if not pcm:
                continue
            if ttfb is None:
                ttfb = time.perf_counter() - t0
            all_pcm += pcm
            n += 1
        return finish(all_pcm, ttfb, time.perf_counter() - t0, n)

    # ── Option E: 2.5-flash-lite streaming with auto-chunk for 512-token limit ──
    elif model_key == "E":
        # gemini-2.5-flash-lite-preview-tts has a 512-token (~170 word) limit on Vertex AI
        parts = split_sentences(text, max_words=150) if len(text.split()) > 160 else [text]
        t0 = time.perf_counter()
        ttfb, all_pcm, n = None, b"", 0
        for part in parts:
            part_content = apply_instruction(part, instruction) if not ttfb else part
            for chunk in client.models.generate_content_stream(
                model=model_name, contents=part_content, config=speech_cfg(voice)
            ):
                try:
                    pcm = chunk.candidates[0].content.parts[0].inline_data.data
                except (IndexError, AttributeError):
                    continue
                if not pcm:
                    continue
                if ttfb is None:
                    ttfb = time.perf_counter() - t0
                all_pcm += pcm
                n += 1
        return finish(all_pcm, ttfb, time.perf_counter() - t0, n)


class GenRequest(BaseModel):
    text:        str
    model:       str = "C"
    voice:       str = "Aoede"
    instruction: str  = ""    # system prompt / style instruction
    telephony:   bool = True  # downsample to 8kHz for telephony


app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")

@app.get("/", response_class=HTMLResponse)
async def index():
    return (Path(__file__).parent / "index.html").read_text()


from fastapi.responses import JSONResponse
from fastapi.concurrency import run_in_threadpool

@app.post("/generate")
async def generate(req: GenRequest):
    try:
        result = await run_in_threadpool(run_generation_sync, req.text, req.model, req.voice, req.instruction, req.telephony)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 7779))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
