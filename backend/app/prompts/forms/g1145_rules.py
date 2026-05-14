"""G-1145 (E-Notification of Application/Petition Acceptance) prompt rules."""

from __future__ import annotations

from ._spec import FormPromptSpec


_G1145_VERIFICATION_CONTEXT = "\n".join(
    [
        "Estructura del formulario G-1145:",
        "- Pagina unica que solicita notificaciones electronicas (email/SMS) cuando USCIS "
        "acepta la aplicacion o peticion del aplicante.",
        "- Campos requeridos: Family Name (Last Name), Given Name (First Name), "
        "Applicant E-mail Address, Applicant Mobile Phone Number (Texting).",
        "- El G-1145 se grapa o adjunta a la primera pagina del paquete enviado a USCIS.",
        "- No tiene Parts; sus datos vienen del aplicante (Part 2 del I-914 o I-765).",
    ]
)


FORM_PROMPT_SPEC = FormPromptSpec(
    form_type="g-1145",
    form_label="G-1145 - E-Notification of Application/Petition Acceptance",
    short_label="G-1145",
    verification_context=_G1145_VERIFICATION_CONTEXT,
)
