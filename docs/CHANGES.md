# Public alpha update — 2026-10-02

- Read-only Studio/FFmpeg and selected CUDA/SadTalker startup checks, available
  in Advanced and doctor.py. No installations or environment mutations.
- Global job progress button on every tab; lightweight job-only polling.
- Reviewed clips become unreviewed when source timing, speaker or context changes.
- Replacing a recording asks for confirmation before uploading the new file.
- Blank neutral art rejected before overwriting previous art; anatomical
  plausibility checked before approval.
- OGG audio uploads supported; background worker streams closed after completion.
- 19 Python tests and DOM-free JavaScript workflow checks pass.

Keep this package separate from the conference-specific production tools.
Real Windows browser, live provider and CUDA rendering tests remain required.

## Diagnostic timeout refinement

- Separate 60-second CUDA and 180-second SadTalker startup limits.
- Preserve stdout/stderr on failure and timeout; periodic Python stack traces
  identify stalled imports. Progress appears while checks are running.
- Explicit UTF-8 worker output prevents garbled Windows log punctuation.
- Five diagnostic tests pass, including partial timeout output preservation.

## Transcript validation and Windows page encoding

- Serve the Studio page from explicit UTF-8 input, fixing Windows mojibake.
- Preserve instantaneous word/segment text with adjacent timed source text.
  If zero-duration words lack nearby timing, retain original segment captions.
- Clamp only small boundary rounding; reject reversed, non-finite, grossly
  out-of-bounds or out-of-order times with exact entry/value diagnostics.
- Save complete recognizer output before validation and reuse it only when
  media/settings/hash match. A validation repair does not repeat inference.
- 29 Python tests and DOM-free JavaScript interactions pass, including a
  non-UTF-8 server locale and raw-output cache invalidation.

## Approved PNG identity

An unchanged opaque RGB PNG now retains its original bytes during neutral import,
so Pillow/zlib re-encoding cannot falsely invalidate a matching anatomy profile.
Images requiring actual conversion or cleanup still get a new canonical identity.
A regression test with PNG metadata/nondefault compression passes; all 30 tests
and JavaScript interaction checks pass. Genuine artwork mismatches still fail.

## Production page recovery

- New scenes include audio defaults; validated scene upgrades are retained in
  project state and returned to Studio rather than discarded in a renderer copy.
- Existing productions missing audio defaults are upgraded during project load,
  preserving clip assignments and scene layout. No project reset is needed.
- Page failures show a recovery screen while other tabs remain accessible.
- 32 Python tests pass. JavaScript tests now exercise a populated Productions
  page from the real scene factory, tab switching, and error recovery.

## Model path consistency

- Stored/loaded model paths accept matching surrounding quotes and trim
  accidental whitespace while preserving spaces within folder names.
- Standalone inference also normalizes quotes and expands user-home paths.
- Render preflight reports the specific missing path before extracting speech.
- 33 tests and JavaScript workflow checks pass. CUDA inference still requires
  the Windows speaking preview.

## Render gallery and source trimming

Completed outputs have a Renders tab with filters, playback and downloads.
Source review uses end-boundary playback stopping and synchronized start/end
sliders. Boundary edits automatically check the visible review box; speaker or
context changes clear it. Live approved/unapproved counts and per-clip labels
make remaining review visible.

36 Python tests and DOM-free JavaScript interactions pass. A synthetic two-clip
queue produced individual clips and joined/group videos; gallery metadata and
retained-version discovery passed. Real browser timing remains to be tested.

Render heartbeats now show local time/timezone, subprocess elapsed time,
last-output age and the current RUN stage when available. They report process
liveness, not a guaranteed percentage or proof of forward progress.
37 Python tests and JavaScript interaction checks pass.

Clip transcript panels: toggle visibility, show selected interval, update
on boundary edits, and explain segment-only timing limitations. JavaScript
checks cover interval exclusion, fallback, live updates and toggle behavior.
All 37 Python tests continue to pass.

Saved reference images now display their project-relative path, thumbnail,
Open image and Download reference links below extraction controls. JavaScript
checks cover the populated reference controls; 37 Python tests pass.

Heartbeat labels distinguish process-start age from last worker-message age.

## Additional asset proposals

Speakers with neutral art can create local torso-mask and mouth-closing
proposals or extract the exactly padded anatomy bust. Optional configured image
API edits generate gestures or redraw lips. All results are versioned drafts
with open/download/import-reviewed controls, master/profile identity checks
and no automatic activation. Breathing proposals are narrow central chest
masks, not semantic segmentation; inspect chair/arm overlap. Closed-mouth
warping compresses existing pixels; local bust extraction preserves lips.
API drafts need alignment review; pose imports retain the existing strict guard.
39 Python tests and JavaScript checks pass. Local proposals were verified to
avoid API calls, preserve master bytes and pad rectangular busts correctly.
Live image API editing remains unverified; no paid calls were made.

## Guided setup candidate

Added Getting started, computer inventory, suggested presets, style presets and
explicit asset routes. Windows bootstrap discovers Python or downloads a private
runtime; managed setup installs missing FFmpeg/transcription/anatomy plus a
separate Python 3.10/CUDA SadTalker environment. Source is pinned to upstream
commit cd4c0465ae0b54a6f85af57f5c65fec9fe23e7f8. Models use upstream published
release URLs. Existing CUDA environments are verified and reused first.
Download receipts, archive traversal guards and install locks protect retries.

44 Python tests and DOM-free JavaScript checks passed, including mocked download
reuse/invalidation, unsafe archive rejection, no-GPU fallback, verification-only
path updates, setup UI, art-route controls and authenticated machine inventory.
Python compilation passed. Real clean Windows installation, PowerShell bootstrap,
CUDA inference and interactive browser accessibility remain unverified. No
model environment was installed or changed on the user's computer.

## Reference capture and Hugging Face settings

- Select a clip assigned to a speaker, preview its source, pause and capture the
  current frame without entering a timecode. Captures must be inside that clip.
- Separate local model-download authentication from hosted Hugging Face ASR.
  UI-entered credentials stay in server memory and out of project exports.
- Hosted ASR uses cached 60-second requests and requires returned timestamps.
  Text-only results are retained for inspection rather than given fake timing.
- Added `docs/CLEAN_INSTALL_TEST.md` for fresh Windows installation testing.

## GitHub documentation preparation

- Reorganized README into quick start, workflow, showcase, providers, recovery
  and development sections; removed conflicting accumulated setup instructions.
- Added five screenshot/GIF placeholders and a capture guide in docs/media/.
- MIT copyright attribution is Thomas E. Tuoti (@well-noted), year 2026.
  External packages, models and supplied media retain their separate terms.

## Public repository exclusions

- The maintainer capture guide stays in the downloadable package but is ignored
  by Git. Removed its public README link so it will not break on GitHub.
- Excluded local environments, user projects and root-level media/work/render
  outputs, credentials, model weights, external tool checkouts and diagnostics.
- README showcase images and GIFs remain trackable.

## README showcase captures

- Replaced four interface placeholders with genuine Studio screenshots and a
  scene move/resize GIF using new geometric test artwork. The finished-animation
  placeholder remains; existing conference assets and renders are excluded.
- Added a local review gallery; it and the capture guide remain ignored by Git.
- Captures exercise actual browser interactions with no page-level JS errors.
  They do not establish clean Windows installation or neural inference coverage.

## Deterministic gesture preparation

- Added reviewable local gesture compositing in Speakers & art. Bounded region,
  optional grayscale mask, inside-only feathering and exact protected pixels.
- Added prepare_gesture.py for transparent PNG workflows. No AI, resizing or
  source overwrite; output reports protected pixel changes.
- Renderer, snapshots and Studio bounds now include gesture extents so raised
  hands stay visible and the crop remains fixed across poses.

## First-run installation progress

- Setup now displays three stages: isolated environment, dependency install,
  and import verification. An activity indicator keeps updating during silent
  pip installation, with elapsed time and time since last output.
- Download/install output is retained. The stage bar is not a package-install
  percentage; completion appears only after successful import verification.
- Noninteractive logs receive periodic timestamp-relative status lines.

## Pending speakers and existing animation environments

- Fixed state refresh after adding speakers without artwork. Artwork metadata
  is computed only for speakers with an imported figure. Pending speakers remain
  editable, including in a project containing other completed figures.
- Clarified configured versus missing project paths; installation is optional
  when an existing animation environment can be reused.
- Successful CUDA and SadTalker startup verification saves tool paths for future
  projects on this computer. Custom project settings are not overwritten.

## Windows draft imports and gesture upload IDs

- Draft import buttons carry paths in HTML data attributes rather than inline
  JavaScript string literals. Windows backslashes no longer disappear.
- New drafts use portable paths; missing draft errors explain how to recover.
- Drafts keep their review section open. Applied breathing masks have a visible
  status and preview link; proposals still require review before applying.
- Gesture uploads with blank IDs use a sanitized filename and avoid existing
  pose IDs. Explicit invalid IDs display the value and supported format.
- Reserved asset names cannot be used to overwrite neutral artwork as a pose.

## Protect completed jobs from stale saves

- Project state includes a revision. Saving an older page returns a clear
  conflict instead of overwriting completed transcription or other worker data.
  Current browser edits remain on screen; reload is required before saving.
- Render errors distinguish missing recording and transcript references and
  explain how to reconnect an existing transcript without recognition.

## Broader existing-tool discovery

- Search user-home folders up to three levels deep, capped at 600 directories
  and ten seconds. Environment/cache directories and symlinks are excluded.
- Check Windows virtual environments' Scripts/python.exe and the standard
  WindowsApps Python alias, as well as previous Python/Conda candidates.
- Discovery always writes work/discovery_report.json; failed empty searches
  replace the setup report with a current explanation rather than leaving an
  older report. Existing environments are not modified.

## Preserve upper-face artwork during composition

- Clamp the registered face-cache matte below the calibrated nose, with a short
  soft transition toward the mouth. Older full-face masks no longer replace
  the source eyes, glasses or forehead in finished Studio productions.
- This is a renderer-only correction. Matching neural caches can be reused when
  recomposing the same clip with unchanged assets, intervals and settings.
- Eye expressions/blinks from the neural cache are intentionally excluded;
  lower-face animation and current color correction remain active.

## Editable emphasis phrases

- Fixed the inline textarea handler: a template-literal newline had produced
  invalid JavaScript, so visible edits did not update the production.
- A named input handler now stores one trimmed phrase per line, removes blank
  lines, and marks edits unsaved. Empty lists stay empty after reload.

## Clip playback gesture marking and appearance

- Manual timing has labeled start/end/pose fields and clip-relative timing help.
  Select a speaker's assigned clip, play its audio/video, choose a pose/duration
  and click Add gesture here without interrupting playback. End times clamp to
  the clip boundary; overlap and invalid timing are rejected. Adding selects
  manual mode. New cues are clip-specific; legacy global cues remain labeled.
- The queue filters cues by clip before scheduling and splitting long speeches.
  Separate clips may have matching cue times; conflicts are checked per clip.
- Explained automatic probability, seed, hold length, interval and spacing.
- Added a top-bar light/dark toggle. A browser cookie remembers appearance
  across changing localhost ports; production JSON and render colors stay intact.

## Finished public showcase

- Added the creator-approved welcome_clip.mp4 under docs/media, unchanged with
  original audio, and a poster extracted from its gesture frame at 4 seconds.
- Replaced the finished-production README placeholder with an inline animated GIF
  of the complete demo, plus the original video with audio.
  Existing conference media, artwork, local projects and credentials stay out
  of the public distribution.
