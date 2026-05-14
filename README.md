# Document Categorizer & Extractor

Sistema de clasificacion, indexacion, verificacion y analisis inteligente de documentos legales para la oficina **Manuel Solis**.

Permite ingerir PDFs e imagenes, organizarlos en una taxonomia jerarquica, verificar cumplimiento contra checklists trazables, extraer texto con IA (Google Gemini), realizar busqueda semantica con RAG (Pinecone) y ejecutar verificacion automatica de calidad con AI Autopilot.

---

## Tabla de contenidos

- [Arquitectura](#arquitectura)
- [Tech Stack](#tech-stack)
- [Requisitos previos](#requisitos-previos)
- [Instalacion](#instalacion)
- [Configuracion](#configuracion)
- [Ejecucion](#ejecucion)
- [Autenticacion y roles](#autenticacion-y-roles)
- [Flujo de uso](#flujo-de-uso)
- [Estructura del proyecto](#estructura-del-proyecto)
- [API Reference](#api-reference)
- [Conceptos clave](#conceptos-clave)

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────────────┐
│  Frontend (React + Vite + TypeScript) — Puerto 5173             │
│  React Router · Tailwind CSS · Framer Motion · dnd-kit          │
│  AuthContext + sessionStorage (JWT) · Axios con interceptor     │
│  Proxy Vite: /api → backend:8001, /storage → backend:8001      │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP / REST
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Backend (FastAPI + Uvicorn) — Puerto 8001                      │
│  JWT Auth (SSO bridge con BOS) · RBAC (admin/supervisor/case)   │
│  SQLAlchemy + Alembic (migraciones) · Pydantic v2               │
│  14 routers: cases, documents, pages, checklist, qc_checklist,  │
│  templates, extraction, export, auth, admin, roles, permissions,│
│  teams, supervisor                                              │
└────────────────────────────┬────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────────┐
│ SQLite /     │    │ storage/     │    │ Google Gemini    │
│ PostgreSQL   │    │ (archivos,   │    │ (OCR, tablas,    │
│ (Alembic)    │    │  thumbs)     │    │  embeddings, QC) │
└──────────────┘    └──────────────┘    └───────┬──────────┘
                                                │
                                        ┌───────▼──────────┐
                                        │ Pinecone         │
                                        │ (Vector DB / RAG)│
                                        └──────────────────┘
```

---

## Tech Stack

### Frontend

| Tecnologia | Version | Uso |
|------------|---------|-----|
| React | ^18.3.1 | Libreria de UI |
| React DOM | ^18.3.1 | Renderizado DOM |
| TypeScript | ^5.5.4 | Tipado estatico |
| Vite | ^5.4.3 | Build tool y dev server |
| @vitejs/plugin-react | ^4.3.1 | Integracion React + Vite |
| React Router DOM | ^6.26.2 | Enrutamiento SPA |
| Tailwind CSS | ^3.4.10 | Framework de estilos utility-first |
| tailwindcss-animate | ^1.0.7 | Animaciones CSS con Tailwind |
| PostCSS | ^8.4.45 | Procesamiento CSS |
| Autoprefixer | ^10.4.20 | Prefijos CSS automaticos |
| Framer Motion | ^12.34.3 | Animaciones declarativas |
| @dnd-kit/core | ^6.1.0 | Drag & drop |
| @dnd-kit/sortable | ^8.0.0 | Ordenacion con drag & drop |
| @dnd-kit/utilities | ^3.2.2 | Utilidades DnD |
| @radix-ui/react-tooltip | ^1.2.8 | Tooltips accesibles (WAI-ARIA) |
| Lucide React | ^0.441.0 | Iconos SVG |
| react-hot-toast | ^2.4.1 | Notificaciones toast |
| Axios | ^1.7.4 | Cliente HTTP |

### Backend

| Tecnologia | Version | Uso |
|------------|---------|-----|
| Python | 3.10+ | Lenguaje principal |
| FastAPI | >=0.115.0 | Framework API REST |
| Uvicorn | >=0.30.6 | Servidor ASGI |
| SQLAlchemy | >=2.0.35 | ORM y acceso a BD |
| Alembic | >=1.18.0 | Migraciones de base de datos |
| Pydantic | >=2.9.2 | Validacion y schemas |
| PyJWT | >=2.8.0 | Autenticacion JWT |
| PyMuPDF (fitz) | — | Split PDF en paginas, miniaturas |
| Pillow | >=10.4.0 | Procesamiento de imagenes |
| ReportLab | >=4.2.2 | Generacion de PDF consolidados y reportes |
| aiofiles | >=24.1.0 | I/O asincrono de archivos |
| python-multipart | >=0.0.9 | Upload multipart/form-data |
| python-dotenv | >=1.0.0 | Carga de variables de entorno desde .env |
| psycopg2-binary | >=2.9.9 | Driver PostgreSQL |
| google-genai | >=1.0.0 | API Google Gemini (OCR, embeddings, verificacion QC) |
| Pinecone | — | Cliente para vector DB (RAG) |

### Servicios externos

| Servicio | Uso |
|----------|-----|
| SQLite | Base de datos local por defecto |
| PostgreSQL | Base de datos en produccion (alternativa configurable) |
| Google Gemini 2.0 Flash | OCR, extraccion de tablas, embeddings, verificacion QC automatica |
| Pinecone | Indice vectorial para busqueda semantica (RAG) |
| BOS (Laravel) | SSO externo — redirige con HMAC para autenticacion |

---

## Requisitos previos

| Componente | Version minima |
|------------|---------------|
| Python | 3.10+ |
| Node.js | 18+ |
| npm | 9+ |
| PostgreSQL | 13+ *(solo si se elige `pgsql` como BD)* |

---

## Instalacion

### 1. Clonar el repositorio

```bash
git clone <url-del-repo>
cd document-categorizer
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

## Configuracion

Copia el archivo de ejemplo y ajusta las variables segun tu entorno:

```bash
cp .env.example .env
```

### Variables de entorno

| Variable | Descripcion | Requerida |
|----------|-------------|-----------|
| `DB_CONNECTION` | Motor de BD: `sqlite` o `pgsql` | Si |
| `DB_HOST` | Host de PostgreSQL | Solo si `pgsql` |
| `DB_PORT` | Puerto de PostgreSQL | Solo si `pgsql` |
| `DB_USER` | Usuario de PostgreSQL | Solo si `pgsql` |
| `DB_PASSWORD` | Contraseña de PostgreSQL | Solo si `pgsql` |
| `DB_NAME` | Nombre de la base de datos | Solo si `pgsql` |
| `SECRET_KEY` | Clave general de la aplicacion | Si |
| `SSO_SECRET_KEY` | Clave HMAC para SSO con BOS | Si se usa SSO |
| `JWT_SECRET` | Clave para firmar tokens JWT | Si |
| `VITE_BOS_URL` | URL de redireccion a BOS (frontend) | Si se usa SSO |
| `GEMINI_API_KEY` | API key de Google Gemini | Para IA/OCR/RAG |
| `PINECONE_API_KEY` | API key de Pinecone | Para RAG |

> Sin `GEMINI_API_KEY`, el sistema funciona normalmente pero las funciones de extraccion de texto, indexacion RAG, busqueda semantica y verificacion QC automatica no estaran disponibles.

### Variables avanzadas (opcionales)

El archivo `backend/app/services/rag_config.py` expone variables de entorno adicionales para ajustar fino del pipeline RAG y Gemini:

| Grupo | Variables | Descripcion |
|-------|-----------|-------------|
| Modelos Gemini | `GEMINI_MODEL`, `GEMINI_VISION_MODEL` | Modelos a usar (default: `gemini-2.0-flash`) |
| Embeddings | `EMBEDDING_MODEL`, `EMBEDDING_DIMENSION`, `EMBEDDING_BATCH_SIZE` | Configuracion de embeddings |
| OCR | `OCR_CHUNK_SIZE`, `OCR_CHUNK_OVERLAP`, `OCR_TEMPERATURE` | Parametros de chunking y extraccion |
| Pinecone | `PINECONE_INDEX_OCR`, `PINECONE_NAMESPACE_PREFIX` | Indice y namespace en Pinecone |
| Retrieval | `RETRIEVAL_TOP_K`, `RETRIEVAL_PREFER_SCOPED_DOCUMENT` | Busqueda semantica |
| QC Autopilot | `QC_AUTOPILOT_BATCH_SIZE`, `QC_AUTOPILOT_EVIDENCE_TOP_K`, `QC_AUTOPILOT_LLM_BATCH_CONCURRENCY` | Verificacion automatica |
| Paralelismo | `MAX_EXTRACTION_WORKERS`, `EXTRACTION_BATCH_SIZE`, `CASE_EXTRACTION_PARALLEL_BATCHES` | Workers y concurrencia |
| Cache Gemini | `GEMINI_ENABLE_EXPLICIT_CACHE`, `GEMINI_CACHE_TTL_SECONDS` | Cache de prompts |

---

## Ejecucion

### Backend (terminal 1)

```bash
cd backend
.\venv\Scripts\Activate.ps1          # Windows
# source venv/bin/activate           # Linux/Mac

uvicorn app.main:app --reload --port 8001
```

El backend estara en `http://localhost:8001`.

### Frontend (terminal 2)

```bash
cd frontend
npm run dev
```

El frontend estara en `http://localhost:5173`.

### Verificar

- Abrir `http://localhost:5173` en el navegador.
- Health check del backend: `http://localhost:8001/api/health`.

---

## Autenticacion y roles

### Flujo SSO

1. BOS (Laravel) redirige al usuario al frontend con `email`, `name` y firma HMAC.
2. El frontend envia POST a `/api/sso-login`.
3. El backend verifica el HMAC, crea/actualiza el usuario (Just-in-Time) y devuelve un JWT local.
4. El frontend almacena el JWT en `sessionStorage` y lo envia en cada request via header `Authorization: Bearer <token>`.

### Roles y permisos (RBAC)

| Rol | Permisos |
|-----|----------|
| **admin** | Todas las tabs + gestion de roles y usuarios |
| **supervisor** | Pages, Organizar, QC Checklist, Exportar |
| **casemanager** | Pages, Organizar |

Los permisos granulares son: `tab.pages`, `tab.organize`, `tab.qc_checklist`, `tab.export`, `admin.manage_roles`.

### Rutas protegidas (frontend)

| Ruta | Acceso |
|------|--------|
| `/` | Todos los roles autenticados |
| `/cases/:caseId` | Todos los roles autenticados |
| `/teams` | `supervisor`, `admin` |
| `/team-members` | `admin` |

---

## Flujo de uso

### 1. Dashboard

Al abrir la aplicacion veras el dashboard con los casos existentes. Crea un nuevo caso con nombre y descripcion. Los casos pueden asignarse a usuarios y equipos.

### 2. Tab "Paginas" — Ingesta de documentos

- Arrastra PDFs o imagenes al area de upload (o haz clic para seleccionar archivos).
- Cada PDF se separa automaticamente en paginas individuales con miniatura.
- Las paginas aparecen en estado "sin clasificar".

### 3. Tab "Organizar" — Clasificacion visual

El workspace tiene 3 columnas:

| Izquierda | Centro | Derecha |
|-----------|--------|---------|
| Arbol de documentos (tipos + secciones jerarquicas) | Drop zones de cada seccion | Paginas sin clasificar |

- **Crear estructura**: Crea tipos de documento (ej. "FBI Records", codigo "B") y secciones/subsecciones a cualquier profundidad (ej. B.1, B.2, B.2.1).
- **Clasificar**: Arrastra paginas desde la columna derecha hacia las drop zones del centro.
- **Multi-seccion**: Una pagina puede vincularse a multiples secciones, con una seccion primaria y links secundarios.
- **Indicador de tablas**: Toggle por tipo de documento para cambiar el modo de extraccion con Gemini.

### 4. Plantillas reutilizables

- Selecciona una plantilla predefinida para aplicarla al caso.
- La plantilla crea automaticamente: tipos de documento, secciones jerarquicas, checklists y el mapa de conexiones.
- Plantillas de taxonomia incluidas: **I-914 Document Taxonomy**.

### 5. Tab "Checklist" — Verificacion trazable

- Crea checklists con items descriptivos.
- Cada item puede vincularse a **secciones destino** (donde buscar la evidencia) usando el boton de MapPin.
- Los chips de seccion destino son clicables: te llevan directo a esa seccion en el tab Organizar.
- Vincula paginas como evidencia seleccionandolas y haciendo clic en el icono de link.
- Cicla el estado de cada item: pendiente → completo → incompleto → N/A.

### 6. QC Checklists — Verificacion de calidad con IA

Sistema avanzado de checklists jerarquicos organizados en **Partes → Preguntas**:

- **Plantillas QC predefinidas**: I-914, I-914A (Supplement A), I-765, I-192.
- **Seeders automaticos**: Al aplicar una plantilla, se instancian todas las partes, preguntas y mapeos.
- **Link Presets**: Mapeos predefinidos entre preguntas y secciones del caso, con auto-link inteligente basado en matching de nombres.
- **AI Verify**: Verificacion puntual de una pregunta individual usando Gemini + evidencia contextual.
- **AI Verify All**: Verificacion de todas las preguntas de una parte con un solo clic.
- **AI Autopilot**: Verificacion automatica masiva que ejecuta un pipeline completo:
  1. Recopila evidencia semantica via Pinecone (RAG).
  2. Agrupa preguntas en batches.
  3. Envia a Gemini para evaluacion.
  4. Registra respuestas, notas y nivel de confianza.
- **Busqueda semantica**: Query en lenguaje natural contra el indice vectorial del caso.
- **Save as Template**: Guarda un QC checklist como plantilla reutilizable.

### 7. Extraccion con IA (Gemini)

- **Modo texto** (OCR): Extrae texto plano preservando estructura de parrafos.
- **Modo tablas** (Gemini Vision): Extrae contenido incluyendo tablas en formato Markdown.
- **Extraccion en lote**: Extrae todas las paginas de un caso con paralelismo configurable.
- **Deteccion de formularios**: Identifica automaticamente el tipo de formulario en las paginas.
- **Re-indexacion**: Re-procesa paginas ya extraidas para actualizar el indice vectorial.
- **Status en tiempo real**: Consulta el estado de extraccion de todo el caso.

### 8. Indexacion RAG (Busqueda semantica)

- Las paginas extraidas se procesan en chunks con overlap configurable.
- Los chunks se convierten en embeddings usando Gemini (`gemini-embedding-001`).
- Los vectores se almacenan en Pinecone con metadatos (caso, seccion, pagina).
- Permite busqueda semantica para responder preguntas QC y queries en lenguaje natural.
- Scope por documento: prioriza resultados del documento relevante antes de buscar globalmente.

### 9. Tab "Exportar"

- Descarga el **PDF consolidado** con indice de contenidos.
- Descarga el **reporte de cumplimiento** del checklist clasico.
- Descarga el **reporte QC** (global o por checklist individual).
- Exporta datos de extraccion y uso de tokens en **JSON**.
- Revisa el **log de auditoria** de todas las acciones del caso.

### 10. Administracion

- **Gestion de equipos**: Crear equipos, asignar miembros con roles especificos.
- **Gestion de usuarios**: Alta, baja, edicion y asignacion/revocacion de roles.
- **Roles y permisos**: Crear roles personalizados y asignar permisos granulares.
- **Vista de supervisor**: Listar casos asignados a equipos supervisados.

---

## Estructura del proyecto

```
document-categorizer/
├── backend/
│   ├── app/
│   │   ├── main.py                    # Entry point FastAPI + seeders + migraciones
│   │   ├── database.py                # SQLAlchemy (SQLite / PostgreSQL)
│   │   ├── models.py                  # Modelos ORM
│   │   ├── schemas.py                 # Schemas Pydantic v2
│   │   ├── db_utils.py               # Helpers: get_or_404, reorder
│   │   ├── routers/
│   │   │   ├── auth.py               # SSO login + JWT + /auth/me
│   │   │   ├── admin.py              # CRUD usuarios (solo admin)
│   │   │   ├── roles.py              # CRUD roles y permisos
│   │   │   ├── permissions.py        # Listar permisos
│   │   │   ├── teams.py              # CRUD equipos y miembros
│   │   │   ├── supervisor.py         # Vista de supervisor
│   │   │   ├── cases.py              # CRUD de casos
│   │   │   ├── documents.py          # Tipos de documento y secciones
│   │   │   ├── pages.py              # Upload, clasificacion, multi-link, reorden
│   │   │   ├── checklist.py          # Checklists clasicos, items, evidencia, targets
│   │   │   ├── qc_checklist.py       # QC Checklists jerarquicos + AI Autopilot
│   │   │   ├── templates.py          # Plantillas de taxonomia + apply-to-case
│   │   │   ├── extraction.py         # OCR, extraccion, reindexacion, RAG query
│   │   │   └── export.py             # PDF consolidado, reportes, auditoria
│   │   ├── services/
│   │   │   ├── pdf_service.py        # Split PDF, miniaturas, procesamiento imagenes
│   │   │   ├── extraction_service.py # Google Gemini Vision (OCR y tablas)
│   │   │   ├── embedding_service.py  # Embeddings con Gemini
│   │   │   ├── chunking_service.py   # Chunking de texto con overlap
│   │   │   ├── pinecone_client.py    # Cliente Pinecone (upsert, query, delete)
│   │   │   ├── indexing_service.py   # Pipeline de indexacion (OCR → chunks → embed → upsert)
│   │   │   ├── ocr_index_service.py  # Extraccion + indexacion combinada
│   │   │   ├── retrieval_service.py  # Busqueda semantica con scope por documento
│   │   │   ├── ai_verify_service.py  # Verificacion de preguntas QC con Gemini
│   │   │   ├── qc_autopilot_jobs.py  # Pipeline AI Autopilot (batch verification)
│   │   │   ├── gemini_runtime_service.py # Token tracking y cache de prompts
│   │   │   ├── case_extraction_service.py # Extraccion masiva paralela por caso
│   │   │   ├── form_detection_service.py  # Deteccion de tipo de formulario
│   │   │   ├── checklist_index_service.py # Indexacion de checklists
│   │   │   ├── json_export_service.py     # Exportacion de datos a JSON
│   │   │   ├── rag_config.py         # Configuracion centralizada RAG
│   │   │   ├── paths.py              # Rutas de archivos
│   │   │   └── export_service.py     # PDF consolidado y reportes
│   │   ├── prompts/
│   │   │   ├── extraction_prompts.py # Prompts para OCR y extraccion
│   │   │   ├── verification_prompts.py # Prompts para verificacion QC
│   │   │   ├── form_detection_prompts.py # Prompts para deteccion de formularios
│   │   │   └── toon_prompts.py       # Prompts adicionales
│   │   └── seed_data/
│   │       ├── i914_doc_taxonomy.py  # Taxonomia de documentos I-914
│   │       ├── i914_template.py      # QC Template I-914
│   │       ├── i914a_template.py     # QC Template I-914A (Supplement A)
│   │       ├── i765_template.py      # QC Template I-765
│   │       └── i192_template.py      # QC Template I-192
│   ├── alembic/                       # Migraciones de BD
│   ├── alembic.ini                    # Configuracion Alembic
│   ├── requirements.txt
│   ├── generate_dev_token.py          # Utilidad para generar JWT de desarrollo
│   ├── data/                          # Base de datos SQLite (gitignored)
│   └── storage/                       # Archivos subidos, paginas, thumbs (gitignored)
│
├── frontend/
│   ├── src/
│   │   ├── main.tsx                   # Entry point React
│   │   ├── App.tsx                    # Rutas (React Router) + proteccion por rol
│   │   ├── types/index.ts            # Tipos TypeScript
│   │   ├── api/client.ts             # Cliente Axios con interceptor JWT Bearer
│   │   ├── contexts/
│   │   │   └── AuthContext.tsx        # Estado global de autenticacion
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx          # Lista de casos
│   │   │   ├── CaseWorkspace.tsx      # Workspace principal (tabs, DnD, preview)
│   │   │   ├── TeamsPage.tsx          # Gestion de equipos
│   │   │   └── TeamMembersPage.tsx    # Gestion de miembros de equipo
│   │   ├── components/
│   │   │   ├── Layout.tsx             # Header comun + navegacion
│   │   │   ├── RequireRole.tsx        # Wrapper de proteccion de rutas por rol
│   │   │   ├── FileUpload.tsx         # Drag & drop upload de archivos
│   │   │   ├── DocumentTree.tsx       # Arbol jerarquico + plantillas
│   │   │   ├── SectionDropZone.tsx    # Drop zone para clasificar paginas
│   │   │   ├── PageThumbnail.tsx      # Miniatura de pagina con indicadores
│   │   │   ├── ChecklistPanel.tsx     # Checklists con mapeo a secciones
│   │   │   └── AuditLog.tsx           # Log de auditoria
│   │   └── lib/
│   │       └── liquid-glass/          # Efectos visuales Liquid Glass
│   │           ├── surfaceFunctions.ts
│   │           ├── refraction.ts
│   │           ├── displacementMap.ts
│   │           └── featureDetection.ts
│   ├── vite.config.ts                 # Proxy /api y /storage → backend:8001
│   ├── tailwind.config.js             # Tema brand/glass + animaciones
│   ├── postcss.config.js              # Tailwind + Autoprefixer
│   ├── tsconfig.json                  # ES2020, JSX, strict
│   └── package.json
│
├── .env                               # Variables de entorno (gitignored)
├── .env.example                       # Plantilla de variables
├── .gitignore
└── README.md
```

---

## API Reference

Todos los endpoints estan bajo el prefijo `/api`. Excepto `/api/sso-login` y `/api/health`, todos requieren autenticacion JWT via header `Authorization: Bearer <token>`.

### Autenticacion

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| POST | `/api/sso-login` | Login SSO (email + name + HMAC) → devuelve JWT |
| GET | `/api/auth/me` | Perfil del usuario autenticado con roles y permisos |

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
| GET | `/api/pages/{id}/section-links` | Listar links de seccion de una pagina |
| POST | `/api/pages/{id}/section-links` | Agregar link a seccion adicional |
| DELETE | `/api/pages/{id}/section-links/{section_id}` | Eliminar link a seccion |
| PUT | `/api/pages/{id}/section-links/primary` | Cambiar seccion primaria |
| PUT | `/api/pages/reorder` | Reordenar paginas |
| DELETE | `/api/pages/{id}` | Eliminar pagina |

### Checklists (clasico)

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/api/cases/{id}/checklists` | Listar checklists (con items, evidencias, targets) |
| POST | `/api/cases/{id}/checklists` | Crear checklist |
| POST | `/api/checklists/{id}/items` | Agregar item |
| PUT | `/api/checklist-items/{id}` | Actualizar item (status, targets) |
| PUT | `/api/checklist-items/{id}/targets` | Upsert secciones destino del item |
| POST | `/api/checklist-items/{id}/evidence` | Vincular pagina como evidencia |
| DELETE | `/api/evidence-links/{id}` | Eliminar evidencia |

### QC Checklists (jerarquico + IA)

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/api/qc-templates` | Listar plantillas QC |
| GET | `/api/cases/{id}/qc-checklists` | Listar QC checklists de un caso |
| POST | `/api/qc-checklists` | Crear QC checklist |
| GET | `/api/qc-checklists/{id}` | Obtener QC checklist completo |
| DELETE | `/api/qc-checklists/{id}` | Eliminar QC checklist |
| POST | `/api/cases/{id}/qc-checklists/apply/{tpl_id}` | Aplicar plantilla QC a caso |
| POST | `/api/qc-checklists/seed/i914` | Seedear plantilla I-914 |
| POST | `/api/qc-checklists/seed/i914a` | Seedear plantilla I-914A |
| POST | `/api/qc-checklists/seed/i765` | Seedear plantilla I-765 |
| POST | `/api/qc-checklists/seed/i192` | Seedear plantilla I-192 |
| POST | `/api/qc-checklists/seed/all` | Seedear todas las plantillas |
| POST | `/api/qc-checklists/{id}/parts` | Agregar parte |
| PUT | `/api/qc-parts/{id}` | Actualizar parte |
| DELETE | `/api/qc-parts/{id}` | Eliminar parte |
| PUT | `/api/qc-parts/reorder` | Reordenar partes |
| POST | `/api/qc-parts/{id}/questions` | Agregar pregunta |
| PUT | `/api/qc-questions/{id}` | Actualizar pregunta |
| DELETE | `/api/qc-questions/{id}` | Eliminar pregunta |
| PUT | `/api/qc-questions/reorder` | Reordenar preguntas |
| POST | `/api/qc-questions/{id}/evidence` | Vincular evidencia |
| DELETE | `/api/qc-evidence/{id}` | Eliminar evidencia |
| POST | `/api/qc-checklists/{id}/save-as-template` | Guardar como plantilla |
| POST | `/api/qc-checklists/{id}/ai-autopilot` | Lanzar AI Autopilot (async) |
| GET | `/api/qc-autopilot-jobs/{id}` | Estado del job de Autopilot |
| POST | `/api/qc-questions/{id}/ai-verify` | Verificar pregunta con IA |
| POST | `/api/qc-parts/{id}/ai-verify-all` | Verificar todas las preguntas de una parte |
| POST | `/api/qc-checklists/{id}/semantic-query` | Busqueda semantica en el caso |
| POST | `/api/qc-checklists/{id}/link-presets` | Crear link preset |
| GET | `/api/qc-link-presets` | Listar link presets |
| GET | `/api/qc-link-presets/{id}` | Obtener link preset |
| DELETE | `/api/qc-link-presets/{id}` | Eliminar link preset |
| POST | `/api/cases/{id}/qc-checklists/{cl_id}/apply-link-preset/{preset_id}` | Aplicar link preset |
| POST | `/api/cases/{id}/qc-checklists/{cl_id}/auto-link-sections` | Auto-link inteligente |

### Plantillas de taxonomia

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/api/templates` | Listar plantillas globales |
| POST | `/api/templates` | Crear plantilla |
| POST | `/api/templates/{id}/nodes` | Agregar nodo al arbol de la plantilla |
| POST | `/api/templates/{id}/checklists` | Agregar checklist con items y mapeos |
| POST | `/api/cases/{id}/apply-template` | Aplicar plantilla a un caso |

### Extraccion e indexacion (Gemini + RAG)

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/api/extraction/status` | Verificar si la API key esta configurada |
| POST | `/api/pages/{id}/extract` | Extraer texto de una pagina |
| GET | `/api/pages/{id}/extraction` | Consultar resultado de extraccion |
| POST | `/api/cases/{id}/extract-batch` | Extraccion en lote del caso |
| GET | `/api/cases/{id}/extraction-status` | Estado de extraccion de todo el caso |
| POST | `/api/pages/{id}/reindex` | Re-indexar una pagina en Pinecone |
| POST | `/api/cases/{id}/reindex` | Re-indexar todo el caso |
| GET | `/api/cases/{id}/extraction-json` | Exportar datos de extraccion en JSON |
| GET | `/api/cases/{id}/token-usage-json` | Exportar uso de tokens Gemini |
| POST | `/api/cases/{id}/rag/query` | Busqueda semantica RAG en el caso |

### Exportacion

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/api/cases/{id}/export/pdf` | Descargar PDF consolidado |
| GET | `/api/cases/{id}/export/report` | Descargar reporte de cumplimiento (checklist) |
| GET | `/api/cases/{id}/export/qc-report` | Descargar reporte QC global |
| GET | `/api/cases/{id}/export/qc-report/{cl_id}` | Descargar reporte QC por checklist |
| GET | `/api/cases/{id}/audit` | Log de auditoria |

### Administracion de usuarios (solo admin)

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/api/users` | Listar usuarios |
| GET | `/api/users/{id}` | Obtener usuario |
| PUT | `/api/users/{id}` | Actualizar usuario |
| DELETE | `/api/users/{id}` | Eliminar usuario |
| PUT | `/api/users/{id}/roles` | Reemplazar roles del usuario |
| POST | `/api/users/{id}/roles` | Agregar rol al usuario |
| DELETE | `/api/users/{id}/roles/{role_id}` | Remover rol del usuario |

### Roles y permisos

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/api/roles` | Listar roles con permisos |
| POST | `/api/roles` | Crear rol |
| PUT | `/api/roles/{id}` | Actualizar rol |
| DELETE | `/api/roles/{id}` | Eliminar rol |
| PUT | `/api/roles/{id}/permissions` | Actualizar permisos del rol |
| GET | `/api/permissions` | Listar todos los permisos |

### Equipos

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/api/teams` | Listar equipos |
| POST | `/api/teams` | Crear equipo |
| GET | `/api/teams/{id}/users` | Obtener equipo con miembros |
| PUT | `/api/teams/{id}` | Actualizar equipo |
| DELETE | `/api/teams/{id}` | Eliminar equipo |

### Supervisor

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/api/supervisor/cases` | Listar todos los casos supervisados |
| GET | `/api/supervisor/teams/{id}/cases` | Listar casos de un equipo especifico |

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

### Multi-link de paginas

Una pagina puede pertenecer a multiples secciones simultaneamente. Se designa una seccion como **primaria** y las demas como links secundarios, permitiendo referenciar la misma pagina desde diferentes contextos.

### Mapa checklist → secciones

Cada item del checklist puede apuntar a una o varias secciones destino. Esto crea un **mapa de conexiones** que indica *donde buscar* la informacion para verificar cada requisito:

```
Checklist "Verificacion A"
  ├── A1: "Verificar antecedentes"  →  [B.2.1]
  ├── A2: "Revisar introduccion"    →  [B.1]
  └── A3: "Confirmar datos"         →  [B.2.1, C.1]
```

### QC Checklists jerarquicos

A diferencia de los checklists clasicos, los QC checklists usan una estructura **Partes → Preguntas** con soporte para:

- Partes anidadas (sub-partes a cualquier profundidad)
- Preguntas con campos: descripcion, donde verificar, estado, respuesta IA, notas IA, confianza IA
- Link Presets: mapeos reutilizables entre preguntas y secciones
- Auto-link inteligente: matching automatico basado en nombres de secciones

### Plantillas reutilizables

Una plantilla empaqueta:
- Un arbol de tipos de documento y secciones predeterminadas
- Checklists con items
- Mapeos item → seccion pre-configurados

Al aplicar una plantilla a un caso, todo se instancia automaticamente preservando las conexiones.

### Pipeline RAG (Retrieval-Augmented Generation)

```
Pagina → OCR (Gemini) → Texto → Chunking → Embeddings (Gemini) → Pinecone
                                                                       │
QC Pregunta → Embedding de query ──────────────────────────────────────┘
                                                                       │
                               Chunks relevantes → Prompt → Gemini → Respuesta
```

El pipeline indexa automaticamente las paginas extraidas y permite busqueda semantica para verificacion QC automatica.

### Modos de extraccion

| Si el documento... | Se usa... | Resultado |
|--------------------|-----------|-----------|
| Solo tiene texto | Gemini OCR | Texto plano con estructura de parrafos |
| Contiene tablas | Gemini Vision (tablas) | Markdown con tablas formateadas |

El modo se configura por tipo de documento con el toggle de tablas.

### AI Autopilot

El AI Autopilot ejecuta un pipeline completo de verificacion automatica:

1. **Recopilacion de evidencia**: Para cada pregunta, busca chunks relevantes en Pinecone usando embeddings semanticos.
2. **Batching**: Agrupa preguntas en lotes para optimizar llamadas a Gemini.
3. **Evaluacion**: Envia preguntas + evidencia a Gemini para determinar si estan cumplidas.
4. **Resultados**: Registra respuesta (yes/no/partial/n_a), notas explicativas y nivel de confianza (high/medium/low).
5. **Tracking**: Registra uso de tokens y estado del job para monitoreo.
