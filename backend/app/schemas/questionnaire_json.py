"""Pydantic models for the questionnaire JSON files under `seed_data/questions/`.

These models describe the on-disk format used by every form questionnaire
(`<form>_form_client.json` and `<form>_form_attorney.json`). They are kept as
permissive as possible (e.g. unknown fields are allowed by default) so that the
schema can evolve without breaking existing files, while still catching the most
common typos and structural mistakes (missing `id`, unknown `type`, etc.).

Used by:
- `app.services.startup_validation` to validate every JSON declared in the
  central `FORM_REGISTRY` at app startup.
- Future tests in `tests/test_questionnaire_schema.py`.

Conventions enforced here are a subset of `seed_data/questions/CONVENTIONS.md`.
Validation severity is configured at the call site (warning vs hard error).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


QuestionType = Literal[
    "text",
    "textarea",
    "date",
    "date_or_text",
    "number",
    "yes_no",
    "single_choice",
    "select",
    "checkbox",
    "signature",
    "note",
    "group",
    "repeatable_group",
    "table",
]

ResponsibleParty = Literal["client", "attorney"]


class QuestionnaireOption(BaseModel):
    """A single choice in a `single_choice` / `yes_no` / `select` / `checkbox` item.

    Accepts two on-disk shapes for backward compatibility:
    - the full `{"label": ..., "value": ...}` form, and
    - a bare string (used historically by I-914 for short option labels like
      "Apt.", "Ste.", "Male", "Married"). Bare strings are normalized to
      `{label: s, value: s}` via the `OptionsList` annotated type. Future
      migrations should promote all options to the explicit dict shape.
    """

    model_config = ConfigDict(extra="allow")

    label: str = Field(min_length=1)
    value: str = Field(min_length=1)


def _coerce_options(value: Any) -> Any:
    """Convert legacy bare-string options into `{label, value}` dicts."""
    if not isinstance(value, list):
        return value
    return [
        {"label": entry, "value": entry} if isinstance(entry, str) else entry
        for entry in value
    ]


OptionsList = Annotated[list[QuestionnaireOption], BeforeValidator(_coerce_options)]


class QuestionnaireSubField(BaseModel):
    """A field nested inside a `group` / `repeatable_group` item or a details block.

    Used for both `fields` (sub-items of a group) and `details_fields`
    (conditional follow-up inputs). All fields are optional except `id` and
    `type`. `label` is optional because some sub-fields share a parent label or
    use the parent's `form_text`.
    """

    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    label: str | None = None
    type: QuestionType
    optional: bool | None = None
    format: str | None = None
    prefix: str | None = None
    default_value: Any = None
    force_default: bool | None = None
    instruction: str | None = None
    where_to_verify: str | None = None
    condition: str | None = None
    options: OptionsList | None = None
    allow_literal_values: list[str] | None = None
    repeatable: bool | None = None


class QuestionnaireItem(BaseModel):
    """A top-level item inside a page (one entry of the `items` array).

    Fields used by code (form_type_matcher, form_filling_service, prompts):
    - `id`, `code`: canonical identifiers (`id` semantic, `code` compact)
    - `label`, `type`: required for rendering and prompting
    - `fields` / `details_fields`: nested inputs
    - `options`: choices for `single_choice` / `yes_no`
    - `instruction`, `where_to_verify`: guidance text for the AI and reviewer
    - `condition`: human-readable show-when expression
    - `responsible_party`: 'client' or 'attorney' (drives questionnaire split)
    - `section`, `form_text`: section heading and the literal form prompt text
    - `optional`, `default_value`, `force_default`, `format`, `prefix`,
      `repeatable`, `exclude_from_form_mapping`, `also_validate_with`,
      `visible_on_pages`, `visible_slots`: rendering / mapping hints
    """

    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    code: str = Field(min_length=1)
    label: str | None = None
    type: QuestionType
    section: str | None = None
    form_text: str | None = None
    instruction: str | None = None
    where_to_verify: str | None = None
    condition: str | None = None
    responsible_party: ResponsibleParty | None = None
    optional: bool | None = None
    format: str | None = None
    prefix: str | None = None
    default_value: Any = None
    force_default: bool | None = None
    repeatable: bool | None = None
    exclude_from_form_mapping: bool | None = None
    also_validate_with: list[str] | None = None
    visible_on_pages: list[int] | None = None
    visible_slots: list[Any] | None = None
    options: OptionsList | None = None
    fields: list[QuestionnaireSubField] | None = None
    details_fields: list[QuestionnaireSubField] | None = None


class QuestionnairePageExcluded(BaseModel):
    """An entry in `excluded_sections`: a section deliberately not asked."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class QuestionnairePage(BaseModel):
    """One page of a questionnaire (`pages[i]`)."""

    model_config = ConfigDict(extra="allow")

    page: int = Field(ge=1)
    items: list[QuestionnaireItem] = Field(default_factory=list)
    excluded_sections: list[QuestionnairePageExcluded] = Field(default_factory=list)


class QuestionnaireDocument(BaseModel):
    """Top-level wrapper for a questionnaire JSON.

    The on-disk format is currently a bare JSON array of pages (not a wrapping
    object). Use `model_validate_pages(...)` to validate that representation.
    """

    model_config = ConfigDict(extra="allow")

    pages: list[QuestionnairePage]

    @classmethod
    def model_validate_pages(cls, raw: Any) -> "QuestionnaireDocument":
        """Validate either the legacy bare-array format or a `{pages: [...]}` dict."""
        if isinstance(raw, list):
            return cls(pages=raw)  # type: ignore[arg-type]
        return cls.model_validate(raw)

    def iter_items(self) -> list[QuestionnaireItem]:
        """Convenience: flatten all items across pages."""
        return [item for page in self.pages for item in page.items]

    def item_ids(self) -> list[str]:
        return [item.id for item in self.iter_items()]

    def item_codes(self) -> list[str]:
        return [item.code for item in self.iter_items()]
