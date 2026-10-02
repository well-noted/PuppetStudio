# Public release roadmap

The current alpha separates reusable project state, optional provider adapters,
face inference and scene composition. It intentionally keeps art/calibration
review ahead of unattended rendering.

Next priorities:
1. Windows end-to-end trial with the next reviewed speaker, including a
   fresh isolated setup and a 12-second speaking calibration.
2. GUI asset registration and sheet extraction; verify neutral/gesture head,
   chair and leg consistency before accepting a pose.
3. Additional provider adapters (Gemini, Anthropic planning, image providers),
   native model lists and capability checks rather than treating endpoints
   as universally interchangeable.
4. Optional diarization with explicit human speaker mapping and meaningful
   chapter grouping, including uncertainty indicators and source playback.
5. Articulated arms/hands, more varied gesture assets, torso-mask authoring and
   speech/phoneme-driven mouth assets for difficult tight-lipped characters.
6. Better preview performance and pixel parity; accessibility audit and
   keyboard equivalents for dragging/resizing.
7. Multiple recordings per project, more output resolutions, crossfades and
   batch selection presets; resumable cancellation with automatic safe lock
   reconciliation.
8. CI on Windows/Linux/macOS, pinned tested dependency lockfiles, provider
   contract tests and a real small-GPU compatibility matrix.

A public repository should ship only code/docs and the generated geometric
example. Project content and secrets are excluded by .gitignore. Uploading a
repository or publishing a release remains a separate action.
