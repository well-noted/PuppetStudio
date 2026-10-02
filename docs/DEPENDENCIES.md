# External dependencies and sources

FFmpeg: https://ffmpeg.org/ (license depends on the build).
NumPy: https://numpy.org/ (BSD).
Pillow: https://python-pillow.org/ (HPND).
OpenCV: https://opencv.org/ (Apache 2.0 for current distributions).
faster-whisper: https://github.com/SYSTRAN/faster-whisper (MIT; model weights
and CTranslate2 dependencies have their own terms).
MediaPipe: https://github.com/google-ai-edge/mediapipe (Apache 2.0;
face-landmarker weights are downloaded separately).
SadTalker: https://github.com/OpenTalker/SadTalker (external checkout/checkpoints,
not redistributed; check the precise upstream revision and component licenses).

Provider contracts checked against official documentation:
https://developers.openai.com/api/docs/guides/speech-to-text
https://developers.openai.com/api/docs/guides/image-generation
https://github.com/SYSTRAN/faster-whisper
https://github.com/OpenTalker/SadTalker/blob/main/docs/best_practice.md

Models are configured by name rather than presented as a universal current
recommendation. Providers can change capabilities; user-selected model/endpoint
combinations should be verified before unattended or paid processing.

Transcription compatibility: setup constrains PyAV to >=11,<19. PyAV 19
removed metadata_errors from av.open; published faster-whisper versions may
still pass it even though upstream main now includes a compatibility fix.
https://pyav.basswood.io/docs/stable/development/changelog.html
