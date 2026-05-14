"""G-28 (Notice of Entry of Appearance as Attorney/Accredited Representative) prompt rules."""

from __future__ import annotations

from ._spec import FormPromptSpec


_G28_VERIFICATION_CONTEXT = "\n".join(
    [
        "Estructura del formulario G-28:",
        "- Part 1: Informacion sobre el attorney o accredited representative "
        "(nombre completo, EOIR ID number, USCIS Online Account, direccion postal del attorney, "
        "telefono, fax, email, bar admission - state/highest court y bar number, "
        "informacion de licencia profesional, accredited representative info)",
        "- Part 2: Notice of appearance (formulario al que aplica esta representacion, "
        "lista de formularios USCIS, indicacion de receipt number cuando aplica)",
        "- Part 3: Informacion del cliente (nombre legal completo del cliente, contacto y "
        "direccion del cliente, A-Number, USCIS Online Account, sexo, fecha de nacimiento)",
        "- Part 4: Autorizaciones del cliente (release of information, notification "
        "preferences, secure document delivery)",
        "- Part 5: Signature del cliente",
        "- Part 6: Signature del attorney / accredited representative",
        "- Parts 7-8: Espacios reservados / interprete / preparador segun aplique",
        "- Part 9: Informacion adicional (Page/Part/Item references)",
    ]
)


FORM_PROMPT_SPEC = FormPromptSpec(
    form_type="g-28",
    form_label="G-28 - Notice of Entry of Appearance as Attorney or Accredited Representative",
    short_label="G-28",
    verification_context=_G28_VERIFICATION_CONTEXT,
)
