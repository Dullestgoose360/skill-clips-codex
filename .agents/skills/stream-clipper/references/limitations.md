# Scope and limits

- Network support depends on the installed yt-dlp extractor and the public VOD. YouTube, Twitch and Kick are initial targets, not universal compatibility. Ongoing live streams, DRM, private/member-only/age-gated sources and authenticated access are not supported by this workflow.
- Search automation is implemented for YouTube. Twitch/Kick discovery uses public UI/search or direct links. Chat replay is attempted for YouTube only; missing/failed chat is reported, never a success marker. Other platform chat is explicitly unavailable.
- Section downloads can still require significant network I/O, depending on the provider. No claim is made that every server supports ranged access. Full-source fallback always requires a reviewed plan.
- Face position is sampled, not tracked frame by frame. Multiple faces and camera movement can require a manual crop. A face does not prove a streamer camera box. No real-person fixture has yet been authorized for this project's test.
- Technical AV timestamp/duration checks do not prove perceptual lip sync or editorial quality. Review previews by eye and ear.
- Recognition and benchmark results depend on the actual installed client/environment. Report executed, mocked and pending tests separately.
- Upstream base has no license file. Its original files and attribution are retained unchanged; no new license is assigned to that code.
