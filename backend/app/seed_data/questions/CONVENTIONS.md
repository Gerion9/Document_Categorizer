# Questionnaire JSON Conventions

Cada formulario USCIS soportado por el pipeline de auto-llenado tiene dos JSON
en este directorio: `<compact>_form_client.json` (preguntas del cliente) y
`<compact>_form_attorney.json` (preguntas del abogado). El compact code es el
form_type sin guion (`i914`, `i765`, `i192`, `i360`, `i914a`, `g28`, `g1145`).

Estas convenciones son evaluadas en arranque por
`app.services.startup_validation._validate_questionnaire_json_schemas`. El
modelo Pydantic canonico vive en `app/schemas/questionnaire_json.py`.

## Estructura

El archivo es una lista de paginas (`pages`). Cada pagina tiene `page` (entero,
1-indexado) e `items` (lista de preguntas). Opcionalmente, `excluded_sections`
documenta partes del PDF que se omiten deliberadamente con `name` y `reason`.

```json
[
  {
    "page": 1,
    "items": [
      { "id": "p1_purpose", "code": "1", "type": "single_choice", ... }
    ],
    "excluded_sections": [
      { "name": "Part 5", "reason": "No aplica para SIJS" }
    ]
  }
]
```

## Item: campos obligatorios

| Campo | Tipo | Notas |
|---|---|---|
| `id` | string | **Semantico**, snake_case, prefijado por parte (p. ej. `p2_full_name`). Es el id estable que persiste en BD. |
| `code` | string | **Compacto**, refleja el codigo del PDF (`"1"`, `"2.1"`, `"2.2-2.4"`). Sigue el patron usado por I-914/I-765/I-192. |
| `type` | enum | Uno de: `text`, `textarea`, `date`, `date_or_text`, `number`, `yes_no`, `single_choice`, `select`, `checkbox`, `signature`, `note`, `group`, `repeatable_group`, `table`. |
| `responsible_party` | enum | `client` o `attorney`. |

`label` es opcional cuando el item usa `form_text` para mostrar la pregunta
literal del PDF (patron heredado de I-914). Para items nuevos se recomienda
poblar ambos: `form_text` con el texto literal del PDF y `label` con un titulo
corto para la UI.

## Item: campos recomendados (obligatorios en Fase 5)

| Campo | Proposito |
|---|---|
| `instruction` | Indicacion concreta al IA sobre como interpretar la pregunta, formato esperado y ambiguedades a evitar. **Debe describir intencion**, no parafrasear el PDF. |
| `where_to_verify` | Fuente(s) de verificacion priorizadas (`BIO CALL`, `Declaration`, `FBI Report`, etc.) usadas tanto por el llenado como por el QC. |
| `section` | Encabezado de la seccion del PDF (`"Part 2. Information About You"`). |

## Sub-fields y details_fields

Items con `type: "group"` o `type: "repeatable_group"` agrupan inputs en
`fields` (campos del grupo). Items con respuestas condicionales (`yes_no` +
follow-up) usan `details_fields`. Cada sub-field obedece la misma forma que un
item (`id`, `type`, `label`, `instruction`, `where_to_verify`, etc.) pero su id
es relativo al item padre y se concatena como `<item_id>.<field_id>` al
persistirse.

## Opciones

Para `single_choice`, `yes_no`, `select` y `checkbox`, las opciones se declaran
como una lista de `{"label": str, "value": str}`. La forma heredada (lista de
strings cortos como `["Apt.", "Ste.", "Flr."]`) se acepta por compatibilidad y
se normaliza automaticamente, pero **JSONs nuevos deben usar la forma explicita**.

## Patrones reutilizables

### Apt./Ste./Flr.
Cualquier direccion con tipo de unidad debe declarar las opciones exactamente
como en el PDF: `"Apt."`, `"Ste."`, `"Flr."` (incluyendo el punto). El prompt
de auto-llenado normaliza Apartment/Suite/Floor a esos valores literalmente.

### Other Names (alias)
Use `type: "repeatable_group"` con `fields: [family, given, middle]`. El item
representa una sola entrada repetible; el motor de llenado pide UN valor por
campo y deja que el cliente repita la fila para alias adicionales.

### Direcciones
Patron canonico: `street`, `unit_type` (Apt./Ste./Flr.), `unit_number`,
`city`, `state` (USPS 2-letras cuando aplica), `zip_code`, `country`. Para
direcciones extranjeras anada `province` y `postal_code`.

### Fechas
`type: "date"` con `format: "Mmm DD YYYY"` (formato canonico ingles). Use
`date_or_text` solo cuando el campo acepta literalmente "PRESENT" u otra
palabra reservada; declarela en `allow_literal_values`.

## Compatibilidad de migracion

Cuando se renombra el `id` de un item (por ejemplo, al pasar de `p2_1` a
`p2_full_name`), agrega el id antiguo a `also_validate_with` para que los
registros historicos sigan vinculandose. El script de migracion en
`scripts/migrate_questionnaire_ids.py` aplica el mapeo a `questionnaire_item_id`
en la BD.

## No mezclar contenido de formulario con contenido legal

`instruction` describe COMO llenar. `where_to_verify` describe DONDE buscar la
evidencia. No incluyas ninguno de los dos en `label` o `form_text`; reserva
esos campos para reproducir el PDF.
