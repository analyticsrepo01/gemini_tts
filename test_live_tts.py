#!/usr/bin/env python3
"""
Benchmark: Gemini Live API as a TTS engine.
Measures TTFB, total generation time, audio duration, RTF.
Compares against the static TTS models (A/B/C) benchmarked in serve.py.
"""
import asyncio, os, time, wave, uuid
from pathlib import Path

from google import genai
from google.genai import types

API_KEY = os.getenv("GEMINI_API_KEY", "")
client  = (genai.Client(api_key=API_KEY) if API_KEY
           else genai.Client(vertexai=True, project="my-project-0004-346516", location="global"))

SAMPLE_RATE = 24000
SAMPLE_W    = 2
AUDIO_DIR   = Path(__file__).parent / "audio_output"
AUDIO_DIR.mkdir(exist_ok=True)

MODELS_TO_TRY = [
    "gemini-2.5-flash-preview-native-audio-dialog",
    "gemini-live-2.5-flash-preview",
    "gemini-2.5-flash-live-preview",
    "gemini-3.1-flash-live-preview",  # known-good fallback
]

TEXT_SHORT  = "Thank you for calling Viamo support. How can I help you today?"
TEXT_MEDIUM = (
    "Thank you for calling Viamo support. My name is Alex and I'm here to help. "
    "I can see your account has been active for three years — that's great! "
    "Could you please describe the issue you're experiencing so I can assist you as quickly as possible?"
)
TEXT_LONG = (
    "Hello and thank you for calling Viamo customer support. My name is Alex and I will be your dedicated "
    "support specialist today. I can see from your account that you've been a valued customer with us for "
    "over three years, and we truly appreciate your loyalty. Before we get started, I want to assure you "
    "that your call is important to us and I am fully committed to resolving any issues you may have today. "
    "Could you please start by describing the nature of your inquiry? Whether it's a technical issue, a "
    "billing question, or a request to upgrade your service plan, I have all the tools available to assist "
    "you efficiently. Please take your time and provide as much detail as you feel is necessary, and I will "
    "do my best to provide you with the most accurate and helpful response possible."
)

PROMPTS = [
    ("short",  TEXT_SHORT),
    ("medium", TEXT_MEDIUM),
    ("long",   TEXT_LONG),
]


def save_wav(pcm: bytes, label: str) -> str:
    fname = f"live_{label}_{uuid.uuid4().hex[:6]}.wav"
    with wave.open(str(AUDIO_DIR / fname), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(SAMPLE_W)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    return fname


async def benchmark_live(model: str, label: str, text: str) -> dict | None:
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
            )
        ),
    )

    audio_chunks = []
    ttfb = None
    t0   = time.perf_counter()

    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            await session.send_realtime_input(text=f"Say exactly the following, with no additions: {text}")

            async for resp in session.receive():
                if resp.data:
                    if ttfb is None:
                        ttfb = time.perf_counter() - t0
                    audio_chunks.append(resp.data)
                if resp.server_content and resp.server_content.turn_complete:
                    break

    except Exception as e:
        print(f"  ✗ {model}: {e}")
        return None

    total  = time.perf_counter() - t0
    pcm    = b"".join(audio_chunks)
    dur    = len(pcm) / (SAMPLE_RATE * SAMPLE_W)
    fname  = save_wav(pcm, label)

    return {
        "model":       model,
        "label":       label,
        "ttfb":        round(ttfb  or 0, 3),
        "total_time":  round(total,       3),
        "audio_dur":   round(dur,         2),
        "rtf":         round(dur / total, 2),
        "chunks":      len(audio_chunks),
        "size_kb":     round(len(pcm) / 1024, 1),
        "file":        fname,
    }


async def probe_models() -> str:
    """Return the first model that connects successfully."""
    for model in MODELS_TO_TRY:
        print(f"  Probing {model} ...", end=" ", flush=True)
        config = types.LiveConnectConfig(response_modalities=["AUDIO"])
        try:
            async with client.aio.live.connect(model=model, config=config) as session:
                await session.send_realtime_input(text="Say: test")
                async for resp in session.receive():
                    if resp.data or (resp.server_content and resp.server_content.turn_complete):
                        break
            print("OK")
            return model
        except Exception as e:
            print(f"FAIL ({e})")
    return None


async def main():
    print("=" * 60)
    print("  Gemini Live API — TTS Latency Benchmark")
    print("=" * 60)

    print("\nProbing available live models...")
    model = await probe_models()
    if not model:
        print("\nNo Live API model available in this project/key.")
        return

    print(f"\nUsing model: {model}\n")
    print(f"{'Label':<8} {'TTFB':>7} {'Total':>7} {'Audio':>7} {'RTF':>5} {'Chunks':>7}  File")
    print("-" * 70)

    results = []
    for label, text in PROMPTS:
        print(f"  Running {label}...", flush=True)
        r = await benchmark_live(model, label, text)
        if r:
            results.append(r)
            print(f"  {r['label']:<8} {r['ttfb']:>6.3f}s {r['total_time']:>6.3f}s "
                  f"{r['audio_dur']:>6.2f}s {r['rtf']:>5.2f}x {r['chunks']:>6}  {r['file']}")

    if results:
        print("\n" + "=" * 60)
        print("  Summary vs TTS Models (from serve.py benchmarks)")
        print("=" * 60)
        print(f"  {'Model':<40} {'TTFB':>7}")
        print(f"  {'-'*48}")
        print(f"  {'gemini-2.5-flash-tts (one-shot)':<40} {'~30s':>7}")
        print(f"  {'gemini-2.5-flash-lite (chunked)':<40} {'~10s':>7}")
        print(f"  {'gemini-3.1-flash-tts-preview (streaming)':<40} {'<2s':>7}")
        for r in results:
            label = f"{r['model']} / Live ({r['label']})"
            print(f"  {label:<40} {r['ttfb']:>6.3f}s")
        print()


if __name__ == "__main__":
    asyncio.run(main())
