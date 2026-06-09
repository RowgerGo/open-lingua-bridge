"""NLLB translator (lazy import; uses CTranslate2 when available)."""

from __future__ import annotations

from ..base import TranslateProvider


class NllbTranslateProvider(TranslateProvider):
    name = "translate-nllb"

    def __init__(self, model_path: str, device: str = "cpu") -> None:
        try:
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("transformers not installed; `pip install transformers sentencepiece`") from exc
        self._tokenizer = AutoTokenizer.from_pretrained(model_path)
        self._model = AutoModelForSeq2SeqLM.from_pretrained(model_path).to(device)

    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        self._tokenizer.src_lang = source_lang
        encoded = self._tokenizer(text, return_tensors="pt").to(self._model.device)
        forced_bos = self._tokenizer.convert_tokens_to_ids(target_lang)
        out = self._model.generate(**encoded, forced_bos_token_id=forced_bos, max_length=256)
        return self._tokenizer.decode(out[0], skip_special_tokens=True)
