"""I-765 (Application for Employment Authorization) prompt rules."""

from __future__ import annotations

from ._spec import FormPromptSpec


_I765_VERIFICATION_CONTEXT = "\n".join(
    [
        "Estructura del formulario I-765:",
        "- Header: Info de representante legal (G-28, Attorney Bar Number, USCIS Online Account Number)",
        "- Part 1: Razon para aplicar (1.a permiso inicial, 1.b reemplazo/correccion, "
        "1.c renovacion; nombre legal completo)",
        "- Part 2: Identidad/Direccion/Otra info (aliases, direccion postal y fisica, A-Number, "
        "USCIS Account, sexo, estado civil, SSN, ciudadania, lugar/fecha nacimiento, I-94, "
        "pasaporte, status migratorio, SEVIS, categoria de elegibilidad, items condicionales "
        "STEM OPT / H-1B / criminal)",
        "- Part 3: Declaracion, contacto, certificacion y firma del aplicante (idioma, "
        "interprete, preparador, ABC settlement, firma en tinta)",
        "- Part 4: Interprete (nombre, organizacion, direccion, contacto, idioma, firma)",
        "- Part 5: Preparador (nombre, organizacion, direccion, contacto, declaracion "
        "attorney/non-attorney, firma)",
        "- Part 6: Informacion adicional (nombre, A-Number, Page/Part/Item references, "
        "hojas adicionales)",
    ]
)


FORM_PROMPT_SPEC = FormPromptSpec(
    form_type="i-765",
    form_label="I-765 - Application for Employment Authorization",
    short_label="I-765",
    verification_context=_I765_VERIFICATION_CONTEXT,
)
