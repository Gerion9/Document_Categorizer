"""Per-form prompt specifications.

Importing this module guarantees that every USCIS form declared in
`app.services.form_registry.FORM_REGISTRY` has a matching `FormPromptSpec`
loaded into `FORM_PROMPT_REGISTRY`. New forms must add an entry both in
`form_registry` and in this package.
"""

from __future__ import annotations

import importlib

from ...services.form_registry import FORM_REGISTRY
from ._spec import FormPromptSpec


def _load_registry() -> dict[str, FormPromptSpec]:
    registry: dict[str, FormPromptSpec] = {}
    for spec in FORM_REGISTRY.values():
        module = importlib.import_module(f".{spec.prompt_module}", package=__name__)
        prompt_spec = getattr(module, "FORM_PROMPT_SPEC")
        if not isinstance(prompt_spec, FormPromptSpec):
            raise TypeError(
                f"Module app.prompts.forms.{spec.prompt_module} must expose "
                "FORM_PROMPT_SPEC: FormPromptSpec"
            )
        if prompt_spec.form_type != spec.form_type:
            raise ValueError(
                f"FormPromptSpec.form_type='{prompt_spec.form_type}' does not match "
                f"FormSpec.form_type='{spec.form_type}' in {spec.prompt_module}"
            )
        registry[spec.form_type] = prompt_spec
    return registry


FORM_PROMPT_REGISTRY: dict[str, FormPromptSpec] = _load_registry()


def get_form_prompt_spec(form_type: str | None) -> FormPromptSpec:
    """Return the FormPromptSpec for `form_type`.

    Raises KeyError when the form is not registered. Callers MUST NOT fall back
    silently to another form (e.g. I-914) — historical bugs were caused by
    `_get_form_label` defaulting to I-914 when the form_type was unknown.
    """
    from ...services.form_registry import normalize_form_type

    normalized = normalize_form_type(form_type) or ""
    spec = FORM_PROMPT_REGISTRY.get(normalized)
    if spec is None:
        raise KeyError(
            f"No FormPromptSpec registered for form_type='{form_type}' "
            f"(normalized to '{normalized}'). Registered: {sorted(FORM_PROMPT_REGISTRY)}"
        )
    return spec


def try_get_form_prompt_spec(form_type: str | None) -> FormPromptSpec | None:
    """Like `get_form_prompt_spec` but returns None for unknown forms."""
    try:
        return get_form_prompt_spec(form_type)
    except KeyError:
        return None


__all__ = [
    "FORM_PROMPT_REGISTRY",
    "FormPromptSpec",
    "get_form_prompt_spec",
    "try_get_form_prompt_spec",
]
