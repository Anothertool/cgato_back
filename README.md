# CGato Backend

Backend Django con PostgreSQL y Django REST Framework.

## Ejecución local

Desde PowerShell, con Python 3.13 y PostgreSQL instalados:

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Completa `.env` con una `SECRET_KEY` propia, `ENV=dev` y `DATABASE_URL`.
Si ya existe `.env`, conserva ese archivo. La base de datos y el usuario deben
existir en PostgreSQL antes de ejecutar las migraciones. Por ejemplo:

```dotenv
SECRET_KEY=replace-with-a-generated-secret-key
ENV=dev
DATABASE_URL=postgresql://cgato:password@localhost:5432/cgato
```

Codifica los caracteres especiales del usuario o contraseña en la URL.
Para generar una clave:

```powershell
.\venv\Scripts\python.exe -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

```powershell
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py createsuperuser
.\venv\Scripts\python.exe manage.py runserver
```

Admin: `/admin/`. API navegable: `/api/`.
Los endpoints de pacientes y cirugías son públicos, tanto en dev como en prod:
no requieren autenticación, permisos, cookies ni token CSRF. El admin conserva
el inicio de sesión estándar de Django.

## Endpoints

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/api/patients/` | Lista paginada de pacientes |
| POST | `/api/patients/` | Crear paciente |
| GET | `/api/patients/{id}/` | Consultar paciente |
| PATCH | `/api/patients/{id}/` | Actualizar paciente parcialmente |
| DELETE | `/api/patients/{id}/` | Eliminar paciente sin cirugías asociadas |
| GET | `/api/surgeries/` | Lista paginada de cirugías activas |
| POST | `/api/surgeries/` | Crear cirugía con paciente existente o nuevo |
| GET | `/api/surgeries/{id}/` | Consultar cirugía |
| PATCH | `/api/surgeries/{id}/` | Actualizar cirugía parcialmente |
| DELETE | `/api/surgeries/{id}/` | Dar de baja lógicamente una cirugía |

Las listas devuelven `count`, `next`, `previous` y `results`, con 25 registros
por página. Usa `?page=2` para continuar. Las escrituras devuelven la misma
representación completa que las consultas (`201` en creación y `200` en PATCH).
DELETE devuelve `204` sin cuerpo. Los IDs son UUID.

### Pacientes

`POST /api/patients/`:

```json
{
  "first_name": "María",
  "last_name": "García",
  "phone": "600000000",
  "clinical_reference": "LEXI-001"
}
```

Solo `first_name` es obligatorio. `clinical_reference` es única cuando tiene
valor; `null`, una cadena vacía o espacios se guardan como `null`. Los pacientes
con nombres iguales se mantienen separados. `id`, `created_at` y `updated_at`
son de solo lectura.

Búsqueda por nombre, apellidos y referencia clínica:

```text
GET /api/patients/?search=María
GET /api/patients/?search=LEXI-001
```

### Cirugía con paciente existente

`POST /api/surgeries/` (sustituye el UUID por el de un paciente real):

```json
{
  "patient_id": "00000000-0000-0000-0000-000000000001",
  "hospital": "Hospital A",
  "surgery_type": "Cataratas",
  "eye": "RIGHT",
  "scheduled_at": "2026-11-10T09:30:00+01:00"
}
```

### Cirugía con paciente nuevo

`POST /api/surgeries/`:

```json
{
  "patient": {
    "first_name": "María",
    "last_name": "García"
  },
  "hospital": "Hospital A",
  "surgery_type": "Cataratas",
  "eye": "LEFT",
  "scheduled_at": "2026-11-10T10:00:00+01:00",
  "iol_model": "Pure",
  "iol_power": "19.50",
  "amount": "250.00"
}
```

Debe enviarse exactamente una de las opciones `patient_id` o `patient`.
La creación del paciente, la cirugía y su trazabilidad es atómica.
No se buscan ni fusionan pacientes por nombre.

Campos obligatorios: paciente, `hospital`, `surgery_type`, `eye`, `scheduled_at`.
Campos opcionales: `insurer`, `iol_model`, `iol_power`, `anesthesia`, `amount`,
`notes`, `status` y controles administrativos.

`eye`: `RIGHT`, `LEFT`, `BOTH`.
`status`: `PENDING` (predeterminado), `PREPARING`, `READY`, `COMPLETED`, `CANCELLED`.
`iol_power` admite valores negativos y tiene dos decimales; `amount` tiene dos
decimales y no puede ser negativo. Ambos admiten `null`.

Se conserva `USE_TZ=True` y la zona horaria del proyecto, UTC. Envía fechas
con offset para evitar ambigüedad; las fechas sin offset se interpretan en UTC.
Las respuestas se normalizan a UTC.

`SurgeryOutputSerializer` devuelve todos los campos de la cirugía, el paciente
completo anidado y `lens_checks`. El historial de lentes contiene `id`, `field`,
`value`, `checked_by` (ID de usuario, o `null` en operaciones anónimas) y `checked_at`. Los IDs, fechas automáticas,
historial y campos de baja son de solo lectura.

### Actualizaciones y lentes

Cambiar el paciente con `PATCH /api/surgeries/{id}/`:

```json
{
  "patient_id": "00000000-0000-0000-0000-000000000002"
}
```

PATCH no acepta `patient` anidado ni crea pacientes.

Los booleanos `lens_ordered`, `lens_received`, `lens_verified` y
`documentation_ready` tienen valor inicial `false`. Ejemplo de actualización:

```json
{
  "lens_received": true,
  "lens_verified": true,
  "documentation_ready": true
}
```

No se puede verificar una lente sin haberla recibido, ni desmarcar su recepción
mientras siga verificada. Cada cambio real de `lens_ordered`, `lens_received` o
`lens_verified` registra fecha y usuario cuando existe, también al desmarcar el
campo y desde el admin. Las operaciones públicas de la API guardan el usuario
como `null`. Repetir el mismo valor no duplica el historial. La actualización y el
historial se guardan en una única transacción.

### Filtros de cirugías

Los filtros se pueden combinar y aplican coincidencia exacta, excepto los rangos
de fecha inclusivos:

```text
GET /api/surgeries/?status=PENDING&hospital=Hospital%20A
GET /api/surgeries/?eye=LEFT&insurer=Insurer%20A
GET /api/surgeries/?patient_id=00000000-0000-0000-0000-000000000001
GET /api/surgeries/?scheduled_at__gte=2026-11-01T00:00:00Z&scheduled_at__lte=2026-11-30T23:59:59Z
```

El orden predeterminado es `scheduled_at` ascendente, con UUID como desempate.

### Cancelaciones y bajas

Para cancelar conservando la cirugía en el listado:

```json
{
  "status": "CANCELLED"
}
```

DELETE de una cirugía conserva la fila, registra `deleted_at` y `deleted_by`
(este último es `null` en operaciones anónimas)
y la oculta de los endpoints. Este comportamiento se aplica en dev y prod.
El admin permite consultar las bajas, pero no modificarlas ni borrar físicamente
cirugías o su historial. No hay endpoint de recuperación de bajas.

Los pacientes con cualquier cirugía asociada, incluso una cirugía dada de baja,
no pueden eliminarse: la API devuelve `400` y la relación usa `PROTECT`.

## Verificaciones

```powershell
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\venv\Scripts\python.exe manage.py test patients surgeries --noinput
```

Los tests usan PostgreSQL mediante `DATABASE_URL`. Django crea y elimina su
base de datos de pruebas (`test_<nombre>`); el usuario necesita permiso `CREATEDB`.
Utiliza una base de desarrollo para ejecutar los tests.

## Despliegue

Se mantienen el Dockerfile, entrypoint y configuración de Railway existentes.
En producción configura `SECRET_KEY`, `ENV=prod` y `DATABASE_URL`.
El entrypoint ejecuta migraciones y collectstatic antes de arrancar Gunicorn.

## Archivos de las apps

- `patients/`: modelo, serializers de entrada/salida, ViewSet, admin, migración y tests.
- `surgeries/`: modelos de cirugía e historial de lentes, serializers, filtros, ViewSet, admin, migración y tests.
- `cgato_back/settings.py` y `cgato_back/urls.py`: registro de apps, acceso público a la API, paginación y rutas.
- `requirements.txt`: incorpora únicamente `django-filter` a las dependencias existentes.

Referencia: [django-filter con DRF](https://django-filter.readthedocs.io/en/stable/guide/rest_framework.html).
