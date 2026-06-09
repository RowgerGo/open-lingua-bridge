"""Centralized language code mapping for ASR / translate / TTS.

The realtime protocol uses FLORES-style BCP-47 codes (e.g. ``cmn_Hans``,
``eng_Latn``). The downstream libraries use different conventions:

- faster-whisper / Silero VAD use Whisper language codes such as
  ``zh`` / ``en`` and ISO codes such as ``zh-CN``.
- NLLB-200 uses FLORES codes directly (matching the protocol).
- Piper TTS voices ship per language; voice metadata exposes the FLORES code.

This registry resolves between the protocol-level FLORES code and the
provider-specific code, and reports which languages the bundle supports.
"""

from __future__ import annotations

from dataclasses import dataclass


# FLORES code -> Whisper code. Whisper supports ~99 languages.
WHISPER_LANG_CODES: dict[str, str] = {
    "cmn_Hans": "zh",
    "cmn_Hant": "zh",
    "eng_Latn": "en",
    "jpn_Jpan": "ja",
    "kor_Hang": "ko",
    "fra_Latn": "fr",
    "deu_Latn": "de",
    "spa_Latn": "es",
    "rus_Cyrl": "ru",
    "por_Latn": "pt",
    "ita_Latn": "it",
    "ara_Arab": "ar",
    "hin_Deva": "hi",
    "vie_Latn": "vi",
    "tha_Thai": "th",
    "ind_Latn": "id",
}

# FLORES code -> human readable label (used in UI / diagnostics).
LANG_LABELS: dict[str, str] = {
    "cmn_Hans": "简体中文",
    "cmn_Hant": "繁體中文",
    "eng_Latn": "English",
    "jpn_Jpan": "日本語",
    "kor_Hang": "한국어",
    "fra_Latn": "Français",
    "deu_Latn": "Deutsch",
    "spa_Latn": "Español",
    "rus_Cyrl": "Русский",
    "por_Latn": "Português",
    "ita_Latn": "Italiano",
    "ara_Arab": "العربية",
    "hin_Deva": "हिन्दी",
    "vie_Latn": "Tiếng Việt",
    "tha_Thai": "ไทย",
    "ind_Latn": "Bahasa Indonesia",
}


@dataclass(frozen=True)
class LanguageResolution:
    flores: str
    whisper: str | None
    label: str
    supported_by_asr: bool
    supported_by_translate: bool
    supported_by_tts: bool

    @property
    def is_complete(self) -> bool:
        return self.supported_by_asr and self.supported_by_translate and self.supported_by_tts


def supported_flores() -> set[str]:
    return set(WHISPER_LANG_CODES.keys())


def resolve(flores: str, *, tts_voices: list[dict] | None = None) -> LanguageResolution:
    """Return a resolution record for a FLORES code.

    ``tts_voices`` is the list returned by ``TtsProvider.list_voices()``;
    when provided, TTS support is checked against the voice metadata.
    """
    flores = (flores or "").strip()
    whisper = WHISPER_LANG_CODES.get(flores)
    label = LANG_LABELS.get(flores, flores)
    asr_ok = whisper is not None
    translate_ok = flores in supported_flores()
    if tts_voices is None:
        tts_ok = False
    else:
        tts_ok = any(v.get("language") == flores for v in tts_voices)
    return LanguageResolution(
        flores=flores,
        whisper=whisper,
        label=label,
        supported_by_asr=asr_ok,
        supported_by_translate=translate_ok,
        supported_by_tts=tts_ok,
    )


def whisper_code(flores: str) -> str:
    """Return the Whisper code for a FLORES code, or ``""`` when unsupported."""
    return WHISPER_LANG_CODES.get(flores, "")


def chain_check(source: str, target: str, tts_voices: list[dict] | None = None) -> dict:
    """Return a structured chain-validity report.

    Used by ``POST /language-chain/check`` and by ``session.start`` validation.
    """
    src = resolve(source, tts_voices=tts_voices)
    dst = resolve(target, tts_voices=tts_voices)
    complete = src.supported_by_asr and src.supported_by_translate and dst.supported_by_tts
    missing: list[str] = []
    if not src.supported_by_asr:
        missing.append(f"asr:{source}")
    if not src.supported_by_translate:
        missing.append(f"translate:{source}")
    if not dst.supported_by_translate:
        missing.append(f"translate:{target}")
    if tts_voices is not None and not dst.supported_by_tts:
        missing.append(f"tts:{target}")
    return {
        "complete": complete,
        "source": {
            "flores": src.flores,
            "whisper": src.whisper,
            "label": src.label,
            "supported_by_asr": src.supported_by_asr,
            "supported_by_translate": src.supported_by_translate,
        },
        "target": {
            "flores": dst.flores,
            "whisper": dst.whisper,
            "label": dst.label,
            "supported_by_translate": dst.supported_by_translate,
            "supported_by_tts": dst.supported_by_tts,
        },
        "missing": missing,
    }
