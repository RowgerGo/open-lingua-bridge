"""Mock translation provider that returns the input string with a stable prefix."""

from __future__ import annotations

from ..base import TranslateProvider


class MockTranslateProvider(TranslateProvider):
    name = "translate-mock"

    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not text:
            return ""
        if source_lang == target_lang:
            return text
        return f"[{target_lang}] {text}"


class DictionaryTranslateProvider(TranslateProvider):
    """Cheap lookup-based translator used for offline smoke tests."""

    name = "translate-dict"

    DEFAULT_PAIRS: dict[tuple[str, str], dict[str, str]] = {
        ("cmn_Hans", "eng_Latn"): {"你好": "hello", "再见": "goodbye", "谢谢": "thank you"},
        ("eng_Latn", "cmn_Hans"): {"hello": "你好", "goodbye": "再见", "thank you": "谢谢"},
    }

    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not text:
            return ""
        table = self.DEFAULT_PAIRS.get((source_lang, target_lang), {})
        out = []
        for token in text.split():
            out.append(table.get(token.lower(), token))
        return " ".join(out)
