# Document Categorizer & Extractor

Sistema de clasificacion, indexacion y verificacion de documentos legales para la oficina **Manuel Solis**.

Permite ingerir PDFs e imagenes, organizarlos visualmente en una taxonomia jerarquica, verificar cumplimiento contra checklists trazables y extraer texto con IA (Google Gemini).

---

## Tabla de contenidos

- [Arquitectura](#arquitectura)
- [Requisitos previos](#requisitos-previos)
- [Instalacion](#instalacion)
- [Configuracion de Gemini (opcional)](#configuracion-de-gemini-opcional)
- [Ejecucion](#ejecucion)
- [Flujo de uso](#flujo-de-uso)
- [Estructura del proyecto](#estructura-del-proyecto)
- [API Reference](#api-reference)
- [Conceptos clave](#conceptos-clave)

---

## Arquitectura

```
Frontend (React + Vite + TypeScript)
        |
        | Vite proxy (/api, /storage)
        v
Backend (FastAPI + SQLAlchemy + SQLite)
        |
        |--- PyMuPDF     : Split PDFs en paginas, genera miniaturas
        |--- ReportLab   : Genera PDF consolidado y reportes
        |--- Google Gemini: OCR inteligente y extraccion de tablas
        |
        v
   storage/          data/app.db
   (paginas, thumbs)  (SQLite)
```

- **Backend**: Python 3.10+, FastAPI, SQLAlchemy (SQLite local).
- **Frontend**: React 18, TypeScript, Tailwind CSS, dnd-kit (drag & drop).
- **IA**: Google Gemini 2.0 Flash para OCR y extraccion de tablas en markdown.

---

## Requisitos previos

| Componente | Version minima |
|------------|---------------|
| Python     | 3.10+         |
| Node.js    | 18+           |
| npm        | 9+            |

---

## Instalacion

### 1. Clonar el repositorio

```bash
git clone <url-del-repo>
cd Document_Categorizer_Extractor
```

### 2. Backend

```bash
cd backend

# Crear entorno virtual
python -m venv venv

# Activar (Windows PowerShell)
.\venv\Scripts\Activate.ps1

# Activar (Linux/Mac)
# source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

### 3. Frontend

```bash
cd frontend
npm install
```

---

## Configuracion de Gemini (opcional)

Para habilitar la extraccion de texto con IA, necesitas una API key de Google Gemini.

1. Obtener tu key en: https://aistudio.google.com/app/apikey
2. Crear el archivo `backend/.env`:

```
GEMINI_API_KEY=tu-api-key-aqui
```

> Sin esta key, el sistema funciona normalmente pero los botones de extraccion de texto no estaran disponibles.

---

## Ejecucion

### Backend (terminal 1)

```bash
cd backend
.\venv\Scripts\Activate.ps1          # Windows
# source venv/bin/activate           # Linux/Mac

uvicorn app.main:app --reload --port 8000
```

El backend estara en `http://localhost:8000`.

### Frontend (terminal 2)

```bash
cd frontend
npm run dev
```

El frontend estara en `http://localhost:5173`.

### Verificar

- Abrir `http://localhost:5173` en el navegador.
- El health check del backend esta en `http://localhost:8000/api/health`.

---

## Flujo de uso

### 1. Dashboard

Al abrir la aplicacion veras el dashboard con los casos existentes. Crea un nuevo caso con nombre y descripcion.

### 2. Tab "Paginas" - Ingesta de documentos

- Arrastra PDFs o imagenes al area de upload (o haz clic para seleccionar archivos).
- Cada PDF se separa automaticamente en paginas individuales con miniatura.
- Las paginas aparecen en estado "sin clasificar".

### 3. Tab "Organizar" - Clasificacion visual

El workspace tiene 3 columnas:

| Izquierda | Centro | Derecha |
|-----------|--------|---------|
| Arbol de documentos (tipos + secciones jerarquicas) | Drop zones de cada seccion | Paginas sin clasificar |

- **Crear estructura**: En el panel izquierdo, crea tipos de documento (ej. "FBI Records", codigo "B") y secciones/subsecciones a cualquier profundidad (ej. B.1 Introduccion, B.2 Desarrollo, B.2.1 Antecedentes).
- **Clasificar**: Arrastra paginas desde la columna derecha hacia las drop zones del centro.
- **Indicador de tablas**: Cada tipo de documento tiene un toggle para indicar si contiene tablas (cambia el modo de extraccion con Gemini).

### 4. Plantillas reutilizables

- Haz clic en el icono de plantilla en el panel de documentos.
- Selecciona una plantilla predefinida para aplicarla al caso.
- La plantilla crea automaticamente: tipos de documento, secciones jerarquicas, checklists y el **mapa de conexiones** entre items del checklist y secciones destino.

### 5. Tab "Checklist" - Verificacion trazable

- Crea checklists con items descriptivos.
- Cada item puede vincularse a **secciones destino** (donde buscar la evidencia) usando el boton de MapPin.
- Los chips de seccion destino son clicables: te llevan directo a esa seccion en el tab Organizar.
- Vincula paginas como evidencia seleccionandolas y haciendo clic en el icono de link.
- Cicla el estado de cada item: pendiente → completo → incompleto → N/A.

### 6. Extraccion con IA (Gemini)

- En el preview de cualquier pagina, haz clic en "Extraer texto" o "Extraer tablas".
- **Modo texto** (OCR): Extrae texto plano preservando estructura de parrafos.
- **Modo tablas** (Gemini Vision): Extrae contenido incluyendo tablas en formato Markdown.
- El texto extraido se muestra en un panel lateral y se puede copiar al clipboard.
- Tambien puedes extraer todas las paginas de una seccion con el boton "Extraer todo".

### 7. Tab "Exportar"

- Descarga el PDF consolidado con indice de contenidos.
- Descarga el reporte de cumplimiento del checklist.
- Revisa el log de auditoria de todas las acciones.

---

## Estructura del proyecto

```
Document_Categorizer_Extractor/
├── backend/
│   ├── app/
│   │   ├── main.py              # Entry point FastAPI + migraciones
│   │   ├── database.py          # Configuracion SQLAlchemy / SQLite
│   │   ├── models.py            # Modelos ORM (Case, DocType, Section, Page, Checklist, Templates...)
│   │   ├── schemas.py           # Schemas Pydantic (request/response)
│   │   ├── routers/
│   │   │   ├── cases.py         # CRUD de casos
│   │   │   ├── documents.py     # Tipos de documento y secciones (jerarquia multi-nivel)
│   │   │   ├── pages.py         # Upload, clasificacion, reordenamiento de paginas
│   │   │   ├── checklist.py     # Checklists, items, evidencia, targets de seccion
│   │   │   ├── templates.py     # Biblioteca global de plantillas + apply-to-case
│   │   │   ├── extraction.py    # Extraccion de texto con Gemini (OCR / tablas)
│   │   │   └── export.py        # Exportacion PDF y reportes
│   │   └── services/
│   │       ├── pdf_service.py       # Split PDF, miniaturas, procesamiento de imagenes
│   │       ├── extraction_service.py # Integracion con Google Gemini Vision
│   │       └── export_service.py    # Generacion de PDF consolidado y reporte
│   ├── requirements.txt
│   ├── data/                    # Base de datos SQLite (gitignored)
│   └── storage/                 # Archivos subidos, paginas, miniaturas (gitignored)
│
├── frontend/
│   ├── src/
│   │   ├── main.tsx             # Entry point React
│   │   ├── App.tsx              # Rutas principales
│   │   ├── types/index.ts       # Tipos TypeScript (mirrors backend schemas)
│   │   ├── api/client.ts        # Cliente Axios centralizado
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx    # Lista de casos
│   │   │   └── CaseWorkspace.tsx # Workspace principal (tabs, DnD, preview)
│   │   └── components/
│   │       ├── Layout.tsx       # Header comun
│   │       ├── FileUpload.tsx   # Drag & drop upload
│   │       ├── DocumentTree.tsx # Arbol jerarquico + plantillas
│   │       ├── SectionDropZone.tsx # Drop zone para clasificar paginas
│   │       ├── PageThumbnail.tsx   # Miniatura de pagina con indicadores
│   │       ├── ChecklistPanel.tsx  # Checklists con mapeo a secciones
│   │       ├── ExportDialog.tsx    # Links de descarga
│   │       └── AuditLog.tsx       # Log de auditoria
│   ├── vite.config.ts           # Proxy /api y /storage al backend
│   ├── tailwind.config.js
│   └── package.json
│
├── .gitignore
└── README.md
```

---

## API Reference

### Casos

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/api/cases` | Listar casos |
| POST | `/api/cases` | Crear caso |
| GET | `/api/cases/{id}` | Obtener caso |
| PUT | `/api/cases/{id}` | Actualizar caso |
| DELETE | `/api/cases/{id}` | Eliminar caso |

### Tipos de documento y secciones

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/api/cases/{id}/document-types` | Listar tipos (con arbol de secciones) |
| POST | `/api/cases/{id}/document-types` | Crear tipo de documento |
| PUT | `/api/document-types/{id}` | Actualizar tipo |
| DELETE | `/api/document-types/{id}` | Eliminar tipo |
| POST | `/api/document-types/{id}/sections` | Crear seccion (soporta `parent_section_id`) |
| PUT | `/api/sections/{id}` | Actualizar seccion |
| DELETE | `/api/sections/{id}` | Eliminar seccion (y subsecciones) |
| GET | `/api/cases/{id}/sections-flat` | Todas las secciones como lista plana |

### Paginas

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| POST | `/api/cases/{id}/upload` | Subir PDFs/imagenes (multipart) |
| GET | `/api/cases/{id}/pages` | Listar paginas (filtros: status, section_id) |
| PUT | `/api/pages/{id}/classify` | Clasificar pagina en seccion |
| PUT | `/api/pages/{id}/unclassify` | Desclasificar pagina |
| PUT | `/api/pages/{id}/extra` | Marcar como extra |
| DELETE | `/api/pages/{id}` | Eliminar pagina |

### Checklists

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/api/cases/{id}/checklists` | Listar checklists (con items, evidencias, targets) |
| POST | `/api/cases/{id}/checklists` | Crear checklist |
| POST | `/api/checklists/{id}/items` | Agregar item |
| PUT | `/api/checklist-items/{id}` | Actualizar item (status, targets) |
| PUT | `/api/checklist-items/{id}/targets` | Upsert secciones destino del item |
| POST | `/api/checklist-items/{id}/evidence` | Vincular pagina como evidencia |
| DELETE | `/api/evidence-links/{id}` | Eliminar evidencia |

### Plantillas

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/api/templates` | Listar plantillas globales |
| POST | `/api/templates` | Crear plantilla |
| POST | `/api/templates/{id}/nodes` | Agregar nodo al arbol de la plantilla |
| POST | `/api/templates/{id}/checklists` | Agregar checklist con items y mapeos |
| POST | `/api/cases/{id}/apply-template` | Aplicar plantilla a un caso |

### Extraccion (Gemini)

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/api/extraction/status` | Verificar si la API key esta configurada |
| POST | `/api/pages/{id}/extract` | Extraer texto de una pagina (background) |
| GET | `/api/pages/{id}/extraction` | Consultar resultado de extraccion |
| POST | `/api/cases/{id}/extract-batch` | Extraccion en lote |

### Exportacion

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/api/cases/{id}/export/pdf` | Descargar PDF consolidado |
| GET | `/api/cases/{id}/export/report` | Descargar reporte de cumplimiento |
| GET | `/api/cases/{id}/audit` | Log de auditoria |

---

## Conceptos clave

### Taxonomia jerarquica

```
Caso
 └── Tipo de Documento (ej. "FBI Records", codigo "B")
      ├── Seccion B.1 "Introduccion"
      ├── Seccion B.2 "Desarrollo"
      │    ├── Subseccion B.2.1 "Antecedentes"
      │    └── Subseccion B.2.2 "Resultados"
      └── Seccion B.3 "Conclusion"
```

Las secciones pueden anidarse a cualquier profundidad. Cada seccion tiene un `path_code` calculado automaticamente (ej. `B.2.1`).

### Mapa checklist → secciones

Cada item del checklist puede apuntar a una o varias secciones destino. Esto crea un **mapa de conexiones** que indica *donde buscar* la informacion para verificar cada requisito:

```
Checklist "Verificacion A"
  ├── A1: "Verificar antecedentes"  →  [B.2.1]
  ├── A2: "Revisar introduccion"    →  [B.1]
  └── A3: "Confirmar datos"         →  [B.2.1, C.1]
```

### Plantillas reutilizables

Una plantilla empaqueta:
- Un arbol de tipos de documento y secciones predeterminadas
- Checklists con items
- Mapeos item → seccion pre-configurados

Al aplicar una plantilla a un caso, todo se instancia automaticamente preservando las conexiones.

### Modos de extraccion

| Si el documento... | Se usa... | Resultado |
|--------------------|-----------|-----------|
| Solo tiene texto | Gemini OCR | Texto plano con estructura de parrafos |
| Contiene tablas | Gemini Vision (tablas) | Markdown con tablas formateadas |

El modo se configura por tipo de documento con el toggle de tablas.

