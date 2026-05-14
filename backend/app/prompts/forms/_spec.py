"""`FormPromptSpec` dataclass: per-form knobs for the prompt pipeline.

Each USCIS form declared in `FORM_REGISTRY` ships its own `FormPromptSpec`
instance under `app.prompts.forms.<form>_rules`. The base prompt builders
(`base_form_filling.py`, `base_verification.py`) consume these specs to inject
form-specific guidance into otherwise generic prompts.

Design goals:
- The base prompts contain NO `if form_type == "i-914"` branches. All form
  specifics flow through `FormPromptSpec`.
- Adding a new form means adding a single `<form>_rules.py` file; no further
  edits to base code are required.
- Failing fast: requesting a spec for an unknown form raises KeyError; there is
  NO silent fallback to I-914.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NarrativeFieldMarker:
    """Identifies a questionnaire field that expects a Part-X free-form paragraph.

    Either field can be empty to broaden the match. The matcher requires both
    to be present in the questionnaire metadata when both are set.
    """

    item_id: str
    field_id: str = ""


@dataclass(frozen=True)
class FormPromptSpec:
    """Form-specific configuration consumed by the base prompt builders."""

    form_type: str
    """Canonical normalized form type (e.g. 'i-914', 'g-1145')."""

    form_label: str
    """Long human-readable label injected into verification prompts."""

    short_label: str
    """Short uppercase label used in form-filling prompts (e.g. 'I-914')."""

    verification_context: str = ""
    """Multi-line description of the form's structure (Parts and sections)."""

    item_hints: dict[str, str] = field(default_factory=dict)
    """Per `questionnaire_item_id` -> hint text appended to `_expected_output_hint`.

    Used today for the I-914 Part 4/9 yes/no hard rules. Other forms may add
    their own item-level hints (e.g. I-360 SIJS findings)."""

    narrative_fields: tuple[NarrativeFieldMarker, ...] = ()
    """Fields that should be treated as Part-9 free-form narrative."""

    taxonomy_rules: str = ""
    """Optional hard taxonomy block (e.g. I-914 events taxonomy)."""

    form_filling_extra_rules: tuple[str, ...] = ()
    """Additional rule lines appended to the form-filling base instructions."""

    batch_family_member_pivot_ids: tuple[str, ...] = ()
    """`questionnaire_item_id` prefixes that, in batch mode, must extract from
    family members (not the principal applicant). I-914 Part 5 uses
    ('p5_1', 'p5_children'). Most forms leave this empty."""

    uses_question_value_semantics: bool = False
    """When True (I-914 only), verification YES/NO interprets the underlying
    question value (Is the affirmation true?) rather than completeness."""
