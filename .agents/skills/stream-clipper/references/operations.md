# Commands

On Windows define `$clip` as the absolute `scripts/clip.py` path and `$py` as the skill's `.venv/Scripts/python.exe`. On Unix use `.venv/bin/python`. All commands accept global `--home PATH` **before** the subcommand. Default home is the real user home plus `stream-clipper`, never the current directory.

```powershell
& $py $clip doctor
& $py $clip config
& $py $clip discover --config C:\work\editorial.json
& $py $clip inspect 'https://www.youtube.com/watch?v=VIDEO_ID'
# Show returned metadata; wait for explicit user confirmation.
& $py $clip authorize SOURCE_ID --confirmation 'Exact user confirmation'
& $py $clip prepare SOURCE_ID --config C:\work\editorial.json
& $py $clip status
# Read blocks and create strict candidate JSON; import every block, even empty arrays.
& $py $clip import-analysis SOURCE_ID --block 0 --file C:\work\block-0.json
& $py $clip review SOURCE_ID
& $py $clip preview SOURCE_ID --ids CANDIDATE_ID
# Present candidates, metadata and previews; wait for exact user selection.
& $py $clip approve SOURCE_ID --ids CANDIDATE_ID --confirmation 'Exact user selection'
& $py $clip render SOURCE_ID --ids CANDIDATE_ID
```

Previews require source authorization but do not require final candidate approval. Finals always require candidate approval. Rejected candidates are simply not approved; adjustments require a new analysis/import/review and fresh approval. No command publishes content.

After interruption repeat `prepare` with the same config. Checksummed successful block JSON is reused. A stale process lock requires `recover-lock`, which refuses if the PID still exists. Inspect PID/process identity manually if a PID has been reused. Runtime process timeouts terminate descendants. A killed coordinator can leave a lock and temporary files; completed checkpoints remain usable.

If section download fails, inspect `plan-full`; show estimated bytes, disk reserve and uncertainty, then obtain explicit user confirmation before `allow-full --confirmation TEXT`. Unknown size is never silently accepted. Disk shortage is rejected even with approval. Retrying `prepare` or `preview` then uses the approved fallback. No authentication bypass is attempted.

`benchmark SOURCE_ID --config FILE --seconds 30 --repeats 2` runs CPU and CUDA on the same authorized interval. Read both timing and transcript quality, plus RAM/VRAM observations. Model load time is reported separately. Total VRAM includes other applications; sampling can miss subsecond peaks.

`cleanup-plan SOURCE_ID` lists disposable intermediates. Only after user review may `cleanup SOURCE_ID --confirmation 'DELETE LISTED TEMPORARIES'` delete that exact list. The downloaded full-source cache is protected.
