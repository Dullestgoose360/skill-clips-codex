# Configuration

Run `clip.py config` to print all defaults. Save JSON outside the skill and pass `--config absolute-path.json` to discovery/preparation/benchmark. All fields are validated; unknown keys, invalid ranges, nonfinite values, duplicate JSON keys and wrong types are rejected.

- Editorial: `platform`, `topic`, `subject`, `creator`, `keywords` (array), `language` (null/ISO code), `video_count`, `clip_count`, `min_duration`, `max_duration`, `editorial_criteria`.
- Work: `block_seconds` (default 720), `context_seconds` (5), `timeout` (1800s), `large_download_gb` (2).
- ASR: `model` (tiny by default, multilingual), `device` (auto/cpu/cuda), `cpu_threads` (8), `allow_model_download` (false). Enable download only when a selected model is needed and its size has been reviewed. auto tries CUDA in an isolated subprocess then CPU/int8; explicit cuda also safely falls back during preparation. Benchmark cuda never falls back, so it cannot mislabel CPU results.
- Output: `profile` (9:16/16:9/1:1), matching even `width` and `height`, `fps`, `codec` (libx264/h264_nvenc), `crf`, `preset`. Profile alone selects default resolution. NVENC uses CQ and p4; CPU uses CRF and selected preset. No encoder fallback hides failures.
- Layout: `layout` (fit/camera-top), `camera_fraction`, `camera_box` (null or source-pixel [x,y,width,height]), `game_position` (horizontal 0–1), `face_threshold`, `face_samples`, `face_min_hits`. Manual box is checked against actual video dimensions.
- Captions: `subtitles`, `title_overlay`, `subtitle_size` (fraction of width), `subtitle_y` (bottom margin as fraction of height). Word timestamps come from the completed ASR blocks. ASS escaping prevents transcript text from injecting formatting directives.

## Candidate analysis schema

Each block file is a JSON array, including `[]` for no suitable moments:

```json
[{"start":"00:00:03.200","end":"00:00:28.000","title":"A complete idea","reason":"Explains one idea from premise to conclusion","score":82,"post":"Optional caption"}]
```

Only these keys are accepted. start/end accept nonnegative finite seconds or MM:SS / HH:MM:SS. Intervals must be within the source and the configured duration bounds; start must belong to that block's primary interval. Context can extend across blocks. The agent should read adjacent blocks for a candidate extending beyond available context. Scores must be 0–100. No silent trimming or extension is performed. The tool generates IDs from the full candidate content; any edit changes the ID. Selection is deterministic, ranks by score and excludes temporal overlap. Scores express editorial judgment, not a prediction of performance.

## Data layout

`HOME/sources/PLATFORM-HASH/` contains sanitized metadata, source-specific authorization, active configuration, events and section cache. `generations/HASH/blocks/00000/` contains independent transcription checkpoints and analysis. Reviews use immutable content identities; `reviews/HASH/previews/` and `reviews/HASH/approved/` are separate. `result.json` records output SHA, configuration, camera and integrity checks. Old generations remain available. Temporary cleanup is explicit and restricted to `tmp/`; source/final files are never automatically deleted.

Runtime configuration `runtime.json` resolves relative paths against the installed skill: ffmpeg, ffprobe, face_model, model_cache, cuda_dirs. Credentials, cookies, tokens and signed playback URLs must never be placed there.
