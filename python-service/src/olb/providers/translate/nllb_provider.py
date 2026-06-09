"""NLLB-200 translation provider.

Loads a local Hugging Face NLLB checkpoint from ``model_path``. We never
trigger a download. Missing files map to :class:`ModelFileMissing`; import /
load errors map to :class:`ModelLoadFailed`; runtime errors map to
:class:`TranslateRequestFailed`. FLORES source/target codes are passed
through as-is because NLLB uses the same code system as the realtime
protocol.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from ...errors import ModelFileMissing, ModelLoadFailed, TranslateRequestFailed
from ..base import TranslateProvider
from ..language import supported_flores


def _import_transformers():
    try:
        return (
            importlib.import_module("transformers"),
            importlib.import_module("transformers.AutoTokenizer"),
            importlib.import_module("transformers.AutoModelForSeq2SeqLM"),
        )
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ModelLoadFailed(
            "transformers not installed; install with `pip install transformers sentencepiece`"
        ) from exc


def _validate_model_dir(model_path: str) -> Path:
    if not model_path:
        raise ModelFileMissing("NLLB model_path is empty")
    path = Path(model_path)
    if not path.exists():
        raise ModelFileMissing(f"NLLB model not found: {model_path}")
    if path.is_dir():
        if not (path / "config.json").is_file():
            raise ModelFileMissing(
                f"NLLB model directory missing config.json: {model_path}"
            )
    return path


class NllbTranslateProvider(TranslateProvider):
    name = "translate-nllb"

    def __init__(self, model_path: str = "", *, device: str = "cpu", max_length: int = 256) -> None:
        path = _validate_model_dir(model_path)
        _, AutoTokenizer, AutoModelForSeq2SeqLM = _import_transformers()
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(str(path))
            self._model = AutoModelForSeq2SeqLM.from_pretrained(str(path)).to(device)
        except Exception as exc:  # pragma: no cover - depends on local model
            raise ModelLoadFailed(f"failed to load NLLB model: {exc}") from exc
        self._device = device
        self._max_length = max_length

    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not text:
            return ""
        if source_lang == target_lang:
            return text
        if source_lang not in supported_flores():
            raise TranslateRequestFailed(f"unsupported source language: {source_lang}")
        if target_lang not in supported_flores():
            raise TranslateRequestFailed(f"unsupported target language: {target_lang}")
        try:
            self._tokenizer.src_lang = source_lang
            encoded = self._tokenizer(text, return_tensors="pt").to(self._device)
            forced_bos = self._tokenizer.convert_tokens_to_ids(target_lang)
            out = self._model.generate(
                **encoded,
                forced_bos_token_id=forced_bos,
                max_length=self._max_length,
            )
        except Exception as exc:  # pragma: no cover - depends on local model
            raise TranslateRequestFailed(f"NLLB translate failed: {exc}") from exc
        return self._tokenizer.decode(out[0], skip_special_tokens=True)
