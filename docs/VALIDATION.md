# Validation — 2026-10-02 public alpha

## Completed here

- 19 automated tests passed: source timing and captions, contiguous speech
  chunks, repeatable gesture scheduling inside speech, path containment,
  secret rejection, value/range errors, scene validation, conservative matte
  cleanup, torso-mask fallback, API request formatting with mock responses,
  and authenticated localhost save/export behavior.
- JavaScript syntax and DOM-free interactions checked with Node: workflow
  pages, global job status, model-check controls, replacement confirmation,
  and resetting clip review after edits. This is not interactive browser QA.
- New diagnostics tested for missing tools, secret redaction and exact model
  import failures. Invalid anatomy and blank replacement assets are rejected.
- Background job polling stays available without loading project artwork.
- Synthetic end-to-end project rendered two speech clips: 3 seconds including
  its intro, and 2 seconds. Combined and grouped outputs are approximately
  5.02 seconds and contain video plus original audio. No queue failures.
- Earlier matching-output rerun reused outputs. Face inference and composition
  use separate content fingerprints; completed face caches survive composition
  failures. The neural cache path was not exercised on a GPU here.
- Generic distribution scan found no named conference speakers or user paths.
- Optional gesture-edge patch: neutral and both gesture mattes reviewed on a
  maroon background. Both speakers' canonical character/profile bytes remain
  unchanged. Installation creates a separate version and performs no render.

## Still needs real-world validation

- Windows first-launch dependency installation and browser interactions.
  Local HTTP endpoints were tested; interactive browser verification timed out.
- Full SadTalker/CUDA execution on the target 4 GB laptop and real speech.
- MediaPipe anatomical detection across different drawn styles.
- Live paid API transcription, semantic planning and image edits. Adapter tests
  used mocks; provider compatibility and billing vary.
- Extended accessibility review, long overnight queues and cancellation recovery.

This package is an alpha for testing, not a claim that arbitrary input video
can automatically become an anatomically correct, polished puppet. Review art,
landmarks and clip assignments, then render a short preview before a batch.

Diagnostic timeout refinement: five targeted diagnostics tests passed, including
CUDA/startup phase isolation and byte-output retention on timeout. JavaScript
workflow checks and Python compilation also passed. The original 19-test suite
passed for the previous build; its full rerun in this refreshed environment was
blocked by missing OpenCV. Renderer code did not change in this refinement.

Latest refinement: full 29-test suite passed after restoring OpenCV in the test
environment. Added tests cover instantaneous word/segment timing, preserving
source text without shifting speech, raw recognition retention on failure,
matching-input reuse, changed-media invalidation, and UTF-8 HTML under an ASCII
default locale. JavaScript checks and Python compilation also passed.

Production recovery update: 32 Python tests pass, with new creation and
existing-scene upgrade coverage. DOM-free JavaScript checks now render the
populated production controls using the Python scene factory, verify tab
reopening and check navigation after a deliberate malformed-scene error.
Interactive Windows browser and real CUDA rendering validation remain pending.

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

A synthetic two-clip composition queue completed after setup integration,
retaining individual and assembled outputs. HEAD checks confirmed the pinned
source, uv and FFmpeg archive URLs respond; Windows installation was not run.

## Clip reference capture and Hugging Face adapter

49 Python tests and DOM-free JavaScript checks passed. New coverage exercises
real timestamp offsets, missing/incomplete timestamp rejection, silence, raw
response cache reuse, credential rejection and exclusion from exported JSON.
UI checks verify the assigned-clip selector, capture boundary guard and the
separate Hugging Face settings. Python compilation passed.

Live Hugging Face requests and native browser frame selection remain untested
here. Clean Windows installation and private Python bootstrapping still require
the checklist test. No new GPU inference or user-machine installation was run.

## Synthetic README interface capture

A local Chromium session exercised clip source playback, excerpt transcript
visibility, assigned-clip reference selection, scene dragging and numeric height
changes, and completed-render playback. No page-level JavaScript errors were
observed in this sequence. Screenshots and the scene-composition GIF use only
new geometric test artwork. Two synthetic clips and their grouped/combined
outputs rendered using the still-face backend. This does not validate neural
lip synchronization, anatomy detection or Windows installation.

## Deterministic gesture preparation

54 Python tests, Node UI checks and Python compilation passed. New tests cover
exact protected RGBA bytes, premultiplied alpha at soft boundaries, mask support,
invalid geometry rejection, successful draft import, stale-master rejection and
fixed bounds containing an extended hand. No model provider calls are used.

The new user-supplied standing character and repaired gesture passed normal
Studio imports. A six-second silent transition rendered with the standard
renderer. The preparation report records zero changed protected pixels. A
color-derived mask was used for this pair's bare arms; it is a reviewed local
heuristic, not a general anatomical detector. These personal assets are kept
in a separate asset bundle and are not included in the public Studio package.
Neural lip synchronization and the new file-upload controls in a real browser
remain to be tested on the target computer.

## Setup progress and pending speakers

60 Python tests and Node UI checks passed. Setup tests cover retained subprocess
output, failure status, truthful elapsed/quiet times and activity during quiet
installation. Environment reuse tests cover successful verification, preserving
custom paths, missing executables and rejected probes. The authenticated HTTP
test adds a speaker before artwork, reloads project state, imports artwork and
adds another pending speaker; both appear and metadata covers only existing art.
Clean Windows installation and real CUDA verification remain user-side checks.

## Windows draft-path regression coverage

62 Python tests and Node UI checks passed. Added full generate/import breathing
mask coverage with slash/backslash requests and exact grayscale pixels; missing
drafts return a descriptive error. Node executes the import button with a
Windows path and verifies exact path preservation, plus filename-derived gesture
IDs and collisions. Reserved pose IDs cannot overwrite the neutral master.
Python compilation passed. Live Windows browser verification remains required.

## Stale-save protection

63 Python tests, Node UI checks and Python compilation passed. The HTTP test
simulates a completed worker adding a transcript after a browser loads state,
then verifies that saving the old revision returns HTTP 409 and retains the
transcript. Render input checks identify missing recording versus transcript.
The affected user project's transcript bytes are not available here, so recovery
requires checking/importing that file on Windows.

## Existing-tool search regression coverage

66 Python tests, Node UI checks and compilation passed. Fixtures cover a
nested sibling checkout under a simulated user home, depth/directory limits,
excluded application data, fresh reports after an empty search, and Windows
virtual-environment and WindowsApps Python candidates. Successful mocked
verification remains necessary before saving discovered paths. Actual discovery
and CUDA startup on the user's Windows computer remain to be tested.

## Upper-face composition guard

68 Python tests, Node UI checks and compilation passed. Synthetic cache tests
verify exact source pixels above the nose, a monotonic soft boundary, continued
mouth animation and no expansion of an existing lower-face mask. The supplied
finished clip was inspected via sampled face frames and temporal pixel changes;
the automatic profile's full-face polygon exposed neural eye changes. No source
face cache/project was supplied, so corrected real-clip recomposition requires
a user-side rerender. No user media is included in this public package.

## Phrase editing regression

69 Python tests, Node UI checks and compilation passed. Node executes the actual
rendered textarea handler, verifies custom phrase data and dirty state, and
switches pages to verify preserved text. Project save/load tests retain both
custom lists and an intentionally empty list without restoring defaults.

## Manual timing and appearance

72 Python tests, Node UI checks and compilation passed. Tests cover separate
clip scheduling, legacy cues, overlap rejection, source-to-clip time conversion,
end clamping, continued playback after marking and stopping at the clip end.
Theme tests cover toggle state, cookie restoration and unchanged project data.
Full interactive Windows browser playback still needs user-side validation.

## Finished showcase packaging

The supplied 17.741-second video contains 1280 × 720 video and audio. The public
copy's SHA-256 matches the upload exactly; a poster was extracted at 4 seconds
and visually reviewed. All README docs/media references resolve. No code changed
for this documentation/media update; the prior 72-test validation still applies.

Inline GIF verified: 177 frames, 17.70 seconds, 960 × 540. Original MP4 remains byte-identical; README media references resolve.
