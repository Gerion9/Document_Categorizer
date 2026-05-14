"""I-914A (Supplement A, derivative T) prompt rules."""

from __future__ import annotations

from ._spec import FormPromptSpec


_I914A_VERIFICATION_CONTEXT = "\n".join(
    [
        "Estructura del formulario I-914A:",
        "- Part 1: Relacion familiar (Spouse/Child/Parent/Sibling under 18)",
        "- Part 2: Info del principal (nombre, DOB, A-Number, status del I-914)",
        "- Part 3: Info del derivado (nombre, direccion, A-Number, SSN, sexo, estado civil, "
        "DOB, pasaporte, status migratorio, historial de entradas)",
        "- Part 4: Procesamiento (criminal, prostitucion, terrorismo, presencia cerca de dano, "
        "proceedings migratorios)",
        "- Part 5: Declaracion y firma del aplicante",
        "- Part 6: Interprete",
        "- Part 7: Preparador",
        "- Part 8: Informacion adicional",
    ]
)


FORM_PROMPT_SPEC = FormPromptSpec(
    form_type="i-914a",
    form_label="I-914 Supplement A (I-914A) - Application for Derivative T Nonimmigrant Status",
    short_label="I-914A",
    verification_context=_I914A_VERIFICATION_CONTEXT,
)
