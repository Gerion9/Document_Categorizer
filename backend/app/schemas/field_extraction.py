"""Pydantic models shared between extraction prompts and the Gemini runtime.

Centralizing the schema avoids drift between:
- the JSON Schema sent to Gemini via `response_json_schema`
- the natural-language schema hint embedded in the prompt text (for OpenAI /
  Anthropic which lack native structured-output enforcement).

`backend/app/services/field_extraction_service.py` consumes the Pydantic models
directly. `backend/app/prompts/form_filling_prompts.py` derives a compact
string representation from the same source via `compact_schema_hint()`.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field


FIELD_VALUE_DESC = (
    "Exact value to write into the PDF field. Empty string when evidence is insufficient."
)
FIELD_CONFIDENCE_DESC = (
    "Confidence level for the extracted field value: high, medium, or low."
)
FIELD_JUSTIFICATION_DESC = (
    "Short justification referencing the evidence used, ideally with page citations."
)
FIELD_ID_DESC = "Field identifier from the request payload."


ConfidenceLiteral = Literal["high", "medium", "low"]


class FieldValueResult(BaseModel):
    """Single-field extraction result returned by the LLM."""

    value: str = Field(description=FIELD_VALUE_DESC)
    confidence: ConfidenceLiteral = Field(description=FIELD_CONFIDENCE_DESC)
    justification: str = Field(description=FIELD_JUSTIFICATION_DESC)


class BatchFieldValueItem(BaseModel):
    """Individual entry inside a batch extraction response."""

    id: str = Field(description=FIELD_ID_DESC)
    value: str = Field(description=FIELD_VALUE_DESC)
    confidence: ConfidenceLiteral = Field(description=FIELD_CONFIDENCE_DESC)
    justification: str = Field(description=FIELD_JUSTIFICATION_DESC)


class BatchFieldValueResult(BaseModel):
    """Batch extraction envelope. `answers` mirrors the request order."""

    answers: list[BatchFieldValueItem]


def _compact_property_descriptor(name: str, schema: dict[str, object]) -> str:
    type_hint = schema.get("type") or ""
    if isinstance(type_hint, list):
        type_hint = "|".join(str(item) for item in type_hint)
    enum = schema.get("enum")
    if enum:
        return f'"{name}":"{"|".join(str(value) for value in enum)}"'
    if schema.get("type") == "array":
        items = schema.get("items") or {}
        return f'"{name}":[{_compact_property_descriptor("", items).split(":", 1)[-1] if items else "..."}]'
    if schema.get("type") == "object":
        return f'"{name}":{compact_object_shape(schema)}'
    if type_hint == "string":
        return f'"{name}":"string"'
    if type_hint:
        return f'"{name}":"{type_hint}"'
    return f'"{name}":"..."'


def compact_object_shape(schema: dict[str, object]) -> str:
    """Render a Pydantic JSON Schema as a one-line `{"prop":"type"}` string.

    Used to keep the prompt hint and the actual Gemini schema in sync without
    embedding the full verbose JSON Schema in every system prompt.
    """
    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        return "{...}"
    parts = [
        _compact_property_descriptor(str(name), value)
        for name, value in properties.items()
        if isinstance(value, dict)
    ]
    return "{" + ",".join(parts) + "}"


def compact_schema_hint(model: type[BaseModel]) -> str:
    """Return a single-line string describing the JSON shape of `model`.

    Resolves `$ref` and `$defs` so the rendered hint is self-contained.
    """
    schema = model.model_json_schema()
    defs = schema.get("$defs") or {}

    def resolve(node: object) -> object:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                target = defs.get(ref.split("/")[-1])
                if isinstance(target, dict):
                    return resolve(target)
            return {key: resolve(value) for key, value in node.items() if key != "$defs"}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    resolved = resolve(schema)
    if not isinstance(resolved, dict):
        return json.dumps(resolved, ensure_ascii=False)
    return compact_object_shape(resolved)


__all__ = [
    "BatchFieldValueItem",
    "BatchFieldValueResult",
    "ConfidenceLiteral",
    "FieldValueResult",
    "FIELD_CONFIDENCE_DESC",
    "FIELD_ID_DESC",
    "FIELD_JUSTIFICATION_DESC",
    "FIELD_VALUE_DESC",
    "compact_object_shape",
    "compact_schema_hint",
]
