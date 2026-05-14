"""I-914 specific prompt rules.

Hosts the entire I-914 hard-rules block previously embedded in
`form_filling_prompts.py`: events taxonomy, Part 4/9 yes-no hard rules,
Part 4 completeness rule, Part 9 addendum rule, Part 5 family-member pivot,
and the I-914 verification context. The base prompt builders consume this via
`FormPromptSpec`.
"""

from __future__ import annotations

from ._spec import FormPromptSpec, NarrativeFieldMarker


_I914_VERIFICATION_CONTEXT = "\n".join(
    [
        "Estructura del formulario I-914:",
        "- Part 1: Proposito (seleccion A o B segun el caso T-1)",
        "- Part 2: Info general (sexo, estado civil, DOB - items 8-10)",
        "- Part 3: Elegibilidad de trata (3.1-3.11: victima de trata severa, "
        "cooperacion con LEA, presencia fisica, hardship, reporte, edad, "
        "entradas previas, EAD, familiares)",
        "- Part 4: Procesamiento (4.1: criminal/LEA, 4.2: prostitucion/contrabando/drogas, "
        "4.3: seguridad/terrorismo/espionaje, 4.4: presencia cerca de dano/proceedings, "
        "4.5: tortura/genocidio, 4.6: militar/paramilitar, 4.7: penalidades civiles/fraude, "
        "4.8: salud)",
        "- Part 5: Miembros familiares (5.1-5.13)",
        "- Part 6: Declaracion y firma",
        "- Part 7: Interprete",
        "- Part 8: Preparador",
        "- Part 9: Informacion adicional",
    ]
)


_I914_TAXONOMY_RULES = "\n".join(
    [
        "Taxonomia de eventos I-914 (reglas duras):",
        "- Eventos MIGRATORIOS y CRIMINALES son categorias distintas. Nunca los mezcles.",
        "  Categorias migratorias: IMMIGRATION_DETENTION, NTA_ISSUED,",
        "  REMOVAL_PROCEEDINGS_INITIATED, REMOVAL_PROCEEDINGS_PENDING, REMOVAL_ORDER,",
        "  DEPORTED_EXCLUDED, DENIAL_OF_ADMISSION, VOLUNTARY_DEPARTURE_GRANTED,",
        "  VOLUNTARY_DEPARTURE_OVERSTAYED.",
        "  Categorias criminales: CRIMINAL_ARREST, CRIMINAL_CITATION, CRIMINAL_DETENTION,",
        "  FORMAL_CHARGE, DIVERSION_DEFERRED_WITHHELD, CONVICTION,",
        "  PROBATION_PAROLE_SUSPENDED, JAIL_PRISON.",
        "- Mapeo obligatorio a items Part 4:",
        "  * IMMIGRATION_DETENTION / CRIMINAL_ARREST / CRIMINAL_CITATION / CRIMINAL_DETENTION -> 4.1.B.",
        "  * FORMAL_CHARGE -> 4.1.C.",
        "  * CONVICTION -> 4.1.D.",
        "  * DIVERSION_DEFERRED_WITHHELD -> 4.1.E.",
        "  * PROBATION_PAROLE_SUSPENDED -> 4.1.F.",
        "  * JAIL_PRISON -> 4.1.G.",
        "  * NTA_ISSUED / REMOVAL_PROCEEDINGS_INITIATED -> 4.9.B.",
        "  * REMOVAL_PROCEEDINGS_PENDING -> 4.9.A (y 4.9.B si el proceso fue iniciado).",
        "  * REMOVAL_ORDER -> 4.9.D.",
        "  * DEPORTED_EXCLUDED -> 4.9.C.",
        "  * DENIAL_OF_ADMISSION -> 4.9.E.",
        "  * VOLUNTARY_DEPARTURE_OVERSTAYED -> 4.9.F.",
        "- Nunca uses 'law enforcement' para eventos migratorios. Usa CBP, ICE, DHS,",
        "  immigration authorities, border authorities o immigration officers segun lo que",
        "  diga el documento.",
        "- Una deteccion migratoria NO implica arresto criminal, charge, conviction,",
        "  probation, jail, removal order, deportation, denial of admission ni voluntary",
        "  departure. Cada consecuencia requiere evidencia explicita y separada.",
        "- Proceedings iniciados != orden de remocion. NTA issued != removal order.",
        "  Formal charge != conviction. CBP hold / hielera / short border processing",
        "  != jail or prison.",
        "- Part 9 debe responder UNICAMENTE la pregunta del item citado. Nunca reutilices",
        "  la misma oracion o el mismo parrafo para items distintos (por ejemplo 4.1.B vs",
        "  4.9.B). Cada item obtiene una explicacion propia basada en su categoria.",
        "- Wording conservador cuando la evidencia solo venga de narrativa (declaration o",
        "  intake): usa 'on or about' para fechas aproximadas, 'in or near' para lugares",
        "  imprecisos y 'if known' para datos faltantes.",
    ]
)


_I914_ITEM_HINTS: dict[str, str] = {
    "p4_1d": (
        "Item 4.1.D (I-914) pregunta sobre CONDENA (conviction). Solo responde 'Yes' "
        "si la evidencia muestra explicitamente una condena, una sentencia culpable, "
        "o un plea of guilty. Un arresto, una citacion, un cargo formal o una diversion "
        "NO bastan para responder 'Yes' aqui."
    ),
    "p4_1e": (
        "Item 4.1.E (I-914) pregunta sobre programas de diversion, deferred adjudication "
        "o withheld adjudication. Solo responde 'Yes' si la evidencia menciona uno de esos "
        "programas explicitamente. Una condena tipica NO va aqui."
    ),
    "p4_1f": (
        "Item 4.1.F (I-914) pregunta sobre probation, parole o suspended sentence. Solo "
        "responde 'Yes' si la evidencia menciona explicitamente alguno de esos tres."
    ),
    "p4_1g": (
        "Item 4.1.G (I-914) pregunta si el aplicante ESTUVO EN jail o prison. Solo responde "
        "'Yes' si la evidencia muestra explicitamente una sentencia o tiempo servido en jail "
        "o prison. Un CBP hold, hielera, ICE detention o short-term immigration processing "
        "NO cuentan como jail or prison."
    ),
    "p4_9a": (
        "Item 4.9.A (I-914) pregunta si los procesos de removal/exclusion/deportation "
        "estan PENDIENTES actualmente. Solo responde 'Yes' si la evidencia muestra un caso "
        "abierto actualmente en EOIR o en inmigration court."
    ),
    "p4_9b": (
        "Item 4.9.B (I-914) pregunta si procesos de removal/exclusion/deportation fueron "
        "INICIADOS en algun momento (NTA issued, placed in removal proceedings). No es lo "
        "mismo que una deteccion migratoria breve. Responde 'Yes' solo si hay evidencia "
        "explicita de NTA o de inicio de proceedings."
    ),
    "p4_9c": (
        "Item 4.9.C (I-914) pregunta si el aplicante ALGUNA VEZ fue removed, excluded o "
        "deported fisicamente de Estados Unidos. Responde 'Yes' solo si la evidencia muestra "
        "que la remocion fue ejecutada (no solo ordenada)."
    ),
    "p4_9d": (
        "Item 4.9.D (I-914) pregunta si el aplicante ALGUNA VEZ fue ORDENADO a ser removed, "
        "excluded o deported (orden formal, no la ejecucion). Responde 'Yes' solo con "
        "evidencia explicita de una orden de remocion."
    ),
    "p4_9e": (
        "Item 4.9.E (I-914) pregunta si al aplicante ALGUNA VEZ le negaron una visa o le "
        "negaron la admision a Estados Unidos. Responde 'Yes' solo si la evidencia lo "
        "muestra explicitamente."
    ),
    "p4_9f": (
        "Item 4.9.F (I-914) pregunta si al aplicante le concedieron salida voluntaria "
        "(voluntary departure) y NO SALIO dentro del plazo. Responde 'Yes' solo cuando "
        "ambos hechos (grant + overstay) esten documentados; un voluntary departure "
        "concedido y cumplido NO es 'Yes' aqui."
    ),
    "p3_9": (
        "Item 3.9 (I-914) describe las CIRCUNSTANCIAS DE LA LLEGADA MAS RECIENTE del "
        "aplicante a Estados Unidos, en conexion con el esquema de trafficking. Nunca "
        "uses la frase 'law enforcement' para describir autoridades migratorias; usa CBP, "
        "ICE, DHS, immigration authorities, border authorities o immigration officers segun "
        "el documento. No conviertas este campo en un historial criminal."
    ),
}


_I914_EXTRA_RULES: tuple[str, ...] = (
    "",
    "Regla de completitud Part 4 (I-914):",
    "- Si cualquier pregunta de Part 4 se responde 'Yes' (detencion, arresto, cargo criminal),",
    "  la tabla inferior que pide detalle (fecha, lugar, razon, resultado) DEBE completarse.",
    "- Usa la informacion de FBI Records, Declaration y LEA Report para construir la explicacion.",
    "- Si no cabe en el espacio de la tabla, indica que se requiere addendum en Part 9.",
    "",
    "Regla de addendum Part 9 (I-914):",
    "- Cada entrada de Part 9 debe indicar Page Number, Part Number e Item Number.",
    "- El contenido debe ser un parrafo factual basado en la evidencia del caso.",
    "- NO generar textos genericos como 'See attached declaration', 'Please refer to supporting documents',",
    "  'details to be confirmed', 'information will be provided later' o cualquier frase de relleno.",
    "- Usar datos especificos: fechas exactas en formato 'Mmm DD YYYY' (p. ej. 'Mar 21 1979'), lugares concretos (ciudad, estado),",
    "  nombres de agencias (CBP, ICE, DHS, EOIR), y resultados documentados.",
    "- Cada item de Part 9 debe tener un parrafo UNICO y diferenciado; nunca copiar el mismo",
    "  texto entre items distintos (p.ej. 4.1.B vs 4.9.B son preguntas diferentes y requieren",
    "  explicaciones diferentes enfocadas en su categoria especifica).",
    "- Si la evidencia es insuficiente para un parrafo factual, devuelve cadena vacia y confidence: low.",
    "",
    "Regla de Part 5 - Miembros Familiares (I-914):",
    "- Los campos de Part 5 (5.1 Spouse, 5.2 Children) requieren datos de FAMILIARES, NO del aplicante principal.",
    "- Para el conyuge (5.1): buscar nombre completo, fecha de nacimiento, pais de nacimiento,",
    "  ciudad y pais de residencia actual del ESPOSO/ESPOSA del aplicante.",
    "- Para los hijos (5.2): buscar nombre completo, fecha de nacimiento, pais de nacimiento,",
    "  ciudad, estado y pais de residencia actual de CADA HIJO/HIJA.",
    "- Fuentes tipicas: declaracion del aplicante, formularios I-914A (derivados), BioCall, documentos familiares.",
    "- Si el documento menciona 'spouse', 'esposo/a', 'husband', 'wife', 'hijo/a', 'child', 'son', 'daughter',",
    "  esos datos corresponden a los campos de Part 5.",
    "- NO confundir datos del aplicante principal con los de familiares.",
)


FORM_PROMPT_SPEC = FormPromptSpec(
    form_type="i-914",
    form_label="I-914 - Application for T Nonimmigrant Status",
    short_label="I-914",
    verification_context=_I914_VERIFICATION_CONTEXT,
    item_hints=_I914_ITEM_HINTS,
    narrative_fields=(NarrativeFieldMarker(item_id="p9_entries", field_id="additional_information"),),
    taxonomy_rules=_I914_TAXONOMY_RULES,
    form_filling_extra_rules=_I914_EXTRA_RULES,
    batch_family_member_pivot_ids=("p5_1", "p5_children"),
    uses_question_value_semantics=True,
)
