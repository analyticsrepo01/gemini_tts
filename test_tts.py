"""Quick smoke test — runs each TTS option and reports TTFB."""
import os, time, wave
from pathlib import Path
from google import genai
from google.genai import types

PROJECT_ID = "my-project-0004-346516"
LOCATION   = "global"
client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

OUTPUT_DIR = Path("audio_output")
OUTPUT_DIR.mkdir(exist_ok=True)

SAMPLE_RATE  = 24000
SAMPLE_WIDTH = 2  # PCM16

TEXT = "Thank you for calling Viamo support. How can I help you today?"

def save_wav(pcm: bytes, name: str):
    path = str(OUTPUT_DIR / name)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    print(f"  Saved: {path} ({len(pcm)/(SAMPLE_RATE*SAMPLE_WIDTH):.1f}s)")

def speech_cfg(voice="Aoede"):
    return types.GenerateContentConfig(
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
            )
        )
    )

# ── Option A: one-shot gemini-2.5-flash-tts
print("\n[A] gemini-2.5-flash-tts (one-shot)")
try:
    t0 = time.perf_counter()
    r = client.models.generate_content(
        model="gemini-2.5-flash-tts",
        contents=TEXT,
        config=speech_cfg(),
    )
    total = time.perf_counter() - t0
    pcm = r.candidates[0].content.parts[0].inline_data.data
    save_wav(pcm, "option_a.wav")
    print(f"  TTFB=Total: {total:.2f}s  ✓")
except Exception as e:
    print(f"  ERROR: {e}")

# ── Option B: one-shot gemini-2.5-flash-lite-preview-tts
print("\n[B] gemini-2.5-flash-lite-preview-tts (one-shot)")
try:
    t0 = time.perf_counter()
    r = client.models.generate_content(
        model="gemini-2.5-flash-lite-preview-tts",
        contents=TEXT,
        config=speech_cfg(),
    )
    total = time.perf_counter() - t0
    pcm = r.candidates[0].content.parts[0].inline_data.data
    save_wav(pcm, "option_b.wav")
    print(f"  TTFB=Total: {total:.2f}s  ✓")
except Exception as e:
    print(f"  ERROR: {e}")

# ── Option C: streaming gemini-3.1-flash-tts-preview
print("\n[C] gemini-3.1-flash-tts-preview (streaming)")
try:
    t0 = time.perf_counter()
    ttfb = None
    all_pcm = b""
    chunks = 0
    for chunk in client.models.generate_content_stream(
        model="gemini-3.1-flash-tts-preview",
        contents=TEXT,
        config=speech_cfg(),
    ):
        try:
            pcm = chunk.candidates[0].content.parts[0].inline_data.data
        except (IndexError, AttributeError):
            continue
        if pcm:
            if ttfb is None:
                ttfb = time.perf_counter() - t0
                print(f"  First chunk at {ttfb:.3f}s")
            all_pcm += pcm
            chunks += 1
    total = time.perf_counter() - t0
    save_wav(all_pcm, "option_c.wav")
    print(f"  TTFB: {ttfb:.3f}s | Total: {total:.2f}s | Chunks: {chunks}  ✓")
except Exception as e:
    print(f"  ERROR: {e}")

print("\nDone.")
