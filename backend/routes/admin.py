from flask import Blueprint, request, jsonify
from config import get_connection, JWT_SECRET_KEY
import bcrypt
import jwt
import functools
import datetime

admin_bp = Blueprint('admin', __name__)


def requiere_token(roles_permitidos=None):
    if roles_permitidos is None:
        roles_permitidos = []
    def decorador(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            auth_header = request.headers.get("Authorization", "")
            token = auth_header.replace("Bearer ", "").strip()
            if not token:
                return jsonify({"success": False, "message": "Token requerido."}), 401
            try:
                payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])
            except jwt.ExpiredSignatureError:
                return jsonify({"success": False, "message": "Sesión expirada."}), 401
            except jwt.InvalidTokenError as e:
                print(f"[JWT INVALID admin] {e}")
                return jsonify({"success": False, "message": "Token inválido."}), 401
            if roles_permitidos and payload.get("rol") not in roles_permitidos:
                return jsonify({"success": False, "message": "Acceso denegado."}), 403
            request.usuario_actual = payload
            return f(*args, **kwargs)
        return wrapper
    return decorador


def _registrar_auditoria(cursor, id_usuario, accion):
    try:
        cursor.execute(
            "INSERT INTO auditoria (id_usuario, accion, fecha) VALUES (%s, %s, NOW())",
            (id_usuario, accion)
        )
    except Exception as e:
        print(f"[AUDITORIA WARN] {e}")


def _get_id_rol(cursor, nombre_rol):
    cursor.execute("SELECT id_rol FROM roles WHERE nombre = %s LIMIT 1", (nombre_rol,))
    row = cursor.fetchone()
    if not row:
        raise ValueError(f"Rol '{nombre_rol}' no existe.")
    return row["id_rol"]


# ══════════════════════════════════════════════════════════════
# STATS — GET /api/admin/stats
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/admin/stats', methods=['GET'])
@requiere_token(["admin", "superadmin"])
def stats():
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""SELECT COUNT(*) AS t FROM usuarios u JOIN roles r ON u.id_rol=r.id_rol
                          WHERE r.nombre='medico' AND u.estado='activo'""")
        total_medicos = cursor.fetchone()["t"]

        cursor.execute("SELECT COUNT(*) AS t FROM pacientes")
        total_pacientes = cursor.fetchone()["t"]

        # Generar cupos del día automáticamente si no existen
        _generar_cupos_hoy(cursor)
        conn.commit()

        cursor.execute("SELECT COUNT(*) AS t FROM fichas WHERE DATE(fecha_registro)=CURDATE()")
        fichas_hoy = cursor.fetchone()["t"]

        cursor.execute("""SELECT COALESCE(SUM(cantidad_maxima - cantidad_reservada),0) AS t
                          FROM cupos WHERE fecha=CURDATE()""")
        cupos_disponibles = cursor.fetchone()["t"]

        cursor.execute("SELECT COUNT(*) AS t FROM usuarios WHERE bloqueado=TRUE")
        bloqueados = cursor.fetchone()["t"]

        cursor.execute("""SELECT COUNT(*) AS t FROM solicitudes_especialidad
                          WHERE estado='pendiente'""")
        solicitudes_pendientes = cursor.fetchone()["t"]

        return jsonify({
            "success":               True,
            "total_medicos":         total_medicos,
            "total_pacientes":       total_pacientes,
            "fichas_hoy":            fichas_hoy,
            "cupos_disponibles":     cupos_disponibles,
            "bloqueados":            bloqueados,
            "solicitudes_pendientes":solicitudes_pendientes
        }), 200
    except Exception as e:
        print(f"[ADMIN STATS ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener estadísticas."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# ACTIVIDAD MÉDICOS HOY — GET /api/admin/actividad_medicos
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/admin/actividad_medicos', methods=['GET'])
@requiere_token(["admin", "superadmin"])
def actividad_medicos():
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT u.id_usuario, u.email, u.ultimo_acceso,
                   CONCAT(m.nombre,' ',m.apellido_paterno)         AS nombre,
                   GROUP_CONCAT(DISTINCT e.nombre SEPARATOR ', ')  AS especialidad,
                   COUNT(DISTINCT f.id_ficha)                      AS fichas_hoy,
                   COALESCE(MAX(c.cantidad_maxima),0)              AS cupo_max,
                   (DATE(u.ultimo_acceso)=CURDATE())               AS sesion_hoy
            FROM usuarios u
            JOIN roles r ON u.id_rol=r.id_rol
            LEFT JOIN medicos m              ON m.id_medico      =u.id_medico
            LEFT JOIN medico_especialidad me ON me.id_medico     =m.id_medico
            LEFT JOIN especialidades e       ON e.id_especialidad=me.id_especialidad
            LEFT JOIN fichas f               ON f.id_medico      =m.id_medico
                                            AND DATE(f.fecha_registro)=CURDATE()
            LEFT JOIN cupos c               ON c.id_especialidad =me.id_especialidad
                                            AND c.fecha          =CURDATE()
            WHERE r.nombre='medico' AND u.estado='activo'
            GROUP BY u.id_usuario, u.email, u.ultimo_acceso, m.nombre, m.apellido_paterno
            ORDER BY fichas_hoy DESC
        """)
        medicos = cursor.fetchall()
        for m in medicos:
            m["sesion_hoy"] = bool(m["sesion_hoy"])
        return jsonify({"success": True, "medicos": medicos}), 200
    except Exception as e:
        print(f"[ACTIVIDAD MEDICOS ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener actividad."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# ESPECIALIDADES CON CUPOS — GET /api/admin/especialidades
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/admin/especialidades', methods=['GET'])
@requiere_token(["admin", "superadmin"])
def especialidades():
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT e.id_especialidad, e.nombre, e.descripcion, e.estado,
                   e.cupo_referencial,
                   COUNT(DISTINCT me.id_medico)             AS total_medicos,
                   COALESCE(c.cantidad_maxima,   0)         AS cantidad_maxima,
                   COALESCE(c.cantidad_reservada,0)         AS cantidad_reservada
            FROM especialidades e
            LEFT JOIN medico_especialidad me ON me.id_especialidad=e.id_especialidad
            LEFT JOIN cupos c                ON c.id_especialidad =e.id_especialidad
                                             AND c.fecha=CURDATE()
            GROUP BY e.id_especialidad, e.nombre, e.descripcion, e.estado,
                     e.cupo_referencial, c.cantidad_maxima, c.cantidad_reservada
            ORDER BY e.estado DESC, e.nombre
        """)
        return jsonify({"success": True, "especialidades": cursor.fetchall()}), 200
    except Exception as e:
        print(f"[ESPECIALIDADES ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener especialidades."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# ALERTAS — GET /api/admin/alertas
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/admin/alertas', methods=['GET'])
@requiere_token(["admin", "superadmin"])
def alertas():
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        lista  = []

        # Alertas de la tabla alertas
        cursor.execute("""
            SELECT a.nivel, a.mensaje, e.nombre AS especialidad
            FROM alertas a
            LEFT JOIN especialidades e ON e.id_especialidad=a.id_especialidad
            WHERE DATE(a.fecha)=CURDATE()
            ORDER BY FIELD(a.nivel,'rojo','amarillo','verde'), a.fecha DESC
            LIMIT 10
        """)
        lista.extend(cursor.fetchall())

        # Especialidades llenas
        cursor.execute("""
            SELECT e.nombre, c.cantidad_maxima, c.cantidad_reservada
            FROM cupos c JOIN especialidades e ON e.id_especialidad=c.id_especialidad
            WHERE c.fecha=CURDATE() AND c.cantidad_reservada>=c.cantidad_maxima
        """)
        for ll in cursor.fetchall():
            lista.insert(0, {"nivel":"rojo",
                "mensaje": f"{ll['nombre']} lleno ({ll['cantidad_reservada']}/{ll['cantidad_maxima']} cupos)."})

        # Especialidades al 80%
        cursor.execute("""
            SELECT e.nombre, c.cantidad_maxima, c.cantidad_reservada
            FROM cupos c JOIN especialidades e ON e.id_especialidad=c.id_especialidad
            WHERE c.fecha=CURDATE() AND c.cantidad_maxima>0
              AND (c.cantidad_reservada/c.cantidad_maxima)>=0.8
              AND c.cantidad_reservada<c.cantidad_maxima
        """)
        for ca in cursor.fetchall():
            pct = round((ca["cantidad_reservada"]/ca["cantidad_maxima"])*100)
            lista.append({"nivel":"amarillo",
                "mensaje": f"{ca['nombre']} al {pct}% ({ca['cantidad_reservada']}/{ca['cantidad_maxima']} cupos)."})

        # Solicitudes de especialidad pendientes
        cursor.execute("SELECT COUNT(*) AS t FROM solicitudes_especialidad WHERE estado='pendiente'")
        pend = cursor.fetchone()["t"]
        if pend > 0:
            lista.insert(0, {"nivel":"amarillo",
                "mensaje": f"Hay {pend} solicitud(es) de especialidad pendiente(s) de aprobación."})

        return jsonify({"success": True, "alertas": lista}), 200
    except Exception as e:
        print(f"[ALERTAS ERROR] {e}")
        return jsonify({"success": False, "alertas": []}), 200
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# SOLICITUDES DE ESPECIALIDAD — GET /api/admin/solicitudes_especialidad
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/admin/solicitudes_especialidad', methods=['GET'])
@requiere_token(["admin", "superadmin"])
def listar_solicitudes_especialidad():
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT se.id,
                   CONCAT(m.nombre,' ',m.apellido_paterno) AS medico,
                   u.email,
                   e.nombre   AS especialidad,
                   se.estado,
                   se.fecha
            FROM solicitudes_especialidad se
            JOIN medicos       m ON m.id_medico      =se.id_medico
            JOIN especialidades e ON e.id_especialidad=se.id_especialidad
            JOIN usuarios      u ON u.id_medico      =m.id_medico
            ORDER BY FIELD(se.estado,'pendiente','aprobada','rechazada'), se.fecha DESC
        """)
        lista = cursor.fetchall()
        for item in lista:
            if item.get("fecha"):
                item["fecha"] = item["fecha"].isoformat()
        return jsonify({"success": True, "solicitudes": lista}), 200
    except Exception as e:
        print(f"[SOLICITUDES ESP ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener solicitudes."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# RESPONDER SOLICITUD ESPECIALIDAD — PUT /api/admin/solicitud_especialidad/<id>
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/admin/solicitud_especialidad/<int:id>', methods=['PUT'])
@requiere_token(["admin"])
def responder_solicitud_especialidad(id):
    data   = request.get_json(silent=True) or {}
    estado = (data.get("estado") or "").strip()
    if estado not in ("aprobada", "rechazada"):
        return jsonify({"success": False, "message": "Estado inválido."}), 400

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        # Obtener la solicitud
        cursor.execute("""
            SELECT se.id, se.id_medico, se.id_especialidad, se.estado
            FROM solicitudes_especialidad se WHERE se.id=%s LIMIT 1
        """, (id,))
        sol = cursor.fetchone()
        if not sol:
            return jsonify({"success": False, "message": "Solicitud no encontrada."}), 404
        if sol["estado"] != "pendiente":
            return jsonify({"success": False, "message": "Esta solicitud ya fue procesada."}), 400

        # Actualizar estado
        cursor.execute(
            "UPDATE solicitudes_especialidad SET estado=%s WHERE id=%s", (estado, id)
        )

        # Si aprobada → insertar en medico_especialidad
        if estado == "aprobada":
            cursor.execute("""
                SELECT id_medico FROM medico_especialidad
                WHERE id_medico=%s AND id_especialidad=%s LIMIT 1
            """, (sol["id_medico"], sol["id_especialidad"]))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO medico_especialidad (id_medico, id_especialidad)
                    VALUES (%s, %s)
                """, (sol["id_medico"], sol["id_especialidad"]))

        id_usuario = request.usuario_actual.get("sub")
        _registrar_auditoria(cursor, id_usuario,
                             f"SOLICITUD_ESP_{estado.upper()} id={id}")
        conn.commit()

        msg = "Especialidad aprobada y asignada al médico." if estado == "aprobada" else "Solicitud rechazada."
        return jsonify({"success": True, "message": msg}), 200

    except Exception as e:
        print(f"[RESPONDER SOL ESP ERROR] {e}")
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error al procesar solicitud."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# PACIENTES — GET /api/admin/pacientes
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/admin/pacientes', methods=['GET'])
@requiere_token(["admin", "superadmin"])
def listar_pacientes():
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT p.id_paciente, p.ci, p.nombre, p.apellido_paterno, p.apellido_materno,
                   p.telefono, p.fecha_nacimiento, p.fecha_registro,
                   COUNT(f.id_ficha) AS total_fichas
            FROM pacientes p
            LEFT JOIN fichas f ON f.id_paciente=p.id_paciente
            GROUP BY p.id_paciente
            ORDER BY p.fecha_registro DESC
        """)
        lista = cursor.fetchall()
        for item in lista:
            if item.get("fecha_nacimiento"):
                item["fecha_nacimiento"] = item["fecha_nacimiento"].isoformat()
            if item.get("fecha_registro"):
                item["fecha_registro"] = item["fecha_registro"].isoformat()
        return jsonify({"success": True, "pacientes": lista}), 200
    except Exception as e:
        print(f"[PACIENTES ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener pacientes."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# HISTORIAL PACIENTE — GET /api/admin/paciente/<id>/historial
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/admin/paciente/<int:id>/historial', methods=['GET'])
@requiere_token(["admin", "superadmin"])
def historial_paciente(id):
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT f.id_ficha, f.fecha, f.numero_turno,
                   e.nombre  AS especialidad,
                   CONCAT(m.nombre,' ',m.apellido_paterno) AS medico,
                   ef.nombre AS estado
            FROM fichas f
            JOIN especialidades  e  ON e.id_especialidad=f.id_especialidad
            JOIN estados_ficha   ef ON ef.id_estado     =f.id_estado
            LEFT JOIN medicos    m  ON m.id_medico      =f.id_medico
            WHERE f.id_paciente=%s
            ORDER BY f.fecha DESC, f.numero_turno ASC
        """, (id,))
        historial = cursor.fetchall()
        for h in historial:
            if h.get("fecha"): h["fecha"] = str(h["fecha"])
        return jsonify({"success": True, "historial": historial}), 200
    except Exception as e:
        print(f"[HISTORIAL ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener historial."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# FICHAS DEL DÍA — GET /api/admin/fichas
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/admin/fichas', methods=['GET'])
@requiere_token(["admin", "superadmin"])
def fichas_dia():
    fecha         = request.args.get("fecha") or datetime.date.today().isoformat()
    id_esp        = request.args.get("especialidad") or None
    estado_filtro = request.args.get("estado")       or None

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT id_especialidad, nombre FROM especialidades ORDER BY nombre")
        especialidades = cursor.fetchall()

        query  = """
            SELECT f.id_ficha, f.codigo_ficha, f.numero_turno, f.fecha,
                   CONCAT(p.nombre,' ',p.apellido_paterno) AS paciente,
                   e.nombre  AS especialidad,
                   CONCAT(m.nombre,' ',m.apellido_paterno) AS medico,
                   ef.nombre AS estado
            FROM fichas f
            JOIN pacientes      p  ON p.id_paciente    =f.id_paciente
            JOIN especialidades e  ON e.id_especialidad =f.id_especialidad
            JOIN estados_ficha  ef ON ef.id_estado      =f.id_estado
            LEFT JOIN medicos   m  ON m.id_medico       =f.id_medico
            WHERE f.fecha=%s
        """
        params = [fecha]
        if id_esp:
            query += " AND f.id_especialidad=%s"; params.append(id_esp)
        if estado_filtro:
            query += " AND ef.nombre=%s"; params.append(estado_filtro)
        query += " ORDER BY f.numero_turno ASC"

        cursor.execute(query, params)
        fichas = cursor.fetchall()
        for f in fichas:
            if f.get("fecha"): f["fecha"] = str(f["fecha"])

        return jsonify({"success": True, "fichas": fichas,
                        "especialidades": especialidades}), 200
    except Exception as e:
        print(f"[FICHAS ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener fichas."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# CANCELAR FICHA — PUT /api/admin/ficha/<id>/cancelar
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/admin/ficha/<int:id>/cancelar', methods=['PUT'])
@requiere_token(["admin", "superadmin"])
def cancelar_ficha(id):
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT id_estado FROM estados_ficha WHERE nombre='cancelada' LIMIT 1")
        est = cursor.fetchone()
        if not est:
            return jsonify({"success": False, "message": "Estado 'cancelada' no configurado."}), 400

        cursor.execute("""
            SELECT f.id_ficha, ef.nombre AS estado
            FROM fichas f JOIN estados_ficha ef ON ef.id_estado=f.id_estado
            WHERE f.id_ficha=%s LIMIT 1
        """, (id,))
        ficha = cursor.fetchone()
        if not ficha:
            return jsonify({"success": False, "message": "Ficha no encontrada."}), 404
        if ficha["estado"] != "pendiente":
            return jsonify({"success": False,
                            "message": f"No se puede cancelar una ficha en estado '{ficha['estado']}'."}), 400

        cursor.execute("UPDATE fichas SET id_estado=%s WHERE id_ficha=%s", (est["id_estado"], id))
        cursor.execute("""
            UPDATE cupos c JOIN fichas f ON f.id_especialidad=c.id_especialidad AND c.fecha=f.fecha
            SET c.cantidad_reservada=GREATEST(c.cantidad_reservada-1,0)
            WHERE f.id_ficha=%s
        """, (id,))

        _registrar_auditoria(cursor, request.usuario_actual.get("sub"), f"CANCELAR_FICHA id={id}")
        conn.commit()
        return jsonify({"success": True, "message": "Ficha cancelada correctamente."}), 200
    except Exception as e:
        print(f"[CANCELAR FICHA ERROR] {e}")
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error al cancelar ficha."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# CREAR MÉDICO — POST /api/crear_medico
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/crear_medico', methods=['POST'])
@requiere_token(["admin", "superadmin"])
def crear_medico():
    data     = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "message": "Solicitud inválida."}), 400

    email    = (data.get("email")    or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not email or not password:
        return jsonify({"success": False, "message": "Email y contraseña son obligatorios."}), 400
    if not email.endswith("@gmail.com"):
        return jsonify({"success": False, "message": "El correo debe ser @gmail.com"}), 400
    if len(password) < 8:
        return jsonify({"success": False, "message": "Mínimo 8 caracteres."}), 400

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT id_usuario FROM usuarios WHERE LOWER(email)=%s LIMIT 1", (email,))
        if cursor.fetchone():
            return jsonify({"success": False, "message": "Ese correo ya está registrado."}), 409

        id_rol        = _get_id_rol(cursor, "medico")
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

        cursor.execute("""
            INSERT INTO usuarios (email, password, id_rol, estado, perfil_completo,
                                  intentos_fallidos, bloqueado, fecha_registro)
            VALUES (%s,%s,%s,'activo',FALSE,0,FALSE,NOW())
        """, (email, password_hash, id_rol))

        _registrar_auditoria(cursor, request.usuario_actual.get("sub"), f"CREAR_MEDICO email={email}")
        conn.commit()
        return jsonify({"success": True, "message": "Médico creado correctamente."}), 201

    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        print(f"[CREAR MEDICO ERROR] {e}")
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error interno al crear el médico."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()



# ══════════════════════════════════════════════════════════════
# CREAR ESPECIALIDAD — POST /api/admin/especialidad
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/admin/especialidad', methods=['POST'])
@requiere_token(["admin", "superadmin"])
def crear_especialidad():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "message": "Solicitud inválida."}), 400

    nombre      = (data.get("nombre")      or "").strip()
    descripcion = (data.get("descripcion") or "").strip()

    if not nombre or not descripcion:
        return jsonify({"success": False, "message": "Nombre y descripción son obligatorios."}), 400

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT id_especialidad FROM especialidades WHERE nombre = %s LIMIT 1", (nombre,)
        )
        if cursor.fetchone():
            return jsonify({"success": False, "message": "Ya existe una especialidad con ese nombre."}), 409

        cursor.execute(
            "INSERT INTO especialidades (nombre, descripcion, estado) VALUES (%s, %s, 'activa')",
            (nombre, descripcion)
        )
        _registrar_auditoria(cursor, request.usuario_actual.get("sub"),
                             f"CREAR_ESPECIALIDAD nombre={nombre}")
        conn.commit()
        return jsonify({"success": True, "message": f"Especialidad '{nombre}' creada correctamente."}), 201

    except Exception as e:
        print(f"[CREAR ESPECIALIDAD ERROR] {e}")
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error al crear especialidad."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# EDITAR ESPECIALIDAD — PUT /api/admin/especialidad/<id>
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/admin/especialidad/<int:id>', methods=['PUT'])
@requiere_token(["admin", "superadmin"])
def editar_especialidad(id):
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "message": "Solicitud inválida."}), 400

    nombre      = (data.get("nombre")      or "").strip()
    descripcion = (data.get("descripcion") or "").strip()

    if not nombre or not descripcion:
        return jsonify({"success": False, "message": "Nombre y descripción son obligatorios."}), 400

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT id_especialidad FROM especialidades WHERE id_especialidad = %s LIMIT 1", (id,)
        )
        if not cursor.fetchone():
            return jsonify({"success": False, "message": "Especialidad no encontrada."}), 404

        cursor.execute(
            "SELECT id_especialidad FROM especialidades WHERE nombre = %s AND id_especialidad != %s LIMIT 1",
            (nombre, id)
        )
        if cursor.fetchone():
            return jsonify({"success": False, "message": "Ya existe otra especialidad con ese nombre."}), 409

        cursor.execute(
            "UPDATE especialidades SET nombre = %s, descripcion = %s WHERE id_especialidad = %s",
            (nombre, descripcion, id)
        )
        _registrar_auditoria(cursor, request.usuario_actual.get("sub"),
                             f"EDITAR_ESPECIALIDAD id={id} nombre={nombre}")
        conn.commit()
        return jsonify({"success": True, "message": "Especialidad actualizada correctamente."}), 200

    except Exception as e:
        print(f"[EDITAR ESPECIALIDAD ERROR] {e}")
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error al editar especialidad."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# CAMBIAR ESTADO ESPECIALIDAD — PUT /api/admin/especialidad/<id>/estado
# activa ↔ inactiva  (nunca se elimina si tiene médicos o fichas)
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/admin/especialidad/<int:id>/estado', methods=['PUT'])
@requiere_token(["admin", "superadmin"])
def estado_especialidad(id):
    data  = request.get_json(silent=True) or {}
    nuevo = (data.get("estado") or "").strip()
    if nuevo not in ("activa", "inactiva"):
        return jsonify({"success": False, "message": "Estado inválido."}), 400

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT nombre, estado FROM especialidades WHERE id_especialidad = %s LIMIT 1", (id,)
        )
        esp = cursor.fetchone()
        if not esp:
            return jsonify({"success": False, "message": "Especialidad no encontrada."}), 404

        cursor.execute(
            "UPDATE especialidades SET estado = %s WHERE id_especialidad = %s", (nuevo, id)
        )
        _registrar_auditoria(cursor, request.usuario_actual.get("sub"),
                             f"ESTADO_ESPECIALIDAD id={id} estado={nuevo}")
        conn.commit()
        accion = "activada" if nuevo == "activa" else "desactivada"
        return jsonify({"success": True, "message": f"Especialidad '{esp['nombre']}' {accion}."}), 200

    except Exception as e:
        print(f"[ESTADO ESPECIALIDAD ERROR] {e}")
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error al cambiar estado."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# ELIMINAR ESPECIALIDAD — DELETE /api/admin/especialidad/<id>
# Solo si no tiene médicos asignados ni fichas registradas
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/admin/especialidad/<int:id>', methods=['DELETE'])
@requiere_token(["admin", "superadmin"])
def eliminar_especialidad(id):
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT nombre FROM especialidades WHERE id_especialidad = %s LIMIT 1", (id,)
        )
        esp = cursor.fetchone()
        if not esp:
            return jsonify({"success": False, "message": "Especialidad no encontrada."}), 404

        # Verificar médicos asignados
        cursor.execute(
            "SELECT COUNT(*) AS t FROM medico_especialidad WHERE id_especialidad = %s", (id,)
        )
        if cursor.fetchone()["t"] > 0:
            return jsonify({"success": False,
                            "message": f"No se puede eliminar '{esp['nombre']}': tiene médicos asignados. Desactívala mejor."}), 400

        # Verificar fichas registradas
        cursor.execute(
            "SELECT COUNT(*) AS t FROM fichas WHERE id_especialidad = %s", (id,)
        )
        if cursor.fetchone()["t"] > 0:
            return jsonify({"success": False,
                            "message": f"No se puede eliminar '{esp['nombre']}': tiene fichas registradas. Desactívala mejor."}), 400

        # Verificar solicitudes de especialidad
        cursor.execute(
            "SELECT COUNT(*) AS t FROM solicitudes_especialidad WHERE id_especialidad = %s", (id,)
        )
        if cursor.fetchone()["t"] > 0:
            return jsonify({"success": False,
                            "message": f"No se puede eliminar '{esp['nombre']}': tiene solicitudes pendientes."}), 400

        cursor.execute("DELETE FROM especialidades WHERE id_especialidad = %s", (id,))
        _registrar_auditoria(cursor, request.usuario_actual.get("sub"),
                             f"ELIMINAR_ESPECIALIDAD nombre={esp['nombre']}")
        conn.commit()
        return jsonify({"success": True, "message": f"Especialidad '{esp['nombre']}' eliminada."}), 200

    except Exception as e:
        print(f"[ELIMINAR ESPECIALIDAD ERROR] {e}")
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error al eliminar especialidad."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# HELPER — Generar cupos del día si no existen
# Se llama automáticamente en stats y fichas
# ══════════════════════════════════════════════════════════════
def _generar_cupos_hoy(cursor):
    """
    Para cada especialidad activa con cupo_referencial > 0,
    inserta un registro en cupos para hoy si no existe.
    """
    try:
        cursor.execute("""
            INSERT INTO cupos (id_especialidad, fecha, cantidad_maxima, cantidad_reservada)
            SELECT e.id_especialidad, CURDATE(), e.cupo_referencial, 0
            FROM especialidades e
            WHERE e.estado = 'activa'
              AND e.cupo_referencial > 0
              AND NOT EXISTS (
                SELECT 1 FROM cupos c
                WHERE c.id_especialidad = e.id_especialidad
                  AND c.fecha = CURDATE()
              )
        """)
    except Exception as e:
        print(f"[GENERAR CUPOS WARN] {e}")


# ══════════════════════════════════════════════════════════════
# GENERAR CUPOS MANUAL — POST /api/admin/generar_cupos
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/admin/generar_cupos', methods=['POST'])
@requiere_token(["admin", "superadmin"])
def generar_cupos_manual():
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        # Contar cuántas especialidades ya tienen cupos hoy
        cursor.execute("""
            SELECT COUNT(*) AS t FROM cupos WHERE fecha = CURDATE()
        """)
        ya_existian = cursor.fetchone()["t"]

        _generar_cupos_hoy(cursor)
        conn.commit()

        # Contar cuántos se generaron
        cursor.execute("""
            SELECT COUNT(*) AS t FROM cupos WHERE fecha = CURDATE()
        """)
        total = cursor.fetchone()["t"]
        nuevos = total - ya_existian

        _registrar_auditoria(cursor, request.usuario_actual.get("sub"),
                             f"GENERAR_CUPOS_MANUAL nuevos={nuevos}")
        conn.commit()

        if nuevos == 0:
            return jsonify({
                "success": True,
                "message": f"Los cupos de hoy ya estaban generados ({total} especialidades)."
            }), 200

        return jsonify({
            "success": True,
            "message": f"Se generaron {nuevos} cupo(s) nuevos para hoy. Total: {total} especialidades."
        }), 200

    except Exception as e:
        print(f"[GENERAR CUPOS ERROR] {e}")
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error al generar cupos."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# CONFIGURAR CUPO FIJO — PUT /api/admin/especialidad/<id>/cupo
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/admin/especialidad/<int:id>/cupo', methods=['PUT'])
@requiere_token(["admin", "superadmin"])
def configurar_cupo(id):
    data            = request.get_json(silent=True) or {}
    cupo_referencial = data.get("cupo_diario")  # el JS manda "cupo_diario", lo mapeamos

    if cupo_referencial is None or not isinstance(cupo_referencial, int) or cupo_referencial < 1:
        return jsonify({"success": False,
                        "message": "El cupo diario debe ser un número entero mayor a 0."}), 400
    if cupo_referencial > 200:
        return jsonify({"success": False,
                        "message": "El cupo máximo permitido es 200 pacientes por día."}), 400

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT nombre FROM especialidades WHERE id_especialidad = %s LIMIT 1", (id,)
        )
        esp = cursor.fetchone()
        if not esp:
            return jsonify({"success": False, "message": "Especialidad no encontrada."}), 404

        # Actualizar cupo fijo
        cursor.execute(
            "UPDATE especialidades SET cupo_referencial = %s WHERE id_especialidad = %s",
            (cupo_referencial, id)
        )

        # También actualizar el cupo de HOY si ya existe
        cursor.execute("""
            UPDATE cupos SET cantidad_maxima = %s
            WHERE id_especialidad = %s AND fecha = CURDATE()
        """, (cupo_referencial, id))

        _registrar_auditoria(cursor, request.usuario_actual.get("sub"),
                             f"CONFIGURAR_CUPO esp={esp['nombre']} cupo={cupo_referencial}")
        conn.commit()

        return jsonify({
            "success": True,
            "message": f"Cupo de '{esp['nombre']}' actualizado a {cupo_referencial} pacientes/día."
        }), 200

    except Exception as e:
        print(f"[CONFIGURAR CUPO ERROR] {e}")
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error al configurar cupo."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# AGENDA — LISTAR SOLICITUDES — GET /api/admin/agendas
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/admin/agendas', methods=['GET'])
@requiere_token(["admin", "superadmin"])
def listar_agendas():
    estado_filtro = request.args.get("estado") or None
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        query = """
            SELECT
                a.id_agenda,
                a.fecha,
                a.turno,
                a.hora_inicio,
                a.hora_fin,
                a.cupos_solicitados,
                a.cupos_aprobados,
                a.cupos_ocupados,
                a.estado,
                a.motivo_rechazo,
                a.fecha_solicitud,
                CONCAT(m.nombre,' ',m.apellido_paterno) AS medico,
                m.id_medico,
                e.nombre   AS especialidad,
                e.id_especialidad,
                -- Nivel de alerta
                CASE
                    WHEN a.estado = 'revision' AND a.cupos_ocupados > 0 THEN 'rojo'
                    WHEN a.estado = 'revision' AND a.cupos_ocupados = 0 THEN 'amarillo'
                    WHEN a.estado = 'pendiente' THEN 'verde'
                    ELSE 'verde'
                END AS nivel_alerta,
                ROUND(
                    TIME_TO_SEC(TIMEDIFF(a.hora_fin, a.hora_inicio)) / 60
                    / a.cupos_solicitados
                ) AS tiempo_promedio
            FROM agenda_medico a
            JOIN medicos      m ON m.id_medico       = a.id_medico
            JOIN especialidades e ON e.id_especialidad = a.id_especialidad
        """
        params = []
        if estado_filtro:
            query += " WHERE a.estado = %s"
            params.append(estado_filtro)
        else:
            query += " WHERE a.estado IN ('pendiente','revision')"

        query += " ORDER BY FIELD(nivel_alerta,'rojo','amarillo','verde'), a.fecha_solicitud DESC"

        cursor.execute(query, params)
        agendas = cursor.fetchall()
        for ag in agendas:
            if ag.get("fecha"):          ag["fecha"]          = str(ag["fecha"])
            if ag.get("hora_inicio"):    ag["hora_inicio"]    = str(ag["hora_inicio"])
            if ag.get("hora_fin"):       ag["hora_fin"]        = str(ag["hora_fin"])
            if ag.get("fecha_solicitud"):ag["fecha_solicitud"] = ag["fecha_solicitud"].isoformat()

        return jsonify({"success": True, "agendas": agendas}), 200

    except Exception as e:
        print(f"[ADMIN AGENDAS ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener agendas."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# AGENDA — APROBAR/RECHAZAR — PUT /api/admin/agenda/<id>
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/admin/agenda/<int:id>', methods=['PUT'])
@requiere_token(["admin", "superadmin"])
def responder_agenda(id):
    data    = request.get_json(silent=True) or {}
    accion  = (data.get("accion")  or "").strip()  # aprobar | rechazar
    motivo  = (data.get("motivo")  or "").strip()

    if accion not in ("aprobar", "rechazar"):
        return jsonify({"success": False, "message": "Acción inválida."}), 400
    if accion == "rechazar" and not motivo:
        return jsonify({"success": False,
                        "message": "Debes indicar el motivo del rechazo."}), 400

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        # Obtener agenda
        cursor.execute("""
            SELECT a.*, 
                   CONCAT(m.nombre,' ',m.apellido_paterno) AS medico_nombre,
                   e.nombre AS especialidad_nombre,
                   u.id_usuario AS id_usuario_medico
            FROM agenda_medico a
            JOIN medicos m ON m.id_medico = a.id_medico
            JOIN especialidades e ON e.id_especialidad = a.id_especialidad
            JOIN usuarios u ON u.id_medico = m.id_medico
            WHERE a.id_agenda = %s LIMIT 1
        """, (id,))
        agenda = cursor.fetchone()
        if not agenda:
            return jsonify({"success": False, "message": "Agenda no encontrada."}), 404

        if agenda["estado"] not in ("pendiente", "revision"):
            return jsonify({"success": False,
                            "message": "Esta agenda ya fue procesada."}), 400

        id_usuario_admin  = request.usuario_actual.get("sub")
        id_usuario_medico = agenda["id_usuario_medico"]

        if accion == "aprobar":
            # Actualizar agenda
            cursor.execute("""
                UPDATE agenda_medico
                SET estado          = 'aprobada',
                    cupos_aprobados = cupos_solicitados,
                    motivo_rechazo  = NULL
                WHERE id_agenda = %s
            """, (id,))

            # Insertar o actualizar en tabla cupos
            cursor.execute("""
                INSERT INTO cupos (id_especialidad, fecha, cantidad_maxima, cantidad_reservada)
                VALUES (%s, %s, %s, 0)
                ON DUPLICATE KEY UPDATE
                    cantidad_maxima = cantidad_maxima + VALUES(cantidad_maxima)
            """, (agenda["id_especialidad"], agenda["fecha"], agenda["cupos_solicitados"]))

            # ── Activar fichas pre-asignadas que coincidan con médico/especialidad/fecha ──
            cursor.execute("""
                SELECT f.id_ficha, f.id_paciente, f.numero_turno
                FROM fichas f
                JOIN estados_ficha ef ON ef.id_estado = f.id_estado
                WHERE ef.nombre = 'pre-asignada'
                  AND f.id_medico = %s AND f.id_especialidad = %s AND f.fecha = %s
                ORDER BY f.numero_turno ASC
            """, (agenda["id_medico"], agenda["id_especialidad"], agenda["fecha"]))
            fichas_preasignadas = cursor.fetchall()

            if fichas_preasignadas:
                cursor.execute(
                    "SELECT id_estado FROM estados_ficha WHERE nombre = 'pendiente' LIMIT 1"
                )
                estado_pendiente = cursor.fetchone()

                # Verificar cupos disponibles vs pre-asignadas
                cursor.execute("""
                    SELECT cantidad_maxima, cantidad_reservada FROM cupos
                    WHERE id_especialidad = %s AND fecha = %s LIMIT 1
                """, (agenda["id_especialidad"], agenda["fecha"]))
                cupo_row = cursor.fetchone()
                disponibles = (cupo_row["cantidad_maxima"] - cupo_row["cantidad_reservada"]) if cupo_row else 0

                activadas = 0
                for fpa in fichas_preasignadas:
                    if activadas >= disponibles:
                        break
                    cursor.execute(
                        "UPDATE fichas SET id_estado = %s WHERE id_ficha = %s",
                        (estado_pendiente["id_estado"], fpa["id_ficha"])
                    )
                    cursor.execute("""
                        UPDATE cupos SET cantidad_reservada = cantidad_reservada + 1
                        WHERE id_especialidad = %s AND fecha = %s
                    """, (agenda["id_especialidad"], agenda["fecha"]))
                    activadas += 1

                    # Notificar al paciente que su ficha fue confirmada
                    cursor.execute(
                        "SELECT id_usuario FROM usuarios WHERE id_paciente = %s LIMIT 1",
                        (fpa["id_paciente"],)
                    )
                    u_pac = cursor.fetchone()
                    if u_pac:
                        cursor.execute("""
                            INSERT INTO notificaciones
                                (id_usuario, mensaje, tipo, fecha, estado)
                            VALUES (%s, %s, 'confirmacion', NOW(), 'no_leido')
                        """, (u_pac["id_usuario"],
                              f"✅ Tu cita de control del {agenda['fecha']} con "
                              f"{agenda['medico_nombre']} fue confirmada. Turno #{fpa['numero_turno']}."))

            # Guardar historial
            cursor.execute("""
                INSERT INTO agenda_historial
                    (id_agenda, cupos_anterior, cupos_nuevo,
                     estado_anterior, estado_nuevo, motivo, fecha, id_usuario)
                VALUES (%s, %s, %s, %s, 'aprobada', 'Aprobada por admin', NOW(), %s)
            """, (id, agenda["cupos_solicitados"], agenda["cupos_solicitados"],
                  agenda["estado"], id_usuario_admin))

            # Notificar al médico
            cursor.execute("""
                INSERT INTO notificaciones
                    (id_usuario, mensaje, tipo, fecha, estado)
                VALUES (%s, %s, 'sistema', NOW(), 'no_leido')
            """, (id_usuario_medico,
                  f"✅ Tu agenda del {agenda['fecha']} ({agenda['turno']}) "
                  f"fue APROBADA. Ya está visible para los pacientes. "
                  f"Cupos: {agenda['cupos_solicitados']}"))

            # Si hay pacientes en revisión notificarles que vuelve a estar activa
            if agenda["cupos_ocupados"] > 0:
                cursor.execute("""
                    SELECT f.id_ficha, p.id_paciente,
                           CONCAT(p.nombre,' ',p.apellido_paterno) AS paciente
                    FROM fichas f
                    JOIN pacientes p ON p.id_paciente = f.id_paciente
                    JOIN estados_ficha ef ON ef.id_estado = f.id_estado
                    WHERE f.id_agenda = %s AND ef.nombre != 'cancelada'
                """, (id,))
                fichas = cursor.fetchall()

                # Notificar a pacientes con cuenta
                for ficha in fichas:
                    cursor.execute("""
                        SELECT u.id_usuario FROM usuarios u
                        JOIN pacientes p ON p.id_paciente = %s
                        WHERE u.id_paciente = p.id_paciente LIMIT 1
                    """, (ficha["id_paciente"],))
                    u_pac = cursor.fetchone()
                    if u_pac:
                        cursor.execute("""
                            INSERT INTO notificaciones
                                (id_usuario, mensaje, tipo, fecha, estado)
                            VALUES (%s, %s, 'sistema', NOW(), 'no_leido')
                        """, (u_pac["id_usuario"],
                              f"✅ Tu cita del {agenda['fecha']} ({agenda['turno']}) "
                              f"con {agenda['medico_nombre']} fue confirmada."))

            msg = f"Agenda aprobada y publicada para pacientes."

        else:  # rechazar
            cursor.execute("""
                UPDATE agenda_medico
                SET estado         = 'rechazada',
                    motivo_rechazo = %s
                WHERE id_agenda = %s
            """, (motivo, id))

            # Guardar historial
            cursor.execute("""
                INSERT INTO agenda_historial
                    (id_agenda, cupos_anterior, cupos_nuevo,
                     estado_anterior, estado_nuevo, motivo, fecha, id_usuario)
                VALUES (%s, %s, %s, %s, 'rechazada', %s, NOW(), %s)
            """, (id, agenda["cupos_solicitados"], agenda["cupos_solicitados"],
                  agenda["estado"], motivo, id_usuario_admin))

            # Notificar al médico con motivo
            cursor.execute("""
                INSERT INTO notificaciones
                    (id_usuario, mensaje, tipo, fecha, estado)
                VALUES (%s, %s, 'rechazo', NOW(), 'no_leido')
            """, (id_usuario_medico,
                  f"❌ Tu agenda del {agenda['fecha']} ({agenda['turno']}) "
                  f"fue RECHAZADA. Motivo: {motivo}. "
                  f"Por favor crea una nueva solicitud."))

            # Si había pacientes con ficha notificarles
            if agenda["cupos_ocupados"] > 0:
                cursor.execute("""
                    SELECT f.id_ficha, p.id_paciente
                    FROM fichas f
                    JOIN pacientes p ON p.id_paciente = f.id_paciente
                    JOIN estados_ficha ef ON ef.id_estado = f.id_estado
                    WHERE f.id_agenda = %s AND ef.nombre != 'cancelada'
                """, (id,))
                fichas = cursor.fetchall()
                for ficha in fichas:
                    cursor.execute("""
                        SELECT u.id_usuario FROM usuarios u
                        WHERE u.id_paciente = %s LIMIT 1
                    """, (ficha["id_paciente"],))
                    u_pac = cursor.fetchone()
                    if u_pac:
                        cursor.execute("""
                            INSERT INTO notificaciones
                                (id_usuario, mensaje, tipo, fecha, estado)
                            VALUES (%s, %s, 'sistema', NOW(), 'no_leido')
                        """, (u_pac["id_usuario"],
                              f"⚠️ Tu cita del {agenda['fecha']} ({agenda['turno']}) "
                              f"fue cancelada por ajuste de agenda médica. "
                              f"Por favor saca una nueva ficha."))

            msg = "Agenda rechazada. Se notificó al médico."

        _registrar_auditoria(cursor, id_usuario_admin,
                             f"AGENDA_{accion.upper()} id={id}")
        conn.commit()
        return jsonify({"success": True, "message": msg}), 200

    except Exception as e:
        print(f"[RESPONDER AGENDA ERROR] {e}")
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error al procesar la agenda."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# MÉDICOS — VISTA TARJETAS — GET /api/admin/medicos/tarjetas
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/admin/medicos/tarjetas', methods=['GET'])
@requiere_token(["admin", "superadmin"])
def medicos_tarjetas():
    id_especialidad = request.args.get("especialidad") or None
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        query = """
            SELECT
                u.id_usuario,
                u.email,
                u.estado,
                u.perfil_completo,
                u.ultimo_acceso,
                m.id_medico,
                m.nombre,
                m.apellido_paterno,
                m.telefono,
                m.matricula_profesional,
                GROUP_CONCAT(DISTINCT e.nombre ORDER BY e.nombre SEPARATOR ', ') AS especialidades,
                -- Fichas hoy
                COUNT(DISTINCT f.id_ficha) AS fichas_hoy,
                -- Completadas hoy
                SUM(CASE WHEN ef.nombre = 'completada' THEN 1 ELSE 0 END) AS completadas_hoy,
                -- En atención
                SUM(CASE WHEN ef.nombre = 'en_atencion' THEN 1 ELSE 0 END) AS en_atencion,
                -- Pendientes
                SUM(CASE WHEN ef.nombre = 'pendiente' THEN 1 ELSE 0 END) AS pendientes,
                -- Agenda activa hoy
                MAX(CASE WHEN ag.estado = 'aprobada' AND ag.fecha = CURDATE()
                    THEN ag.turno ELSE NULL END) AS turno_hoy,
                MAX(CASE WHEN ag.estado = 'aprobada' AND ag.fecha = CURDATE()
                    THEN ag.estado ELSE NULL END) AS agenda_hoy,
                -- Sesión hoy
                (DATE(u.ultimo_acceso) = CURDATE()) AS sesion_hoy
            FROM usuarios u
            JOIN roles r ON r.id_rol = u.id_rol
            LEFT JOIN medicos m ON m.id_medico = u.id_medico
            LEFT JOIN medico_especialidad me ON me.id_medico = m.id_medico
            LEFT JOIN especialidades e ON e.id_especialidad = me.id_especialidad
            LEFT JOIN fichas f ON f.id_medico = m.id_medico
                               AND DATE(f.fecha_registro) = CURDATE()
            LEFT JOIN estados_ficha ef ON ef.id_estado = f.id_estado
            LEFT JOIN agenda_medico ag ON ag.id_medico = m.id_medico
                                       AND ag.fecha = CURDATE()
            WHERE r.nombre = 'medico'
        """
        params = []
        if id_especialidad:
            query += " AND e.id_especialidad = %s"
            params.append(id_especialidad)

        query += """
            GROUP BY u.id_usuario, u.email, u.estado, u.perfil_completo,
                     u.ultimo_acceso, m.id_medico, m.nombre,
                     m.apellido_paterno, m.telefono, m.matricula_profesional
            ORDER BY m.nombre ASC
        """
        cursor.execute(query, params)
        medicos = cursor.fetchall()
        for m in medicos:
            m["sesion_hoy"]      = bool(m["sesion_hoy"])
            m["perfil_completo"] = bool(m["perfil_completo"])
            if m.get("ultimo_acceso"):
                m["ultimo_acceso"] = m["ultimo_acceso"].isoformat()

        return jsonify({"success": True, "medicos": medicos}), 200

    except Exception as e:
        print(f"[MEDICOS TARJETAS ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener médicos."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# MÉDICO DETALLE — GET /api/admin/medico/<id>/detalle
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/admin/medico/<int:id>/detalle', methods=['GET'])
@requiere_token(["admin", "superadmin"])
def detalle_medico(id):
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        # Info básica del médico
        cursor.execute("""
            SELECT m.id_medico, m.nombre, m.apellido_paterno, m.apellido_materno,
                   m.ci, m.telefono, m.email, m.matricula_profesional,
                   m.direccion, m.estado, m.fecha_registro,
                   u.email AS email_sistema, u.id_usuario,
                   u.ultimo_acceso,
                   GROUP_CONCAT(DISTINCT e.nombre ORDER BY e.nombre SEPARATOR ', ') AS especialidades
            FROM medicos m
            JOIN usuarios u ON u.id_medico = m.id_medico
            LEFT JOIN medico_especialidad me ON me.id_medico = m.id_medico
            LEFT JOIN especialidades e ON e.id_especialidad = me.id_especialidad
            WHERE m.id_medico = %s
            GROUP BY m.id_medico
            LIMIT 1
        """, (id,))
        medico = cursor.fetchone()
        if not medico:
            return jsonify({"success": False, "message": "Médico no encontrado."}), 404

        if medico.get("fecha_registro"): medico["fecha_registro"] = medico["fecha_registro"].isoformat()
        if medico.get("ultimo_acceso"):  medico["ultimo_acceso"]  = medico["ultimo_acceso"].isoformat()

        # Resumen fichas hoy
        cursor.execute("""
            SELECT
                COUNT(*)                                              AS total_hoy,
                SUM(CASE WHEN ef.nombre='completada'  THEN 1 ELSE 0 END) AS completadas,
                SUM(CASE WHEN ef.nombre='en_atencion' THEN 1 ELSE 0 END) AS en_atencion,
                SUM(CASE WHEN ef.nombre='pendiente'   THEN 1 ELSE 0 END) AS pendientes
            FROM fichas f
            JOIN estados_ficha ef ON ef.id_estado = f.id_estado
            WHERE f.id_medico = %s AND DATE(f.fecha_registro) = CURDATE()
        """, (id,))
        stats_hoy = cursor.fetchone()

        # Agendas activas y próximas
        cursor.execute("""
            SELECT a.id_agenda, a.fecha, a.turno,
                   a.hora_inicio, a.hora_fin,
                   a.cupos_aprobados, a.cupos_ocupados, a.estado,
                   e.nombre AS especialidad
            FROM agenda_medico a
            JOIN especialidades e ON e.id_especialidad = a.id_especialidad
            WHERE a.id_medico = %s
              AND a.fecha >= CURDATE()
              AND a.estado IN ('aprobada','pendiente')
            ORDER BY a.fecha ASC, a.turno ASC
            LIMIT 5
        """, (id,))
        agendas = cursor.fetchall()
        for ag in agendas:
            if ag.get("fecha"):       ag["fecha"]       = str(ag["fecha"])
            if ag.get("hora_inicio"): ag["hora_inicio"] = str(ag["hora_inicio"])
            if ag.get("hora_fin"):    ag["hora_fin"]    = str(ag["hora_fin"])

        # Auditoría reciente del médico
        cursor.execute("""
            SELECT a.accion, a.fecha
            FROM auditoria a
            WHERE a.id_usuario = %s
            ORDER BY a.fecha DESC
            LIMIT 10
        """, (medico["id_usuario"],))
        auditoria = cursor.fetchall()
        for a in auditoria:
            if a.get("fecha"): a["fecha"] = a["fecha"].isoformat()

        # Historial fichas últimos 7 días
        cursor.execute("""
            SELECT DATE(f.fecha_registro) AS fecha,
                   COUNT(*)              AS total,
                   SUM(CASE WHEN ef.nombre='completada' THEN 1 ELSE 0 END) AS completadas
            FROM fichas f
            JOIN estados_ficha ef ON ef.id_estado = f.id_estado
            WHERE f.id_medico = %s
              AND f.fecha_registro >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
            GROUP BY DATE(f.fecha_registro)
            ORDER BY fecha DESC
        """, (id,))
        historial_semana = cursor.fetchall()
        for h in historial_semana:
            if h.get("fecha"): h["fecha"] = str(h["fecha"])

        return jsonify({
            "success":          True,
            "medico":           medico,
            "stats_hoy":        stats_hoy,
            "agendas":          agendas,
            "auditoria":        auditoria,
            "historial_semana": historial_semana
        }), 200

    except Exception as e:
        print(f"[DETALLE MEDICO ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener detalle."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# MÉDICOS EN TARJETA — GET /api/admin/medicos_detalle
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/admin/medicos_detalle', methods=['GET'])
@requiere_token(["admin", "superadmin"])
def medicos_detalle():
    id_especialidad = request.args.get("especialidad") or None
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        query = """
            SELECT
                u.id_usuario,
                u.email,
                u.estado,
                u.perfil_completo,
                u.ultimo_acceso,
                m.id_medico,
                m.nombre,
                m.apellido_paterno,
                m.apellido_materno,
                m.telefono,
                m.matricula_profesional,
                GROUP_CONCAT(DISTINCT e.nombre ORDER BY e.nombre SEPARATOR ', ') AS especialidades,
                -- Fichas hoy
                COUNT(DISTINCT f.id_ficha) AS fichas_hoy,
                -- Completadas hoy
                SUM(CASE WHEN ef.nombre = 'completada' THEN 1 ELSE 0 END) AS completadas_hoy,
                -- En atencion
                SUM(CASE WHEN ef.nombre = 'en_atencion' THEN 1 ELSE 0 END) AS en_atencion,
                -- Pendientes
                SUM(CASE WHEN ef.nombre = 'pendiente' THEN 1 ELSE 0 END) AS pendientes_hoy,
                -- Agenda hoy
                (SELECT ag.estado FROM agenda_medico ag
                 WHERE ag.id_medico = m.id_medico
                   AND ag.fecha = CURDATE()
                 ORDER BY FIELD(ag.estado,'aprobada','pendiente','revision','rechazada')
                 LIMIT 1) AS estado_agenda_hoy,
                -- Turno hoy
                (SELECT ag.turno FROM agenda_medico ag
                 WHERE ag.id_medico = m.id_medico
                   AND ag.fecha = CURDATE()
                   AND ag.estado = 'aprobada'
                 LIMIT 1) AS turno_hoy,
                -- Sesion hoy
                (DATE(u.ultimo_acceso) = CURDATE()) AS sesion_hoy
            FROM usuarios u
            JOIN roles r ON r.id_rol = u.id_rol
            LEFT JOIN medicos m ON m.id_medico = u.id_medico
            LEFT JOIN medico_especialidad me ON me.id_medico = m.id_medico
            LEFT JOIN especialidades e ON e.id_especialidad = me.id_especialidad
            LEFT JOIN fichas f ON f.id_medico = m.id_medico
                AND DATE(f.fecha_registro) = CURDATE()
            LEFT JOIN estados_ficha ef ON ef.id_estado = f.id_estado
            WHERE r.nombre = 'medico'
        """
        params = []
        if id_especialidad:
            query += """
                AND m.id_medico IN (
                    SELECT id_medico FROM medico_especialidad
                    WHERE id_especialidad = %s
                )
            """
            params.append(id_especialidad)

        query += " GROUP BY u.id_usuario, m.id_medico ORDER BY m.nombre"
        cursor.execute(query, params)
        medicos = cursor.fetchall()

        for m in medicos:
            m["sesion_hoy"]      = bool(m["sesion_hoy"])
            m["perfil_completo"] = bool(m["perfil_completo"])
            if m.get("ultimo_acceso"):
                m["ultimo_acceso"] = m["ultimo_acceso"].isoformat()

        return jsonify({"success": True, "medicos": medicos}), 200

    except Exception as e:
        print(f"[MEDICOS DETALLE ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener médicos."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# DETALLE MÉDICO — GET /api/admin/medico/<id>/detalle