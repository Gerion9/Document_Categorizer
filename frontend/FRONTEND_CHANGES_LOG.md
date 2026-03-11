# Frontend Changes Log

Bitacora de cambios realizados en frontend durante esta iteracion.

## 2026-03-11

### Regla de seguridad en Team members

- Se agrego restriccion para evitar que un `admin` se elimine a si mismo cuando es el unico admin disponible en la lista.
- Comportamiento aplicado:
  - El boton `Eliminar` se deshabilita en ese escenario.
  - Se muestra tooltip explicativo en el boton deshabilitado.
  - Si se intenta borrar via handler, se bloquea y muestra mensaje de error.
- La deteccion de "usuario actual" se toma de `GET /api/auth/me` y se vincula en cache local con `authUserId`.
- Se agrego confirmacion previa al borrado:
  - al presionar `Eliminar`, se muestra dialogo de confirmacion;
  - solo se elimina si el usuario confirma.

### Archivos modificados en esta parte

- `frontend/src/pages/TeamMembersPage.tsx`
- `frontend/FRONTEND_CHANGES_LOG.md`

---

### Nueva pagina: Team members (Agregar usuario)

- Se implemento la nueva vista de miembros en `frontend/src/pages/TeamMembersPage.tsx`.
- La vista incluye tabla con columnas:
  - `Name`
  - `Role`
  - `Actions` (botones `Editar` y `Eliminar`).
- Se agrego boton `Add member` que abre modal con campos:
  - `Nombre`
  - `Rol`
- El boton `Editar` abre el mismo modal precargado para actualizar `Nombre` y `Rol`.
- El item `Agregar usuario` del dropdown del navbar ahora navega a `/team-members`.

#### Preparado para backend (importante)

- **Catalogo de roles temporalmente estatico** en frontend:
  - `Admin`
  - `Supervisor`
  - `Manager`
- Se dejo preparado para migrar en futuro a endpoint de catalogo de roles.
- **Persistencia temporal en cache local (estado React)**:
  - Altas/ediciones/eliminaciones se reflejan en UI, pero no se guardan en base de datos.
- **Contrato de body propuesto para POST (documentado para backend):**

```json
{
  "rol": "id_catalogo_de_roles",
  "name": "nombre"
}
```

> Nota: hoy se usa `roleId` local en cache y se mapea a `rol` para futuro envio al backend.

### Archivos modificados en esta parte

- `frontend/src/pages/TeamMembersPage.tsx`
- `frontend/src/App.tsx`
- `frontend/src/components/Layout.tsx`
- `frontend/FRONTEND_CHANGES_LOG.md`

---

### Navbar: bloque de usuario + dropdown

- Se agrego en el navbar un bloque de usuario con:
  - icono de usuario,
  - nombre del usuario cargado desde `GET /api/auth/me`,
  - flecha para abrir/cerrar dropdown.
- Se agregaron items de dropdown:
  - `Agregar usuario` (placeholder),
  - `Cerrar sesion` (elimina `sessionStorage.auth_token` y recarga la app).
- Se agrego cabecera del dropdown con:
  - nombre completo del usuario,
  - rol actual (tomado de `roles[0]`).

### Ajustes visuales aplicados

- Se corrigio el problema de dropdown oculto por `overflow-hidden` del header.
- Se ajusto el estilo para que no se vea como un solo boton:
  - bloque visual sin borde general,
  - apertura del menu desde la flecha.
- Se quito truncado en nombre/rol dentro del dropdown (ahora hace wrap).

### Archivos modificados

- `frontend/src/components/Layout.tsx`

---

## Formato para siguientes cambios

Agregar nuevos bloques por fecha con:

1. Que se cambio
2. Por que se cambio
3. Archivos modificados

