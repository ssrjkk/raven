from unittest.mock import patch

from raven.voice import TextToSpeech, TTSConfig, TTSProvider, SpeechToText, STTConfig, STTProvider


def test_tts_default_config():
    tts = TextToSpeech()
    assert tts.config.provider == TTSProvider.SYSTEM
    assert tts.config.speed == 1.0


def test_tts_custom_config():
    config = TTSConfig(provider=TTSProvider.GTTS, speed=1.5)
    tts = TextToSpeech(config)
    assert tts.config.provider == TTSProvider.GTTS
    assert tts.config.speed == 1.5


def test_tts_synthesize_system(tmp_path):
    config = TTSConfig(provider=TTSProvider.SYSTEM, cache_dir=str(tmp_path))
    tts = TextToSpeech(config)
    with patch("raven.voice.tts.subprocess.run"):
        output = tts.synthesize("Hello world")
    assert output.endswith(".wav")


def test_tts_synthesize_elevenlabs_fallback(tmp_path):
    config = TTSConfig(provider=TTSProvider.ELEVENLABS, cache_dir=str(tmp_path))
    tts = TextToSpeech(config)
    with patch("raven.voice.tts.subprocess.run"):
        output = tts.synthesize("Hello world")
    assert output.endswith(".wav")


def test_tts_synthesize_edge_import_fallback(tmp_path):
    config = TTSConfig(
        provider=TTSProvider.EDGETTS,
        cache_dir=str(tmp_path),
        voice="en-US-AriaNeural",
    )
    tts = TextToSpeech(config)
    with patch("raven.voice.tts.subprocess.run"):
        output = tts.synthesize("Hello world")
    assert output.endswith(".wav") or output.endswith(".mp3")


def test_tts_list_voices_default():
    tts = TextToSpeech()
    voices = tts.list_voices()
    assert isinstance(voices, list)


def test_stt_default_config():
    stt = SpeechToText()
    assert stt.config.provider == STTProvider.WHISPER
    assert stt.config.model == "base"


def test_stt_custom_config():
    config = STTConfig(provider=STTProvider.GOOGLE, language="fr")
    stt = SpeechToText(config)
    assert stt.config.provider == STTProvider.GOOGLE
    assert stt.config.language == "fr"


def test_stt_transcribe_empty_audio(tmp_path):
    audio = tmp_path / "empty.wav"
    audio.write_bytes(b"")
    stt = SpeechToText()
    text = stt.transcribe(str(audio))
    assert text == ""


def test_stt_record_import_fallback():
    stt = SpeechToText()
    text = stt.record_from_microphone(duration=1.0)
    assert isinstance(text, str)
