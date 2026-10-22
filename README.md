# Hospital de Clínicas

Aplicación web para la gestión de fichas médicas y consultas. El proyecto contiene una API REST en Flask, páginas estáticas para pacientes y un panel web de SuperAdmin. El desarrollo está en curso: esta documentación describe lo que está presente actualmente en el repositorio.

## Funcionalidades disponibles

- Inicio de sesión mediante correo electrónico o CI, con autenticación JWT.
- Registro de pacientes y reserva de fichas sin cuenta.
- Consulta de especialidades, fechas, cupos y médicos disponibles.
- Operaciones de paciente: perfil, fichas, confirmación, cancelación, cambio de fecha e historial.
- Operaciones de médico: horarios, agendas, fichas, consultas, pacientes y notificaciones.
- Administración de usuarios, médicos, especialidades, cupos, solicitudes y auditoría.
- Recuperación de contraseña mediante código de verificación.
- Tareas automáticas para liberar fichas sin confirmar, vencer agendas y notificar fichas preasignadas.

## Estructura

```text
.
├── backend/
│   ├── app.py
│   ├── config.py
│   ├── requirements.txt
│   ├── scheduler.py
│   └── routes/
│       ├── auth.py
│       ├── admin.py
│       ├── superadmin.py
│       ├── medico_routes.py
│       ├── paciente_routes.py
│       ├── fichas_routes.py
│       └── recuperar_routes.py
├── Database/
│   └── hospital.sql
└── Frontend/
    ├── index.html
    ├── css/
    ├── images/
    ├── js/
    └── pages/
```

El frontend incluye la página de inicio, inicio de sesión, selección y reserva de fichas, recuperación de contraseña y el panel de SuperAdmin. La API también incluye operaciones para los perfiles de administrador, médico y paciente.

## Tecnologías

- **Backend:** Python, Flask, Flask-CORS.
- **Base de datos:** MySQL, mediante `mysql-connector-python`.
- **Autenticación:** JWT y bcrypt.
- **Tareas programadas:** APScheduler.
- **Frontend:** HTML, CSS y JavaScript sin proceso de compilación.

## Requisitos

- Python 3.
- Servidor MySQL disponible localmente o en la dirección configurada.
- Una base de datos con el esquema requerido por las rutas del backend.

## Configuración y ejecución local

### 1. Preparar el backend

Desde la raíz del repositorio, en PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Antes de iniciar, revisa la configuración de conexión a MySQL y autenticación en `backend/config.py`. El backend espera una base de datos llamada `hospital_clinica10`; el servidor MySQL y el esquema correspondiente deben estar preparados.

Inicia la API:

```powershell
python app.py
```

La API queda disponible en `http://127.0.0.1:5000`. Sus endpoints se encuentran bajo el prefijo `/api`; por ejemplo, el inicio de sesión usa `POST /api/login`.

### 2. Servir el frontend

En otra terminal, desde la raíz del repositorio:

```powershell
python -m http.server 5500
```

Abre `http://127.0.0.1:5500/Frontend/index.html`. El JavaScript del frontend se comunica con la API en `http://127.0.0.1:5000/api`.

## Base de datos

El backend consulta tablas como usuarios, roles, fichas, agendas y auditoría. Actualmente, `Database/hospital.sql` contiene código Python para obtener una conexión MySQL, no un script SQL de creación de base de datos o tablas. Por ello, el repositorio todavía no proporciona un esquema importable ni datos iniciales; la base debe existir y tener las tablas esperadas por las rutas.

## Pruebas y comprobaciones

En `backend/` hay comprobaciones de conexión a la base de datos y pruebas de entrega del frontend. `test_mail.py` realiza un envío de correo real, por lo que no debe ejecutarse como una prueba automática genérica. La prueba de entrega del frontend espera que Flask sirva la página y sus recursos; actualmente, `app.py` no configura esas rutas estáticas y su ruta raíz responde con un mensaje de API.

## Estado y consideraciones

- La API está implementada para varios perfiles; las pantallas frontend presentes no cubren todas esas operaciones.
- El frontend y la API se ejecutan por separado en desarrollo.
- Las credenciales y claves de servicios deben gestionarse mediante variables de entorno o un almacén seguro antes de desplegar. No publiques secretos incluidos en archivos de configuración o pruebas; revísalos y rótalos si ya fueron compartidos.
- El servidor se inicia en modo de depuración, apropiado solo para desarrollo local.
