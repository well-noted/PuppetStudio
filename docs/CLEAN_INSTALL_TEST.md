# Clean Windows installation test

Use a fresh extracted package on Windows x64. Do not copy an old `.venv`,
project, or model environment into it. Existing Python is fine; testing private
Python bootstrapping requires a computer without a supported Python installed.
Do not uninstall working tools just to run this test.

1. Have internet access, at least 15 GiB free disk space, and a working NVIDIA
   driver for speaking-face animation. Studio does not install GPU drivers.
2. Run `launch.cmd`. It finds supported Python or downloads a private Python,
   creates the Studio environment, and opens Studio. No `py` command is needed.
3. In **Getting started**, check the computer and choose **Find and verify
   existing animation tools**. On a clean machine none should be found.
4. Choose the managed animation-tool installation. Downloads and installation
   progress appear in Render queue. Keep Studio running until it finishes.
5. Check the model environment. Confirm verified SadTalker and Python paths
   were saved in Advanced. Retain the log if installation fails.
6. Import a short video. First test **Local Whisper CPU** transcription, review
   a clip, assign its speaker, and provide approved artwork and anatomy.
7. In **Speakers & art**, choose a clip assigned to that speaker, pause on a
   clear face, and press **Capture this frame**. Check the image and saved path.
8. Create a production and render a short preview. Check speech, captions,
   name/title, composition and the completed video in Renders.
9. Restart Studio. Verified tool paths should persist. Tokens entered in the
   UI deliberately do not persist; environment variables set before launch
   are the alternative for supplying credentials.

## Optional Hugging Face test

Open **Advanced → Transcription & clip planning → Hugging Face**.
The download token authenticates model downloads; Local Whisper remains local.
Hosted ASR is a separate transcription choice that uploads audio and can incur
charges. Set a token with Inference Providers permission and a supported ASR
model. Both token fields use HF_TOKEN by default; use another hosted environment
variable name to separate credentials. Tokens are not exported with projects.

Test hosted ASR on a short clip before a full recording. It needs complete
returned timestamps; text-only responses are retained but cannot become timed
captions. Responses are cached in `work/hf_transcription`. Review chunk edges.

## Reporting problems

Include the Render queue error and `work/setup_report.json` when available.
Installation logs are under the tools directory shown in Getting started,
normally `%LOCALAPPDATA%\PuppetStudio\tools`. Never send actual tokens.
After an interrupted install, inspect the log before removing a leftover
`INSTALL_RUNNING.lock`; ensure no installation process is still running.

The managed installer has automated coverage but has not yet been validated
end to end on a clean Windows machine. This test is intended to establish that.
