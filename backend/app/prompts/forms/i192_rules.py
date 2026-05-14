"""I-192 (Application for Advance Permission to Enter as Nonimmigrant) prompt rules."""

from __future__ import annotations

from ._spec import FormPromptSpec


_I192_VERIFICATION_CONTEXT = "\n".join(
    [
        "Estructura del formulario I-192:",
        "- Global: Info de representante (G-28, Attorney Bar Number, USCIS Online Account Number)",
        "- Part 1: Tipo de aplicacion (seleccion de permiso solicitado, T-Visa)",
        "- Part 2: Info del aplicante con subsecciones:",
        "  - A: Nombre/Aliases (nombre legal completo, otros nombres usados)",
        "  - B: Otra info (A-Number, USCIS Account, DOB, lugar nacimiento, ciudadania, sexo, "
        "direccion postal, direccion fisica, historial de direcciones 5 anos)",
        "  - C: Historial marital (si aplica; puede omitirse si se presenta con I-914/I-914A)",
        "  - D: Explicacion de inadmisibilidad (motivos de inadmisibilidad que aplican al caso)",
        "  - E: I-192 previo, presencia en US, filings previos, denegaciones, historial criminal "
        "(items 27-36)",
        "  - F: Info de viaje (items 37-43; puede omitirse para T/U en US)",
        "  - G: Historial de empleo (items 44-45, ultimos 5 anos)",
        "- Part 3: Declaracion, contacto y firma del aplicante",
        "- Part 4: Interprete (nombre, contacto, idioma, certificacion, firma)",
        "- Part 5: Preparador (nombre, contacto, declaracion, firma)",
        "- Part 6: Informacion adicional (nombre, A-Number, referencias Page/Part/Item)",
        "- Inadmissibility Spotter: Sub-checklist de deteccion de causales de inadmisibilidad "
        "basado en declaracion (INA 212(a) grounds)",
    ]
)


FORM_PROMPT_SPEC = FormPromptSpec(
    form_type="i-192",
    form_label="I-192 - Application for Advance Permission to Enter as a Nonimmigrant",
    short_label="I-192",
    verification_context=_I192_VERIFICATION_CONTEXT,
)
