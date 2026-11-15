# Origin audit — 2026-11-15

- Upstream: https://github.com/davixavier-coder/skill-clips
- Fork: https://github.com/Dullestgoose360/skill-clips-codex
- Base HEAD: `97b7b9084df7158b976fc8e0a0432e31fd919a74` (main; verified with ls-remote and clone).
- Account verified through authenticated GitHub connector and fork UI; name availability checked before creation.
- Development branch: `codex/general-clipper-adaptation`.
- Original tracked files: `.gitignore`, `README.md`, `SKILL.md`, `scripts/{clip,comum,cortar,ouvir}.py`.
- No LICENSE, COPYING, dependency manifest, or automated tests in this commit. No license grant is inferred from public visibility. Original attribution and files are retained; this fork does not assign a license to upstream code.

## Inspected architecture and concrete findings

Original `clip.py` dispatches installation, topic-specific YouTube search, preparation, selection and rendering. `ouvir.py` downloads audio/chat, transcribes on CPU and computes audio activity. `cortar.py` selects moments, samples YuNet faces, creates ASS and invokes FFmpeg.

Dependencies declared inline: faster-whisper, opencv-python-headless, numpy, yt-dlp[default], certifi; external FFmpeg/ffprobe; YuNet ONNX and Whisper base/small. Installation upgrades packages and downloads both speech models unconditionally.

Findings to address:

1. Directory identity uses a truncated creator/title slug, allowing collisions.
2. JSON parse errors can silently fall back; timestamps accept negative/nonfinite values; selection silently changes durations.
3. A transcription is saved only after the entire source completes; existing files are treated as completed without fingerprint/integrity checks.
4. Audio peak analysis reads the entire PCM stream into memory.
5. Face medians can combine distinct faces; no manual camera region, configurable sampling or confidence reporting.
6. Failed section downloads automatically download the full source without a size/disk gate.
7. Rendering uses overwrite flags and ordinal names; approvals are not represented; final video is not fully decoded for validation.
8. Commands and instructions contain fixed topic/Claude paths; no portable personal installation verifier.

## Initial environment observation

Real profile: `C:\Users\ADMIN`. Python 3.12.10 exists under AppData/Local/Programs/Python/Python312, while the PATH alias fails. RTX 3060, 12288 MiB, driver 621.24; initial total device use 3230 MiB. About 232 GB free on C:. These are observations, not benchmark results. No existing personal `stream-clipper` directory was found at initial inspection.

Synthetic audiovisual source explicitly authorized in this chat: local `test-artifacts/source-test.mp4`, title Teste técnico Stream Clipper, approximately 30 seconds, generated image and Portuguese synthetic speech. No third-party live authorized.
