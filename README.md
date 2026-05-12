# 🎙 Gemini TTS Playground

A web application for benchmarking **Google Gemini Text-to-Speech** models with real-time latency metrics. Built to solve a specific challenge: achieving **sub-2-second Time-to-First-Audio (TTFB)** for telephony and call center applications.

**Live Demo**: [gemini-tts-255766800726.us-central1.run.app](https://gemini-tts-255766800726.us-central1.run.app)

---

## Architecture

![Architecture](images/gemini_tts_architecture.png)

Three TTS approaches are benchmarked side-by-side, all accessible from the same UI:

| Option | Model | Approach | TTFB |
|--------|-------|----------|------|
| **A** | `gemini-2.5-flash-tts` | One-shot — full audio before return | ~30s |
| **B** | `gemini-2.5-flash-lite-preview-tts` | Chunked — split text → sequential calls → stitch | ~10s |
| **C ⭐** | `gemini-3.1-flash-tts-preview` | True streaming — chunks arrive as generated | **< 2s** |

## Latency Benchmarks

![Latency](images/gemini_tts_latency.png)

Option C (streaming) achieves sub-2s TTFB on the **full 1-minute Viamo agent script** — the downstream system can begin playback before generation is complete.

---

## Features

- **3 model options** with live metric comparison
- **Real-time metrics**: TTFB, Total Generation Time, Audio Duration, Real-time Factor, Chunks, File Size
- **System Instruction / Style Prompt** — guide tone, emotion and speaking style
- **5 preset styles**: Professional, Warm & Friendly, Energetic, Whisper, News Anchor
- **13 voices**: Aoede, Charon, Fenrir, Kore, Puck, Orus, Zephyr, Leda, Sulafat, Iapetus, Umbriel, Algenib, Rasalgethi
- **Telephony Mode** — one-click 8kHz downsampling (PCMU) for call center compatibility
- **In-browser audio playback** — no downloads needed
- **Run history** — last 8 generations with metrics, click to replay
- **Sample prompts** — short / medium / long / markup tags

---

## Quick Start

### Run Locally

```bash
git clone git@github.com:analyticsrepo01/gemini_tts.git
cd gemini_tts
pip install -r requirements.txt

# Option 1: Vertex AI (on GCP with ADC configured)
python serve.py

# Option 2: AI Studio API key
GEMINI_API_KEY=your_key python serve.py
```

Open: [http://localhost:7779](http://localhost:7779)

### Deploy to Cloud Run

```bash
gcloud run deploy gemini-tts \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "GEMINI_API_KEY=your_key,AUDIO_DIR=/tmp/audio_output" \
  --memory 1Gi --cpu 1 --timeout 300 \
  --project your-project-id
```

---

## API

### `POST /generate`

```json
{
  "text": "Thank you for calling Viamo support.",
  "model": "C",
  "voice": "Aoede",
  "instruction": "Speak warmly and with genuine empathy.",
  "telephony": true
}
```

**Response:**
```json
{
  "filename": "tts_abc123.wav",
  "metrics": {
    "ttfb": 1.86,
    "total_time": 3.21,
    "audio_duration": 4.5,
    "chunks": 97,
    "rtf": 1.4,
    "size_kb": 70.3,
    "sample_rate": "8kHz",
    "model": "gemini-3.1-flash-tts-preview",
    "approach": "Streaming ⭐"
  }
}
```

Audio served at: `GET /audio/{filename}`

---

## Telephony Integration

![Telephony Architecture](images/gemini_tts_telephony.png)

Gemini 3.1 Flash TTS slots into a standard telephony stack as the TTS engine:

1. **Caller** speaks → STT transcribes → Agent LLM generates response text
2. Text sent to **Gemini 3.1 Flash TTS** via `generate_content_stream`
3. First audio chunk arrives in **< 2s** → streamed immediately to the gateway
4. Audio delivered in **8kHz PCM mulaw** (PSTN standard) — enable Telephony Mode in the app or set `"telephony": true` in the API

```python
# Minimal streaming integration example
for chunk in client.models.generate_content_stream(
    model="gemini-3.1-flash-tts-preview",
    contents=agent_response_text,
    config=GenerateContentConfig(speech_config=...),
):
    pcm = chunk.candidates[0].content.parts[0].inline_data.data
    if pcm:
        telephony_gateway.send_audio(downsample_to_8k(pcm))  # stream to caller
```

Compatible gateways: **Twilio Media Streams**, **Vonage WebSockets**, **Viamo**, any SIP/RTP stack accepting PCM.

---

## Markup Tags (Model C only)

Gemini 3.1 Flash TTS supports expressive inline tags:

```
[sigh] I understand your frustration. [short pause]
Let me look into this [whispering] right away.
[medium pause] Great news — [energetic] we got it sorted!
```

Supported: `[sigh]` `[laughing]` `[uhm]` `[sarcasm]` `[robotic]` `[shouting]` `[whispering]` `[extremely fast]` `[short pause]` `[medium pause]` `[long pause]`

---

## Files

```
gemini_tts/
├── serve.py          # FastAPI backend — TTS generation, 8kHz downsampling, audio serving
├── index.html        # Single-page web UI — metrics, voice picker, system instruction
├── gemini_tts.ipynb  # Benchmark notebook — all 4 options with full metrics
├── test_tts.py       # Smoke test — validates all 3 models
├── Dockerfile        # Cloud Run deployment
├── requirements.txt
├── images/           # Architecture and benchmark diagrams
└── audio_output/     # Sample generated WAV files
```

---

## Background

Built as part of a latency investigation for a telephony TTS pipeline. The key finding: **`gemini-3.1-flash-tts-preview` with streaming (`generate_content_stream`) achieves <2s TTFB** on long-form text, making it viable for real-time call center use without the structural complexity of the Live API.

See `gemini_tts.ipynb` for the full benchmark including Cloud TTS `streaming_synthesize` (Option D).
