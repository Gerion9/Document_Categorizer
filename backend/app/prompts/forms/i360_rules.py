"""I-360 (SIJS scope) prompt rules."""

from __future__ import annotations

from ._spec import FormPromptSpec


_I360_VERIFICATION_CONTEXT = "\n".join(
    [
        "Estructura del formulario I-360 (alcance Special Immigrant Juvenile - SIJS):",
        "- Part 1: Informacion del peticionario (nombre legal, USCIS online account, SSN, "
        "A-Number, fecha de nacimiento, lugar de nacimiento, estado civil)",
        "- Part 2: Informacion del beneficiario - normalmente igual al peticionario para SIJS "
        "self-petitions (verificar coincidencia)",
        "- Part 3: Direccion (mailing/postal address y physical address actual)",
        "- Part 4: Tipo de peticionario y clasificacion SIJ (seleccion de SIJ entre las "
        "opciones de Special Immigrant)",
        "- Parts 5-7: NO aplican para SIJS (Amerasian, Widow(er), Religious Worker, "
        "Iraqi/Afghan translator) - deben quedar en blanco",
        "- Part 8: SIJ Findings (informacion de la juvenile court order: nombre de la corte, "
        "numero de caso, fecha de la orden, hallazgos sobre custodia, reunificacion familiar, "
        "interes superior del menor)",
        "- Parts 9-10: NO aplican para SIJS - deben quedar en blanco",
        "- Part 11: Procesamiento (consulado, prior proceedings, adjustment status)",
        "- Part 12: Contacto y firma del peticionario",
        "- Part 13: Interprete",
        "- Part 14: Preparador",
        "- Additional Information section (similar a Part 9 de I-914): referencias "
        "Page/Part/Item para hojas adicionales",
    ]
)


FORM_PROMPT_SPEC = FormPromptSpec(
    form_type="i-360",
    form_label="I-360 - Petition for Amerasian, Widow(er), or Special Immigrant (SIJS)",
    short_label="I-360",
    verification_context=_I360_VERIFICATION_CONTEXT,
)
