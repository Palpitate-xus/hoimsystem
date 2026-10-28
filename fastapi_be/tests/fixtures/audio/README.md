# Synthetic audio fixtures

These files contain a generated 440 Hz tone lasting 500 ms, with no speech or patient data. The source is mono, 16 kHz, signed 16-bit PCM WAV. MP3, AAC/M4A, Vorbis/Oga, Opus/Ogg and Opus/WebM were encoded from that source with FFmpeg. They exercise container decoding and bounded duration validation, without assessing transcription quality.

Run the production image with this directory mounted at `/fixtures`:

```sh
python scripts/smoke_audio_runtime.py --fixtures /fixtures
```
