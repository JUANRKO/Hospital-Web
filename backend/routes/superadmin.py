from flask import Blueprint, request, jsonify
from config import get_connection, JWT_SECRET_KEY
import bcrypt
import jwt
import functools

superadmin_bp = Blueprint('superadmin', __name__)
SECRET_KEY = JWT_SECRET_KEY


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
                payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            except jwt.ExpiredSignatureError:
                return jsonify({"success": False, "message": "Sesión expirada."}), 401
            except jwt.InvalidTokenError as e:
                print(f"[JWT INVALID] {e}")
                return jsonify({"success": False, "message": "Token inválido."}), 401
            if roles_permitidos and payload.get("rol") not in roles_permitidos:
                return jsonify({"success": False, "message": "Acceso denegado."}), 403
            request.usuario_actual = payload
            return f(*args, **kwargs)
        return wrapper
    return decorador


def _get_id_rol(cursor, nombre_rol):
    cursor.execute("SELECT id_rol FROM roles WHERE nombre = %s LIMIT 1", (nombre_rol,))
    row = cursor.fetchone()
    if not row:
        raise ValueError(f"Rol '{nombre_rol}' no existe.")
    return row["id_rol"]


def _registrar_auditoria(cursor, id_usuario, accion):
    try:
        cursor.execute(
            "INSERT INTO auditoria (id_usuario, accion, fecha) VALUES (%s, %s, NOW())",
            (id_usuario, accion)
        )
    except Exception as e:
        print(f"[AUDITORIA WARN] {e}")


# ── STATS ──────────────────────────────────────────────────────
@superadmin_bp.route('/stats', methods=['GET'])
@requiere_token(["superadmin"])
def stats():
    conn = cursor = None
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) AS t FROM usuarios WHERE estado='activo'")
        total_usuarios = cursor.fetchone()["t"]
        cursor.execute("""SELECT COUNT(*) AS t FROM usuarios u JOIN roles r ON u.id_rol=r.id_rol
                          WHERE r.nombre='medico' AND u.estado='activo'""")
        total_medicos = cursor.fetchone()["t"]
        cursor.execute("""SELECT COUNT(*) AS t FROM usuarios u JOIN roles r ON u.id_rol=r.id_rol
                          WHERE r.nombre='paciente' AND u.estado='activo'""")
        total_pacientes = cursor.fetchone()["t"]
        cursor.execute("SELECT COUNT(*) AS t FROM fichas WHERE DATE(fecha_registro)=CURDATE()")
        fichas_hoy = cursor.fetchone()["t"]
        return jsonify({"success":True,"total_usuarios":total_usuarios,
                        "total_medicos":total_medicos,"total_pacientes":total_pacientes,
                        "fichas_hoy":fichas_hoy}), 200
    except Exception as e:
        print(f"[STATS ERROR] {e}")
        return jsonify({"success":False,"message":"Error al obtener estadísticas."}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


# ── CREAR SUPERADMIN / ADMIN ───────────────────────────────────
@superadmin_bp.route('/crear_superadmin', methods=['POST'])
@requiere_token(["superadmin"])
def crear_superadmin():
    return _crear_usuario_con_rol("superadmin")

@superadmin_bp.route('/crear_admin', methods=['POST'])
@requiere_token(["superadmin"])
def crear_admin():
    return _crear_usuario_con_rol("admin")

def _crear_usuario_con_rol(nombre_rol):
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success":False,"message":"Solicitud inválida."}), 400
    email    = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()
    if not email or not password:
        return jsonify({"success":False,"message":"Email y contraseña son obligatorios."}), 400
    if not email.endswith("@gmail.com"):
        return jsonify({"success":False,"message":"El correo debe ser @gmail.com"}), 400
    if len(password) < 8:
        return jsonify({"success":False,"message":"Mínimo 8 caracteres."}), 400
    conn = cursor = None
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id_usuario FROM usuarios WHERE LOWER(email)=%s LIMIT 1",(email,))
        if cursor.fetchone():
            return jsonify({"success":False,"message":"Ese correo ya está registrado."}), 409
        id_rol = _get_id_rol(cursor, nombre_rol)
        pw_hash = bcrypt.hashpw(password.encode("utf-8"),bcrypt.gensalt()).decode("utf-8")
        cursor.execute("""INSERT INTO usuarios (email,password,id_rol,estado,perfil_completo,
                          intentos_fallidos,bloqueado,fecha_registro)
                          VALUES (%s,%s,%s,'activo',FALSE,0,FALSE,NOW())""",
                       (email, pw_hash, id_rol))
        nuevo_id = cursor.lastrowid
        _registrar_auditoria(cursor, nuevo_id, f"CREAR_{nombre_rol.upper()}")
        conn.commit()
        label = "SuperAdmin" if nombre_rol == "superadmin" else "Admin"
        return jsonify({"success":True,"message":f"{label} creado correctamente."}), 201
    except ValueError as e:
        return jsonify({"success":False,"message":str(e)}), 400
    except Exception as e:
        print(f"[CREAR {nombre_rol} ERROR] {e}")
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success":False,"message":"Error interno al crear el usuario."}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


# ── COMPLETAR PERFIL (superadmin/admin/medico) ─────────────────
@superadmin_bp.route('/completar_perfil/<int:id>', methods=['POST'])
@requiere_token(["superadmin","admin","medico"])
def completar_perfil(id):
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success":False,"message":"Solicitud inválida."}), 400

    requeridos = ["ci","nombre","apellido_paterno","apellido_materno",
                  "telefono","fecha_nacimiento","direccion",
                  "matricula_profesional","email_contacto","nueva_password"]
    for campo in requeridos:
        if not data.get(campo):
            return jsonify({"success":False,"message":f"El campo '{campo}' es obligatorio."}), 400

    nueva_pass = data["nueva_password"]
    if len(nueva_pass) < 8:
        return jsonify({"success":False,"message":"La contraseña debe tener al menos 8 caracteres."}), 400

    # especialidades_ids: lista de ids enviados por el médico (opcional para superadmin/admin)
    # Acepta "especialidades" o "especialidades_ids" (compatibilidad con el formulario del médico)
    especialidades_ids = data.get("especialidades") or data.get("especialidades_ids") or []

    conn = cursor = None
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT id_usuario, id_medico FROM usuarios WHERE id_usuario=%s LIMIT 1",(id,))
        usuario = cursor.fetchone()
        if not usuario:
            return jsonify({"success":False,"message":"Usuario no encontrado."}), 404

        # CI duplicado
        cursor.execute("SELECT id_medico FROM medicos WHERE ci=%s LIMIT 1",(data["ci"],))
        if cursor.fetchone():
            return jsonify({"success":False,"message":"Ya existe un médico con ese CI."}), 409

        # Matrícula duplicada
        cursor.execute("SELECT id_medico FROM medicos WHERE matricula_profesional=%s LIMIT 1",
                       (data["matricula_profesional"],))
        if cursor.fetchone():
            return jsonify({"success":False,"message":"Esa matrícula ya está registrada."}), 409

        # 1️⃣ Insertar en medicos
        cursor.execute("""INSERT INTO medicos
                          (ci,nombre,apellido_paterno,apellido_materno,
                           telefono,email,matricula_profesional,direccion,estado,fecha_registro)
                          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'activo',NOW())""",
                       (data["ci"],data["nombre"],data["apellido_paterno"],data["apellido_materno"],
                        data["telefono"],data["email_contacto"],
                        data["matricula_profesional"],data["direccion"]))
        id_medico = cursor.lastrowid

        # 2️⃣ Hash nueva password
        pw_hash = bcrypt.hashpw(nueva_pass.encode("utf-8"),bcrypt.gensalt()).decode("utf-8")

        # 3️⃣ Actualizar usuarios
        cursor.execute("""UPDATE usuarios SET password=%s, perfil_completo=TRUE,
                          id_medico=%s, ultimo_acceso=NOW() WHERE id_usuario=%s""",
                       (pw_hash, id_medico, id))

        # 4️⃣ Guardar solicitudes de especialidad si se enviaron
        if especialidades_ids:
            for id_esp in especialidades_ids:
                try: id_esp = int(id_esp)
                except: continue
                # Verificar que no exista ya
                cursor.execute("""SELECT id FROM solicitudes_especialidad
                                  WHERE id_medico=%s AND id_especialidad=%s LIMIT 1""",
                               (id_medico, id_esp))
                if not cursor.fetchone():
                    cursor.execute("""INSERT INTO solicitudes_especialidad
                                      (id_medico, id_especialidad, estado, fecha)
                                      VALUES (%s,%s,'pendiente',NOW())""",
                                   (id_medico, id_esp))

        _registrar_auditoria(cursor, id, "PERFIL_COMPLETADO")
        conn.commit()

        return jsonify({
            "success": True,
            "message": "Perfil completado correctamente." +
                       (f" Se enviaron {len(especialidades_ids)} solicitud(es) de especialidad." if especialidades_ids else "")
        }), 200

    except Exception as e:
        print(f"[COMPLETAR_PERFIL ERROR] {e}")
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success":False,"message":"Error al guardar el perfil."}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


# ── LISTAR SUPERADMINS / ADMINS ────────────────────────────────
@superadmin_bp.route('/superadmins', methods=['GET'])
@requiere_token(["superadmin"])
def listar_superadmins():
    return _listar_por_rol("superadmin","superadmins")

@superadmin_bp.route('/admins', methods=['GET'])
@requiere_token(["superadmin"])
def listar_admins():
    return _listar_por_rol("admin","admins")

def _listar_por_rol(nombre_rol, key):
    conn = cursor = None
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("""SELECT u.id_usuario,u.email,u.estado,u.perfil_completo,u.fecha_registro
                          FROM usuarios u JOIN roles r ON u.id_rol=r.id_rol
                          WHERE r.nombre=%s ORDER BY u.fecha_registro DESC""", (nombre_rol,))
        lista = cursor.fetchall()
        for item in lista:
            if item.get("fecha_registro"):
                item["fecha_registro"] = item["fecha_registro"].isoformat()
            item["perfil_completo"] = bool(item["perfil_completo"])
        return jsonify({"success":True, key:lista}), 200
    except Exception as e:
        print(f"[LISTAR {nombre_rol} ERROR] {e}")
        return jsonify({"success":False,"message":"Error al obtener la lista."}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


# ── CAMBIAR ESTADO ─────────────────────────────────────────────
def _cambiar_estado(id_usuario, nombre_rol):
    data  = request.get_json(silent=True) or {}
    nuevo = (data.get("estado") or "").strip()
    if nuevo not in ("activo","inactivo"):
        return jsonify({"success":False,"message":"Estado inválido."}), 400
    conn = cursor = None
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("""SELECT u.id_usuario FROM usuarios u JOIN roles r ON u.id_rol=r.id_rol
                          WHERE u.id_usuario=%s AND r.nombre=%s LIMIT 1""",(id_usuario,nombre_rol))
        if not cursor.fetchone():
            return jsonify({"success":False,"message":"Usuario no encontrado."}), 404
        cursor.execute("UPDATE usuarios SET estado=%s WHERE id_usuario=%s",(nuevo,id_usuario))
        _registrar_auditoria(cursor, id_usuario, f"ESTADO_{nuevo.upper()}")
        conn.commit()
        return jsonify({"success":True,"message":f"Estado actualizado a {nuevo}."}), 200
    except Exception as e:
        return jsonify({"success":False,"message":"Error al cambiar estado."}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

def _eliminar_usuario(id_usuario, nombre_rol):
    conn = cursor = None
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("""SELECT u.id_usuario FROM usuarios u JOIN roles r ON u.id_rol=r.id_rol
                          WHERE u.id_usuario=%s AND r.nombre=%s LIMIT 1""",(id_usuario,nombre_rol))
        if not cursor.fetchone():
            return jsonify({"success":False,"message":"Usuario no encontrado."}), 404
        cursor.execute("DELETE FROM usuarios WHERE id_usuario=%s",(id_usuario,))
        conn.commit()
        return jsonify({"success":True,"message":"Usuario eliminado."}), 200
    except Exception as e:
        return jsonify({"success":False,"message":"Error al eliminar."}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@superadmin_bp.route('/superadmin/<int:id>/estado', methods=['PUT'])
@requiere_token(["superadmin"])
def estado_superadmin(id): return _cambiar_estado(id,"superadmin")

@superadmin_bp.route('/admin/<int:id>/estado', methods=['PUT'])
@requiere_token(["superadmin"])
def estado_admin(id): return _cambiar_estado(id,"admin")

@superadmin_bp.route('/medico/<int:id>/estado', methods=['PUT'])
@requiere_token(["superadmin"])
def estado_medico(id): return _cambiar_estado(id,"medico")

@superadmin_bp.route('/superadmin/<int:id>', methods=['DELETE'])
@requiere_token(["superadmin"])
def eliminar_superadmin(id): return _eliminar_usuario(id,"superadmin")

@superadmin_bp.route('/admin/<int:id>', methods=['DELETE'])
@requiere_token(["superadmin"])
def eliminar_admin(id): return _eliminar_usuario(id,"admin")


# ── MÉDICOS ────────────────────────────────────────────────────
@superadmin_bp.route('/medicos', methods=['GET'])
@requiere_token(["superadmin"])
def listar_medicos():
    conn = cursor = None
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT u.id_usuario, u.email, u.estado, u.perfil_completo,
                   m.nombre, m.apellido_paterno,
                   GROUP_CONCAT(e.nombre SEPARATOR ', ') AS especialidad
            FROM usuarios u
            JOIN roles r ON u.id_rol=r.id_rol
            LEFT JOIN medicos m ON m.id_medico=u.id_medico
            LEFT JOIN medico_especialidad me ON me.id_medico=m.id_medico
            LEFT JOIN especialidades e ON e.id_especialidad=me.id_especialidad
            WHERE r.nombre='medico'
            GROUP BY u.id_usuario ORDER BY u.email
        """)
        lista = cursor.fetchall()
        for item in lista:
            item["perfil_completo"] = bool(item["perfil_completo"])
        return jsonify({"success":True,"medicos":lista}), 200
    except Exception as e:
        print(f"[MEDICOS ERROR] {e}")
        return jsonify({"success":False,"message":"Error al obtener médicos."}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


# ── SOLICITUDES RECUPERACIÓN ───────────────────────────────────
@superadmin_bp.route('/solicitudes', methods=['GET'])
@requiere_token(["superadmin"])
def listar_solicitudes():
    conn = cursor = None
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("""SELECT sr.id, u.email, sr.estado, sr.fecha
                          FROM solicitudes_recuperacion sr
                          LEFT JOIN usuarios u ON u.id_usuario=sr.id_usuario
                          ORDER BY sr.fecha DESC""")
        lista = cursor.fetchall()
        for item in lista:
            if item.get("fecha"): item["fecha"] = item["fecha"].isoformat()
        return jsonify({"success":True,"solicitudes":lista}), 200
    except Exception as e:
        return jsonify({"success":False,"message":"Error al obtener solicitudes."}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@superadmin_bp.route('/solicitud/<int:id>', methods=['PUT'])
@requiere_token(["superadmin"])
def responder_solicitud(id):
    data  = request.get_json(silent=True) or {}
    estado = (data.get("estado") or "").strip()
    mapa  = {"aprobada":"aprobado","rechazada":"rechazado","aprobado":"aprobado","rechazado":"rechazado"}
    estado_bd = mapa.get(estado)
    if not estado_bd:
        return jsonify({"success":False,"message":"Estado inválido."}), 400
    conn = cursor = None
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("UPDATE solicitudes_recuperacion SET estado=%s WHERE id=%s",(estado_bd,id))
        conn.commit()
        return jsonify({"success":True,"message":f"Solicitud {estado_bd}."}), 200
    except Exception as e:
        return jsonify({"success":False,"message":"Error al actualizar."}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


# ── BLOQUEADOS ─────────────────────────────────────────────────
@superadmin_bp.route('/bloqueados', methods=['GET'])
@requiere_token(["superadmin"])
def listar_bloqueados():
    conn = cursor = None
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("""SELECT id_usuario,email,intentos_fallidos,fecha_bloqueo
                          FROM usuarios WHERE bloqueado=TRUE ORDER BY fecha_bloqueo DESC""")
        lista = cursor.fetchall()
        for item in lista:
            if item.get("fecha_bloqueo"): item["fecha_bloqueo"] = item["fecha_bloqueo"].isoformat()
        return jsonify({"success":True,"usuarios":lista}), 200
    except Exception as e:
        return jsonify({"success":False,"message":"Error al obtener bloqueados."}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@superadmin_bp.route('/desbloquear/<int:id>', methods=['PUT'])
@requiere_token(["superadmin"])
def desbloquear(id):
    conn = cursor = None
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("""UPDATE usuarios SET bloqueado=FALSE, intentos_fallidos=0,
                          fecha_bloqueo=NULL WHERE id_usuario=%s""",(id,))
        _registrar_auditoria(cursor, id, "DESBLOQUEADO")
        conn.commit()
        return jsonify({"success":True,"message":"Usuario desbloqueado."}), 200
    except Exception as e:
        return jsonify({"success":False,"message":"Error al desbloquear."}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


# ── AUDITORÍA ──────────────────────────────────────────────────
@superadmin_bp.route('/auditoria', methods=['GET'])
@requiere_token(["superadmin"])
def auditoria():
    limit = request.args.get("limit", 50, type=int)
    conn = cursor = None
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("""SELECT a.id_log AS id, a.id_usuario, u.email, a.accion, a.fecha
                          FROM auditoria a LEFT JOIN usuarios u ON u.id_usuario=a.id_usuario
                          ORDER BY a.fecha DESC LIMIT %s""",(limit,))
        logs = cursor.fetchall()
        for log in logs:
            if log.get("fecha"): log["fecha"] = log["fecha"].isoformat()
        return jsonify({"success":True,"logs":logs}), 200
    except Exception as e:
        return jsonify({"success":False,"message":"Error al obtener auditoría."}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
