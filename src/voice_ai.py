"""
Voice AI integration - Text-to-Speech using edge-tts (high quality, consistent)
"""

import edge_tts
import asyncio
import time
import os
import subprocess
import sys
import tempfile


def _load_default_voice() -> str:
    """Read tts_voice from config/appium_config.yaml; fall back if unavailable."""
    try:
        import yaml
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "appium_config.yaml",
        )
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        return cfg["voice_ai"]["tts_voice"]
    except Exception:
        return "en-US-AriaNeural"


DEFAULT_VOICE: str = _load_default_voice()


class VoiceAI:
    """Voice synthesis for test automation - uses Microsoft Edge TTS"""

    def __init__(
        self, voice: str = DEFAULT_VOICE, audio_dir: str = ""
    ):
        if not audio_dir:
            audio_dir = os.path.join(tempfile.gettempdir(), "pizza_voice_test")
        self.voice = voice  # Use a consistent neural voice
        self.audio_dir = audio_dir
        os.makedirs(audio_dir, exist_ok=True)

        # Clean up old temp files on initialization
        self._cleanup_old_files()

    def _cleanup_old_files(self):
        """Clean up temp files older than 1 hour"""
        try:
            import glob
            import time

            # Clean up WAV files older than 1 hour
            cutoff_time = time.time() - 3600  # 1 hour ago

            for wav_file in glob.glob(f"{self.audio_dir}/*.wav"):
                try:
                    if os.path.getmtime(wav_file) < cutoff_time:
                        os.unlink(wav_file)
                        print(
                            f"   🗑️ Cleaned up old temp file: {os.path.basename(wav_file)}"
                        )
                except OSError:
                    pass

            # Keep only last 10 files to prevent disk space issues
            wav_files = sorted(
                glob.glob(f"{self.audio_dir}/*.wav"), key=os.path.getmtime, reverse=True
            )
            if len(wav_files) > 10:
                for old_file in wav_files[10:]:
                    try:
                        os.unlink(old_file)
                        print(
                            f"   🗑️ Cleaned up excess temp file: {os.path.basename(old_file)}"
                        )
                    except OSError:
                        pass

        except Exception as e:
            print(f"   ⚠️ Temp file cleanup warning: {e}")

    async def speak(self, text: str, filename: str = "utterance", rate: str = "+0%"):
        """Generate and play speech using edge-tts"""
        print(f"🔊 Speaking: '{text}'")
        wav_file = None
        try:
            timestamp = str(int(time.time() * 1000))
            wav_file = f"{self.audio_dir}/{filename}_{timestamp}.wav"

            print(f"   📝 Generating audio...")

            # Use edge-tts to generate audio
            communicate = edge_tts.Communicate(text, voice=self.voice, rate=rate)
            await communicate.save(wav_file)

            print(f"   🔊 Playing audio...")
            # Kill any lingering player from a previous run before starting a new one.
            if sys.platform == "darwin":
                subprocess.run(["pkill", "-x", "afplay"], capture_output=True)
            elif sys.platform == "linux":
                subprocess.run(["pkill", "-x", "aplay"], capture_output=True)

            # Play the audio file using Popen so we hold a reference to the child
            # process.  subprocess.run() leaves afplay running as an orphan when
            # Python is killed or interrupted — Popen lets us kill the child in the
            # finally / except block, so aborting the test always silences playback.
            if sys.platform == "darwin":
                play_proc = subprocess.Popen(["afplay", wav_file])
            elif sys.platform == "win32":
                import winsound
                winsound.PlaySound(wav_file, winsound.SND_FILENAME)
                play_proc = None
            else:
                play_proc = subprocess.Popen(["aplay", wav_file])

            if play_proc is not None:
                try:
                    play_proc.wait(timeout=60)
                    if play_proc.returncode != 0:
                        raise subprocess.CalledProcessError(play_proc.returncode, "afplay")
                except (KeyboardInterrupt, Exception):
                    play_proc.kill()
                    play_proc.wait()
                    raise

            print(f"   ✅ Audio spoken")
            return wav_file

        except Exception as e:
            print(f"   ❌ TTS Error: {str(e)}")
            import traceback

            traceback.print_exc()
            return None
        finally:
            # Clean up the temp file immediately after playing
            if wav_file and os.path.exists(wav_file):
                try:
                    os.unlink(wav_file)
                    print(f"   🗑️ Cleaned up temp audio file")
                except OSError:
                    pass


def speak_sync(text: str, voice: str = DEFAULT_VOICE, rate: str = "+0%"):
    """Synchronous wrapper for speaking text"""
    vai = VoiceAI(voice=voice)
    import asyncio

    return asyncio.run(vai.speak(text, rate=rate))


def speak_digits_sync(
    digit_words: list,
    voice: str = DEFAULT_VOICE,
    rate: str = "+0%",
    pause_secs: float = 0.7,
):
    """Speak each word in digit_words as a separate utterance with pause_secs gap between.

    IVR digit-collection expects one digit per utterance with natural pauses, which
    matches how a human says a CVV: "three" [pause] "eight" [pause] "two".
    Grouping all digits into one phrase produces unnatural prosody that IVR STT rejects.
    """
    vai = VoiceAI(voice=voice)

    async def _speak_all():
        for i, word in enumerate(digit_words):
            await vai.speak(word, filename=f"digit_{i}", rate=rate)
            if i < len(digit_words) - 1:
                await asyncio.sleep(pause_secs)

    asyncio.run(_speak_all())
