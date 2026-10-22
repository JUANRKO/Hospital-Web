from flask import Blueprint, request, jsonify
from config import get_connection, JWT_SECRET_KEY
import jwt
import functools
import datetime
import os
from datetime import date

medico_bp = Blueprint('medico', __name__)


# ══════════════════════════════════════════════════════════════
# DECORADOR
# ══════════════════════════════════════════════════════════════
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
                print(f"[JWT INVALID medico] {e}")
                return jsonify({"success": False, "message": "Token inválido."}), 401

            if roles_permitidos and payload.get("rol") not in roles_permitidos:
                return jsonify({"success": False, "message": "Acceso denegado."}), 403

            request.usuario_actual = payload
            return f(*args, **kwargs)
        return wrapper
    return decorador


def _id_medico_desde_token(cursor):
    """Obtiene el id_medico a partir del id_usuario del token."""
    id_usuario = request.usuario_actual.get("sub")
    cursor.execute(
        "SELECT id_medico FROM usuarios WHERE id_usuario = %s LIMIT 1", (id_usuario,)
    )
    row = cursor.fetchone()
    if not row or not row["id_medico"]:
        return None
    return row["id_medico"]


def _registrar_auditoria(cursor, id_usuario, accion):
    try:
        cursor.execute(
            "INSERT INTO auditoria (id_usuario, accion, fecha) VALUES (%s, %s, NOW())",
            (id_usuario, accion)
        )
    except Exception as e:
        print(f"[AUDITORIA WARN] {e}")


# ══════════════════════════════════════════════════════════════
# 1. STATS MÉDICO — GET /api/medico/stats
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/stats', methods=['GET'])
@requiere_token(["medico"])
def stats_medico():
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_medico = _id_medico_desde_token(cursor)
        if not id_medico:
            return jsonify({"success": False, "message": "Perfil médico no encontrado."}), 404

        # Nombre del médico
        cursor.execute(
            "SELECT nombre, apellido_paterno FROM medicos WHERE id_medico = %s LIMIT 1",
            (id_medico,)
        )
        med = cursor.fetchone()
        nombre = f"{med['nombre']} {med['apellido_paterno']}" if med else ""

        # Fichas de hoy
        cursor.execute("""
            SELECT COUNT(*) AS t FROM fichas f
            JOIN estados_ficha ef ON ef.id_estado = f.id_estado
            WHERE f.id_medico = %s AND DATE(f.fecha_registro) = CURDATE()
        """, (id_medico,))
        fichas_hoy = cursor.fetchone()["t"]

        # En espera (pendientes)
        cursor.execute("""
            SELECT COUNT(*) AS t FROM fichas f
            JOIN estados_ficha ef ON ef.id_estado = f.id_estado
            WHERE f.id_medico = %s AND ef.nombre = 'pendiente'
            AND DATE(f.fecha_registro) = CURDATE()
        """, (id_medico,))
        en_espera = cursor.fetchone()["t"]

        # Atendidos (completadas hoy)
        cursor.execute("""
            SELECT COUNT(*) AS t FROM fichas f
            JOIN estados_ficha ef ON ef.id_estado = f.id_estado
            WHERE f.id_medico = %s AND ef.nombre = 'completada'
            AND DATE(f.fecha_registro) = CURDATE()
        """, (id_medico,))
        atendidos = cursor.fetchone()["t"]

        # Cupos restantes
        cursor.execute("""
            SELECT COALESCE(SUM(c.cantidad_maxima - c.cantidad_reservada), 0) AS t
            FROM cupos c
            JOIN medico_especialidad me ON me.id_especialidad = c.id_especialidad
            WHERE me.id_medico = %s AND c.fecha = CURDATE()
        """, (id_medico,))
        cupos_restantes = cursor.fetchone()["t"]

        # Especialidades aprobadas
        cursor.execute("""
            SELECT e.nombre FROM especialidades e
            JOIN medico_especialidad me ON me.id_especialidad = e.id_especialidad
            WHERE me.id_medico = %s AND e.estado = 'activa'
            ORDER BY e.nombre
        """, (id_medico,))
        especialidades = [row["nombre"] for row in cursor.fetchall()]

        return jsonify({
            "success":         True,
            "nombre":          nombre,
            "fichas_hoy":      fichas_hoy,
            "en_espera":       en_espera,
            "atendidos":       atendidos,
            "cupos_restantes": cupos_restantes,
            "especialidades":  especialidades
        }), 200

    except Exception as e:
        print(f"[MEDICO STATS ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener estadísticas."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# 2. FICHAS DEL DÍA — GET /api/medico/fichas
#    ?fecha=YYYY-MM-DD  (opcional, default: hoy)
#    ?estado=pendiente  (opcional)
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/fichas', methods=['GET'])
@requiere_token(["medico"])
def fichas_medico():
    estado_filtro = request.args.get("estado") or None
    fecha_filtro  = request.args.get("fecha")  or None
    limit         = request.args.get("limit", 200, type=int)

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_medico = _id_medico_desde_token(cursor)
        if not id_medico:
            return jsonify({"success": False, "message": "Perfil médico no encontrado."}), 404

        cursor.execute("""
            SELECT
                fecha,
                MAX(tiene_fichas)  AS tiene_fichas,
                MAX(tiene_agenda)  AS tiene_agenda,
                MAX(agenda_estado) AS agenda_estado
            FROM (
                SELECT ag.fecha,
                       0          AS tiene_fichas,
                       1          AS tiene_agenda,
                       ag.estado  AS agenda_estado
                FROM agenda_medico ag
                WHERE ag.id_medico = %s
                  AND ag.estado NOT IN ('rechazada', 'vencida')
                UNION ALL
                SELECT f.fecha,
                       1     AS tiene_fichas,
                       0     AS tiene_agenda,
                       NULL  AS agenda_estado
                FROM fichas f
                WHERE f.id_medico = %s
            ) combinado
            GROUP BY fecha
            ORDER BY fecha ASC
            LIMIT 90
        """, (id_medico, id_medico))
        fechas_raw = cursor.fetchall()

        hoy = datetime.date.today()
        futuras  = []
        pasadas  = []
        for row in fechas_raw:
            f_str  = str(row["fecha"])
            f_date = row["fecha"] if isinstance(row["fecha"], datetime.date) else datetime.date.fromisoformat(f_str)
            entry  = {
                "fecha":         f_str,
                "tiene_fichas":  bool(row["tiene_fichas"]),
                "tiene_agenda":  bool(row["tiene_agenda"]),
                "agenda_estado": row.get("agenda_estado") or "",
                "es_hoy":        f_date == hoy,
                "es_futuro":     f_date > hoy,
            }
            if f_date >= hoy:
                futuras.append(entry)
            else:
                pasadas.append(entry)

        pasadas.sort(key=lambda x: x["fecha"], reverse=True)
        fechas_disponibles = futuras + pasadas

        if not fecha_filtro:
            hoy_str   = str(hoy)
            hoy_entry = next((f for f in fechas_disponibles if f["es_hoy"]), None)
            if hoy_entry:
                fecha_filtro = hoy_str
            else:
                futura = next((f["fecha"] for f in fechas_disponibles if f["es_futuro"]), None)
                if futura:
                    fecha_filtro = futura
                elif fechas_disponibles:
                    fecha_filtro = fechas_disponibles[0]["fecha"]
                else:
                    fecha_filtro = hoy_str

        query = """
            SELECT f.id_ficha, f.codigo_ficha, f.numero_turno, f.fecha,
                   f.confirmada, f.fecha_limite_confirmacion,
                   CONCAT(p.nombre,' ',p.apellido_paterno) AS paciente,
                   p.ci,
                   e.nombre  AS especialidad,
                   ef.nombre AS estado,
                   f.fecha_registro,
                   (SELECT TIME_FORMAT(
                       ADDTIME(
                           ag.hora_inicio,
                           SEC_TO_TIME(
                               FLOOR(
                                   TIME_TO_SEC(TIMEDIFF(ag.hora_fin, ag.hora_inicio))
                                   / ag.cupos_solicitados
                               ) * (f.numero_turno - 1)
                           )
                       ), '%H:%i')
                    FROM agenda_medico ag
                    WHERE ag.id_medico = f.id_medico
                      AND ag.id_especialidad = f.id_especialidad
                      AND ag.fecha = f.fecha
                      AND ag.estado = 'aprobada'
                    LIMIT 1
                   ) AS hora_estimada
            FROM fichas f
            JOIN pacientes      p  ON p.id_paciente    = f.id_paciente
            JOIN especialidades e  ON e.id_especialidad = f.id_especialidad
            JOIN estados_ficha  ef ON ef.id_estado      = f.id_estado
            WHERE f.id_medico = %s
              AND f.fecha = %s
        """
        params = [id_medico, fecha_filtro]

        if estado_filtro:
            query += " AND ef.nombre = %s"
            params.append(estado_filtro)

        query += " ORDER BY f.numero_turno ASC LIMIT %s"
        params.append(limit)

        cursor.execute(query, params)
        fichas = cursor.fetchall()
        for f in fichas:
            if f.get("fecha"):          f["fecha"]          = str(f["fecha"])
            if f.get("fecha_registro"): f["fecha_registro"] = f["fecha_registro"].isoformat()
            f["confirmada"] = bool(f.get("confirmada"))
            if f.get("fecha_limite_confirmacion"):
                f["fecha_limite_confirmacion"] = f["fecha_limite_confirmacion"].isoformat()

        return jsonify({
            "success":            True,
            "fichas":             fichas,
            "fecha_seleccionada": fecha_filtro,
            "fechas_disponibles": fechas_disponibles
        }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500

    finally:
        if cursor: cursor.close()
        if conn:   conn.close()

# ══════════════════════════════════════════════════════════════
# 3. CAMBIAR ESTADO FICHA — PUT /api/medico/ficha/<id>/estado
# pendiente → en_atencion → completada
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/ficha/<int:id>/estado', methods=['PUT'])
@requiere_token(["medico"])
def cambiar_estado_ficha(id):
    data         = request.get_json(silent=True) or {}
    nuevo_estado = (data.get("estado") or "").strip()

    ESTADOS_VALIDOS     = ("en_atencion", "completada", "no_se_presento")
    TRANSICIONES_VALIDAS = {
        "pendiente":   ("en_atencion", "no_se_presento"),
        "en_atencion": ("completada", "no_se_presento")
    }

    if nuevo_estado not in ESTADOS_VALIDOS:
        return jsonify({"success": False, "message": "Estado inválido."}), 400

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_medico = _id_medico_desde_token(cursor)
        if not id_medico:
            return jsonify({"success": False, "message": "Perfil médico no encontrado."}), 404

        # Verificar que la ficha pertenece a este médico
        cursor.execute("""
            SELECT f.id_ficha, ef.nombre AS estado_actual
            FROM fichas f
            JOIN estados_ficha ef ON ef.id_estado = f.id_estado
            WHERE f.id_ficha = %s AND f.id_medico = %s LIMIT 1
        """, (id, id_medico))
        ficha = cursor.fetchone()

        if not ficha:
            return jsonify({"success": False, "message": "Ficha no encontrada o no te pertenece."}), 404

        # Verificar transición válida
        opciones_validas = TRANSICIONES_VALIDAS.get(ficha["estado_actual"], ())
        if nuevo_estado not in opciones_validas:
            return jsonify({"success": False,
                            "message": f"No puedes pasar de '{ficha['estado_actual']}' a '{nuevo_estado}'."}), 400

        # Obtener id del nuevo estado
        cursor.execute(
            "SELECT id_estado FROM estados_ficha WHERE nombre = %s LIMIT 1", (nuevo_estado,)
        )
        est = cursor.fetchone()
        if not est:
            return jsonify({"success": False, "message": f"Estado '{nuevo_estado}' no existe."}), 400

        cursor.execute(
            "UPDATE fichas SET id_estado = %s WHERE id_ficha = %s",
            (est["id_estado"], id)
        )
        _registrar_auditoria(cursor, request.usuario_actual.get("sub"),
                             f"FICHA_ESTADO id={id} nuevo={nuevo_estado}")
        conn.commit()

        return jsonify({"success": True, "message": f"Ficha actualizada a '{nuevo_estado}'."}), 200

    except Exception as e:
        print(f"[CAMBIAR ESTADO FICHA ERROR] {e}")
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error al cambiar estado."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# 4. MIS PACIENTES — GET /api/medico/pacientes
# Pacientes que este médico ha atendido
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/pacientes', methods=['GET'])
@requiere_token(["medico"])
def mis_pacientes():
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_medico = _id_medico_desde_token(cursor)
        if not id_medico:
            return jsonify({"success": False, "message": "Perfil médico no encontrado."}), 404

        cursor.execute("""
            SELECT DISTINCT
                p.id_paciente,
                p.ci,
                p.nombre,
                p.apellido_paterno,
                p.apellido_materno,
                p.telefono,
                COUNT(f.id_ficha)        AS total_fichas,
                MAX(f.fecha_registro)    AS ultima_atencion
            FROM fichas f
            JOIN pacientes p ON p.id_paciente = f.id_paciente
            WHERE f.id_medico = %s
            GROUP BY p.id_paciente
            ORDER BY ultima_atencion DESC
        """, (id_medico,))
        pacientes = cursor.fetchall()
        for p in pacientes:
            if p.get("ultima_atencion"):
                p["ultima_atencion"] = p["ultima_atencion"].isoformat()

        return jsonify({"success": True, "pacientes": pacientes}), 200

    except Exception as e:
        print(f"[MIS PACIENTES ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener pacientes."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# 5. HISTORIAL PACIENTE — GET /api/medico/paciente/<id>/historial
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/paciente/<int:id>/historial', methods=['GET'])
@requiere_token(["medico"])
def historial_paciente(id):
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_medico = _id_medico_desde_token(cursor)
        if not id_medico:
            return jsonify({"success": False, "message": "Perfil médico no encontrado."}), 404

        cursor.execute("""
            SELECT f.id_ficha, f.fecha, f.numero_turno,
                   e.nombre  AS especialidad,
                   ef.nombre AS estado,
                   f.fecha_registro
            FROM fichas f
            JOIN especialidades e  ON e.id_especialidad = f.id_especialidad
            JOIN estados_ficha  ef ON ef.id_estado      = f.id_estado
            WHERE f.id_paciente = %s AND f.id_medico = %s
            ORDER BY f.fecha DESC, f.numero_turno ASC
        """, (id, id_medico))
        historial = cursor.fetchall()
        for h in historial:
            if h.get("fecha"):          h["fecha"]          = str(h["fecha"])
            if h.get("fecha_registro"): h["fecha_registro"] = h["fecha_registro"].isoformat()

        return jsonify({"success": True, "historial": historial}), 200

    except Exception as e:
        print(f"[HISTORIAL PACIENTE ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener historial."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# 6. MIS ESPECIALIDADES — GET /api/medico/especialidades
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/especialidades', methods=['GET'])
@requiere_token(["medico"])
def mis_especialidades():
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_medico = _id_medico_desde_token(cursor)
        if not id_medico:
            return jsonify({"success": False, "message": "Perfil médico no encontrado."}), 404

        # Aprobadas
        cursor.execute("""
            SELECT e.id_especialidad, e.nombre, e.descripcion
            FROM especialidades e
            JOIN medico_especialidad me ON me.id_especialidad = e.id_especialidad
            WHERE me.id_medico = %s AND e.estado = 'activa'
            ORDER BY e.nombre
        """, (id_medico,))
        aprobadas = cursor.fetchall()

        # Solicitudes
        cursor.execute("""
            SELECT se.id, e.nombre AS especialidad, se.estado, se.fecha
            FROM solicitudes_especialidad se
            JOIN especialidades e ON e.id_especialidad = se.id_especialidad
            WHERE se.id_medico = %s
            ORDER BY FIELD(se.estado,'pendiente','aprobada','rechazada'), se.fecha DESC
        """, (id_medico,))
        solicitudes = cursor.fetchall()
        for s in solicitudes:
            if s.get("fecha"): s["fecha"] = s["fecha"].isoformat()

        return jsonify({
            "success":     True,
            "aprobadas":   aprobadas,
            "solicitudes": solicitudes
        }), 200

    except Exception as e:
        print(f"[MIS ESPECIALIDADES ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener especialidades."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# 7. SOLICITAR ESPECIALIDAD — POST /api/medico/solicitar_especialidad
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/solicitar_especialidad', methods=['POST'])
@requiere_token(["medico"])
def solicitar_especialidad():
    data = request.get_json(silent=True) or {}
    id_especialidad = data.get("id_especialidad")
    if not id_especialidad:
        return jsonify({"success": False, "message": "Especialidad requerida."}), 400

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_medico = _id_medico_desde_token(cursor)
        if not id_medico:
            return jsonify({"success": False, "message": "Perfil médico no encontrado."}), 404

        # Verificar que la especialidad existe y está activa
        cursor.execute(
            "SELECT nombre FROM especialidades WHERE id_especialidad = %s AND estado = 'activa' LIMIT 1",
            (id_especialidad,)
        )
        esp = cursor.fetchone()
        if not esp:
            return jsonify({"success": False, "message": "Especialidad no disponible."}), 404

        # Verificar que no tenga ya esa especialidad asignada
        cursor.execute("""
            SELECT id_medico FROM medico_especialidad
            WHERE id_medico = %s AND id_especialidad = %s LIMIT 1
        """, (id_medico, id_especialidad))
        if cursor.fetchone():
            return jsonify({"success": False,
                            "message": f"Ya tienes la especialidad '{esp['nombre']}' asignada."}), 409

        # Verificar que no tenga solicitud pendiente para esa especialidad
        cursor.execute("""
            SELECT id FROM solicitudes_especialidad
            WHERE id_medico = %s AND id_especialidad = %s AND estado = 'pendiente' LIMIT 1
        """, (id_medico, id_especialidad))
        if cursor.fetchone():
            return jsonify({"success": False,
                            "message": f"Ya tienes una solicitud pendiente para '{esp['nombre']}'."}), 409

        cursor.execute("""
            INSERT INTO solicitudes_especialidad (id_medico, id_especialidad, estado, fecha)
            VALUES (%s, %s, 'pendiente', NOW())
        """, (id_medico, id_especialidad))

        _registrar_auditoria(cursor, request.usuario_actual.get("sub"),
                             f"SOLICITAR_ESP id_esp={id_especialidad}")
        conn.commit()

        return jsonify({"success": True,
                        "message": f"Solicitud para '{esp['nombre']}' enviada correctamente."}), 201

    except Exception as e:
        print(f"[SOLICITAR ESP ERROR] {e}")
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error al enviar solicitud."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# 8. ESPECIALIDADES ACTIVAS — GET /api/especialidades_activas
# Usada por el formulario completar perfil Y por el modal solicitar
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/especialidades_activas', methods=['GET'])
@requiere_token(["medico", "admin", "superadmin"])
def especialidades_activas():
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id_especialidad, nombre, descripcion
            FROM especialidades
            WHERE estado = 'activa'
            ORDER BY nombre
        """)
        return jsonify({"success": True, "especialidades": cursor.fetchall()}), 200
    except Exception as e:
        print(f"[ESPECIALIDADES ACTIVAS ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener especialidades."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# 9. MIS HORARIOS — GET /api/medico/horarios
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/horarios', methods=['GET'])
@requiere_token(["medico"])
def mis_horarios():
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_medico = _id_medico_desde_token(cursor)
        if not id_medico:
            return jsonify({"success": False, "message": "Perfil médico no encontrado."}), 404

        cursor.execute("""
            SELECT id_horario, dia_semana,
                   hora_inicio, hora_fin, activo
            FROM horarios_medico
            WHERE id_medico = %s
            ORDER BY FIELD(dia_semana,'lunes','martes','miercoles','jueves','viernes','sabado','domingo')
        """, (id_medico,))
        horarios = cursor.fetchall()
        for h in horarios:
            if h.get("hora_inicio"): h["hora_inicio"] = str(h["hora_inicio"])
            if h.get("hora_fin"):    h["hora_fin"]    = str(h["hora_fin"])

        return jsonify({"success": True, "horarios": horarios}), 200

    except Exception as e:
        print(f"[MIS HORARIOS ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener horarios."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# 10. AGREGAR HORARIO — POST /api/medico/horario
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/horario', methods=['POST'])
@requiere_token(["medico"])
def agregar_horario():
    data = request.get_json(silent=True) or {}
    dia  = (data.get("dia_semana")  or "").strip()
    ini  = (data.get("hora_inicio") or "").strip()
    fin  = (data.get("hora_fin")    or "").strip()

    DIAS_VALIDOS = ["lunes","martes","miercoles","jueves","viernes","sabado","domingo"]
    if dia not in DIAS_VALIDOS:
        return jsonify({"success": False, "message": "Día inválido."}), 400
    if not ini or not fin:
        return jsonify({"success": False, "message": "Hora inicio y fin son obligatorias."}), 400
    if ini >= fin:
        return jsonify({"success": False, "message": "La hora fin debe ser mayor a la hora inicio."}), 400

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_medico = _id_medico_desde_token(cursor)
        if not id_medico:
            return jsonify({"success": False, "message": "Perfil médico no encontrado."}), 404

        # No puede tener dos horarios el mismo día
        cursor.execute("""
            SELECT id_horario FROM horarios_medico
            WHERE id_medico = %s AND dia_semana = %s LIMIT 1
        """, (id_medico, dia))
        if cursor.fetchone():
            return jsonify({"success": False,
                            "message": f"Ya tienes un horario registrado para el {dia}. Edítalo en su lugar."}), 409

        cursor.execute("""
            INSERT INTO horarios_medico (id_medico, dia_semana, hora_inicio, hora_fin)
            VALUES (%s, %s, %s, %s)
        """, (id_medico, dia, ini, fin))

        _registrar_auditoria(cursor, request.usuario_actual.get("sub"),
                             f"AGREGAR_HORARIO dia={dia}")
        conn.commit()
        return jsonify({"success": True, "message": "Horario agregado correctamente."}), 201

    except Exception as e:
        print(f"[AGREGAR HORARIO ERROR] {e}")
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error al agregar horario."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# 11. EDITAR HORARIO — PUT /api/medico/horario/<id>
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/horario/<int:id>', methods=['PUT'])
@requiere_token(["medico"])
def editar_horario(id):
    data = request.get_json(silent=True) or {}
    dia  = (data.get("dia_semana")  or "").strip()
    ini  = (data.get("hora_inicio") or "").strip()
    fin  = (data.get("hora_fin")    or "").strip()

    if not dia or not ini or not fin:
        return jsonify({"success": False, "message": "Todos los campos son obligatorios."}), 400
    if ini >= fin:
        return jsonify({"success": False, "message": "La hora fin debe ser mayor a la hora inicio."}), 400

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_medico = _id_medico_desde_token(cursor)
        if not id_medico:
            return jsonify({"success": False, "message": "Perfil médico no encontrado."}), 404

        # Verificar que el horario pertenece a este médico
        cursor.execute(
            "SELECT id_horario FROM horarios_medico WHERE id_horario = %s AND id_medico = %s LIMIT 1",
            (id, id_medico)
        )
        if not cursor.fetchone():
            return jsonify({"success": False, "message": "Horario no encontrado."}), 404

        cursor.execute("""
            UPDATE horarios_medico
            SET dia_semana = %s, hora_inicio = %s, hora_fin = %s
            WHERE id_horario = %s
        """, (dia, ini, fin, id))

        _registrar_auditoria(cursor, request.usuario_actual.get("sub"),
                             f"EDITAR_HORARIO id={id} dia={dia}")
        conn.commit()
        return jsonify({"success": True, "message": "Horario actualizado correctamente."}), 200

    except Exception as e:
        print(f"[EDITAR HORARIO ERROR] {e}")
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error al editar horario."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# 12. ELIMINAR HORARIO — DELETE /api/medico/horario/<id>
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/horario/<int:id>', methods=['DELETE'])
@requiere_token(["medico"])
def eliminar_horario(id):
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_medico = _id_medico_desde_token(cursor)
        if not id_medico:
            return jsonify({"success": False, "message": "Perfil médico no encontrado."}), 404

        cursor.execute(
            "SELECT id_horario FROM horarios_medico WHERE id_horario = %s AND id_medico = %s LIMIT 1",
            (id, id_medico)
        )
        if not cursor.fetchone():
            return jsonify({"success": False, "message": "Horario no encontrado."}), 404

        cursor.execute("DELETE FROM horarios_medico WHERE id_horario = %s", (id,))
        _registrar_auditoria(cursor, request.usuario_actual.get("sub"),
                             f"ELIMINAR_HORARIO id={id}")
        conn.commit()
        return jsonify({"success": True, "message": "Horario eliminado."}), 200

    except Exception as e:
        print(f"[ELIMINAR HORARIO ERROR] {e}")
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error al eliminar horario."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# 12b. TOGGLE ESTADO HORARIO — PATCH /api/medico/horario/<id>/estado
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/horario/<int:id>/estado', methods=['PATCH'])
@requiere_token(["medico"])
def toggle_horario(id):
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_medico = _id_medico_desde_token(cursor)
        if not id_medico:
            return jsonify({"success": False, "message": "Perfil médico no encontrado."}), 404

        cursor.execute(
            "SELECT id_horario, activo, dia_semana FROM horarios_medico WHERE id_horario = %s AND id_medico = %s LIMIT 1",
            (id, id_medico)
        )
        horario = cursor.fetchone()
        if not horario:
            return jsonify({"success": False, "message": "Horario no encontrado."}), 404

        nuevo_estado = not horario["activo"]
        cursor.execute(
            "UPDATE horarios_medico SET activo = %s WHERE id_horario = %s",
            (nuevo_estado, id)
        )
        _registrar_auditoria(cursor, request.usuario_actual.get("sub"),
                             f"TOGGLE_HORARIO id={id} dia={horario['dia_semana']} activo={nuevo_estado}")
        conn.commit()
        return jsonify({
            "success": True,
            "activo":  nuevo_estado,
            "message": f"Horario {'activado' if nuevo_estado else 'desactivado'}."
        }), 200

    except Exception as e:
        print(f"[TOGGLE HORARIO ERROR] {e}")
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error al cambiar estado del horario."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# 13. NOTIFICACIONES — GET /api/medico/notificaciones
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/notificaciones', methods=['GET'])
@requiere_token(["medico"])
def mis_notificaciones():
    limit = request.args.get("limit", 50, type=int)
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_usuario = request.usuario_actual.get("sub")
        cursor.execute("""
            SELECT id_notificacion, mensaje, fecha, estado
            FROM notificaciones
            WHERE id_usuario = %s
            ORDER BY fecha DESC
            LIMIT %s
        """, (id_usuario, limit))
        notis = cursor.fetchall()
        for n in notis:
            if n.get("fecha"): n["fecha"] = n["fecha"].isoformat()

        return jsonify({"success": True, "notificaciones": notis}), 200

    except Exception as e:
        print(f"[NOTIFICACIONES ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener notificaciones."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# 14. MARCAR NOTIFICACIÓN LEÍDA — PUT /api/medico/notificacion/<id>/leer
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/notificacion/<int:id>/leer', methods=['PUT'])
@requiere_token(["medico"])
def marcar_leida(id):
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_usuario = request.usuario_actual.get("sub")
        cursor.execute("""
            UPDATE notificaciones SET estado = 'leido'
            WHERE id_notificacion = %s AND id_usuario = %s
        """, (id, id_usuario))
        conn.commit()
        return jsonify({"success": True}), 200

    except Exception as e:
        return jsonify({"success": False, "message": "Error al actualizar."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# 15. MARCAR TODAS LEÍDAS — PUT /api/medico/notificaciones/leer_todas
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/notificaciones/leer_todas', methods=['PUT'])
@requiere_token(["medico"])
def leer_todas():
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_usuario = request.usuario_actual.get("sub")
        cursor.execute("""
            UPDATE notificaciones SET estado = 'leido'
            WHERE id_usuario = %s AND estado = 'no_leido'
        """, (id_usuario,))
        conn.commit()
        return jsonify({"success": True, "message": "Todas las notificaciones marcadas como leídas."}), 200

    except Exception as e:
        return jsonify({"success": False, "message": "Error al actualizar."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# AGENDA — CREAR — POST /api/medico/agenda
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/agenda', methods=['POST'])
@requiere_token(["medico"])
def crear_agenda():
    data = request.get_json(silent=True) or {}

    id_especialidad   = data.get("id_especialidad")
    fecha             = (data.get("fecha")        or "").strip()
    turno             = (data.get("turno")         or "").strip()
    hora_inicio       = (data.get("hora_inicio")   or "").strip()
    hora_fin          = (data.get("hora_fin")       or "").strip()
    cupos_solicitados = data.get("cupos_solicitados")

    # Validaciones
    if not all([id_especialidad, fecha, turno, hora_inicio, hora_fin, cupos_solicitados]):
        return jsonify({"success": False, "message": "Todos los campos son obligatorios."}), 400
    if turno not in ("mañana", "tarde"):
        return jsonify({"success": False, "message": "Turno inválido."}), 400
    if hora_inicio >= hora_fin:
        return jsonify({"success": False, "message": "La hora fin debe ser mayor a la hora inicio."}), 400
    if not isinstance(cupos_solicitados, int) or cupos_solicitados < 1:
        return jsonify({"success": False, "message": "Los cupos deben ser al menos 1."}), 400

    # Validar fecha — no puede ser pasada ni más de 7 días
    try:
        fecha_dt = datetime.date.fromisoformat(fecha)
        hoy      = datetime.date.today()
        if fecha_dt < hoy:
            return jsonify({"success": False,
                    "message": "La fecha debe ser posterior a hoy."}), 400
        if (fecha_dt - hoy).days > 7:
            return jsonify({"success": False,
                    "message": "Solo puedes publicar agenda con máximo 7 días de anticipación."}), 400
    except ValueError:
        return jsonify({"success": False, "message": "Fecha inválida."}), 400

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_medico = _id_medico_desde_token(cursor)
        if not id_medico:
            return jsonify({"success": False, "message": "Perfil médico no encontrado."}), 404

        # Verificar que tiene esa especialidad aprobada
        cursor.execute("""
            SELECT id_medico FROM medico_especialidad
            WHERE id_medico = %s AND id_especialidad = %s LIMIT 1
        """, (id_medico, id_especialidad))
        if not cursor.fetchone():
            return jsonify({"success": False,
                            "message": "No tienes esa especialidad aprobada."}), 403

        # Verificar que no existe agenda para ese día/turno/especialidad
        cursor.execute("""
            SELECT id_agenda FROM agenda_medico
            WHERE id_medico = %s AND id_especialidad = %s
              AND fecha = %s AND turno = %s
              AND estado NOT IN ('rechazada','vencida')
            LIMIT 1
        """, (id_medico, id_especialidad, fecha, turno))
        if cursor.fetchone():
            return jsonify({"success": False,
                            "message": f"Ya tienes una agenda para ese día y turno."}), 409

        # Calcular tiempo promedio
        h_ini  = datetime.datetime.strptime(hora_inicio, "%H:%M")
        h_fin  = datetime.datetime.strptime(hora_fin,    "%H:%M")
        minutos = int((h_fin - h_ini).seconds / 60)
        tiempo_promedio = round(minutos / cupos_solicitados)

        cursor.execute("""
            INSERT INTO agenda_medico
                (id_medico, id_especialidad, fecha, turno,
                 hora_inicio, hora_fin, cupos_solicitados, estado, fecha_solicitud)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pendiente', NOW())
        """, (id_medico, id_especialidad, fecha, turno,
              hora_inicio, hora_fin, cupos_solicitados))

        id_agenda = cursor.lastrowid

        # Notificar a TODOS los admins (un registro por cada admin)
        cursor.execute("""
            SELECT u.id_usuario FROM usuarios u
            JOIN roles r ON r.id_rol = u.id_rol
            WHERE r.nombre = 'admin' AND u.estado = 'activo'
        """)
        admins = cursor.fetchall()
        cursor.execute("""
            SELECT m.nombre, m.apellido_paterno FROM medicos m WHERE m.id_medico = %s
        """, (id_medico,))
        med = cursor.fetchone()
        cursor.execute("SELECT nombre FROM especialidades WHERE id_especialidad = %s", (id_especialidad,))
        esp_row = cursor.fetchone()
        msg_noti = f"Nueva solicitud de agenda: Dr. {med['nombre']} {med['apellido_paterno']} — {esp_row['nombre']} {turno} {fecha} — {cupos_solicitados} cupos"
        for admin in admins:
            cursor.execute("""
                INSERT INTO notificaciones (id_usuario, mensaje, tipo, fecha, estado)
                VALUES (%s, %s, 'sistema', NOW(), 'no_leido')
            """, (admin['id_usuario'], msg_noti))

        _registrar_auditoria(cursor, request.usuario_actual.get("sub"),
                             f"CREAR_AGENDA id={id_agenda} fecha={fecha} turno={turno}")
        conn.commit()

        return jsonify({
            "success":        True,
            "message":        "Agenda enviada al admin para aprobación.",
            "id_agenda":      id_agenda,
            "tiempo_promedio": tiempo_promedio
        }), 201

    except Exception as e:
        print(f"[CREAR AGENDA ERROR] {e}")
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error al crear agenda."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# AGENDA — LISTAR — GET /api/medico/agendas
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/agendas', methods=['GET'])
@requiere_token(["medico"])
def listar_agendas():
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_medico = _id_medico_desde_token(cursor)
        if not id_medico:
            return jsonify({"success": False, "message": "Perfil médico no encontrado."}), 404

        # NOTA: el vencimiento de agendas (con 24h de gracia y cálculo de
        # estadísticas) lo realiza el job /medico/job/vencer-agendas.
        # Aquí solo se listan agendas vigentes (esta sección ya no muestra
        # agendas vencidas — esas viven en Historial de Agenda).
        cursor.execute("""
            SELECT a.id_agenda, a.fecha, a.turno,
                   a.hora_inicio, a.hora_fin,
                   a.cupos_solicitados, a.cupos_aprobados,
                   a.cupos_ocupados, a.estado,
                   a.motivo_rechazo,
                   e.nombre AS especialidad,
                   e.id_especialidad,
                   ROUND(
                       TIME_TO_SEC(TIMEDIFF(a.hora_fin, a.hora_inicio)) / 60
                       / a.cupos_solicitados
                   ) AS tiempo_promedio
            FROM agenda_medico a
            JOIN especialidades e ON e.id_especialidad = a.id_especialidad
            WHERE a.id_medico = %s AND a.estado != 'vencida'
            ORDER BY a.fecha DESC, a.turno ASC
        """, (id_medico,))
        agendas = cursor.fetchall()
        hoy_str = date.today().isoformat()
        for ag in agendas:
            if ag.get("fecha"):       ag["fecha"]       = str(ag["fecha"])
            if ag.get("hora_inicio"): ag["hora_inicio"] = str(ag["hora_inicio"])
            if ag.get("hora_fin"):    ag["hora_fin"]    = str(ag["hora_fin"])
            # Marca informativa: ya pasó la fecha pero aún no se procesó el job (24h gracia)
            ag["pendiente_vencer"] = (
                ag["estado"] == "aprobada" and ag["fecha"] < hoy_str
            )

        return jsonify({"success": True, "agendas": agendas}), 200

    except Exception as e:
        print(f"[LISTAR AGENDAS ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener agendas."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# AGENDA — REPUBLICAR — POST /api/medico/agenda/<id>/republicar
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/agenda/<int:id>/republicar', methods=['POST'])
@requiere_token(["medico"])
def republicar_agenda(id):
    data = request.get_json(silent=True) or {}

    nueva_fecha       = (data.get("fecha")            or "").strip()
    cupos_solicitados = data.get("cupos_solicitados")

    if not nueva_fecha:
        return jsonify({"success": False, "message": "La nueva fecha es obligatoria."}), 400

    try:
        fecha_dt = datetime.date.fromisoformat(nueva_fecha)
        hoy      = datetime.date.today()
        if fecha_dt <= hoy:
            return jsonify({"success": False,
                            "message": "La fecha debe ser posterior a hoy."}), 400
        if (fecha_dt - hoy).days > 7:
            return jsonify({"success": False,
                            "message": "Máximo 7 días de anticipación."}), 400
    except ValueError:
        return jsonify({"success": False, "message": "Fecha inválida."}), 400

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_medico = _id_medico_desde_token(cursor)
        if not id_medico:
            return jsonify({"success": False, "message": "Perfil médico no encontrado."}), 404

        # Obtener agenda original
        cursor.execute("""
            SELECT * FROM agenda_medico
            WHERE id_agenda = %s AND id_medico = %s LIMIT 1
        """, (id, id_medico))
        agenda = cursor.fetchone()
        if not agenda:
            return jsonify({"success": False, "message": "Agenda no encontrada."}), 404

        cupos_anteriores  = agenda["cupos_aprobados"] or agenda["cupos_solicitados"]
        cupos_nuevos      = cupos_solicitados if cupos_solicitados else cupos_anteriores
        mismos_cupos      = (cupos_nuevos == cupos_anteriores)
        reduce_cupos      = (cupos_nuevos < cupos_anteriores)

        # Verificar si ya existe agenda para esa fecha/turno
        cursor.execute("""
            SELECT id_agenda FROM agenda_medico
            WHERE id_medico = %s AND id_especialidad = %s
              AND fecha = %s AND turno = %s
              AND estado NOT IN ('rechazada','vencida')
              AND id_agenda != %s
            LIMIT 1
        """, (id_medico, agenda["id_especialidad"], nueva_fecha,
              agenda["turno"], id))
        if cursor.fetchone():
            return jsonify({"success": False,
                            "message": "Ya tienes una agenda para ese día y turno."}), 409

        # Estado inicial según si cambia cupos o no
        nuevo_estado = "pendiente" if (not mismos_cupos) else "pendiente"
        # Siempre pendiente — admin debe aprobar

        # Insertar nueva agenda con referencia a la original
        cursor.execute("""
            INSERT INTO agenda_medico
                (id_medico, id_especialidad, fecha, turno,
                 hora_inicio, hora_fin, cupos_solicitados,
                 estado, id_agenda_origen, fecha_solicitud)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pendiente', %s, NOW())
        """, (id_medico, agenda["id_especialidad"], nueva_fecha,
              agenda["turno"], agenda["hora_inicio"], agenda["hora_fin"],
              cupos_nuevos, id))

        nueva_id = cursor.lastrowid

        # Guardar en historial
        cursor.execute("""
            INSERT INTO agenda_historial
                (id_agenda, cupos_anterior, cupos_nuevo,
                 estado_anterior, estado_nuevo, motivo, fecha, id_usuario)
            VALUES (%s, %s, %s, %s, 'pendiente', 'Republicación', NOW(), %s)
        """, (nueva_id, cupos_anteriores, cupos_nuevos,
              agenda["estado"], request.usuario_actual.get("sub")))

        # Notificar admin — con nivel de urgencia según reducción
        if reduce_cupos:
            nivel  = "🟡 ALERTA"
            extra  = f"Redujo cupos de {cupos_anteriores} → {cupos_nuevos}. Requiere aprobación."
        else:
            nivel  = "📋 INFO"
            extra  = f"Mismos cupos ({cupos_nuevos}). Requiere aprobación."

        cursor.execute("""
            INSERT INTO notificaciones (id_usuario, mensaje, tipo, fecha, estado)
            SELECT u.id_usuario,
                   CONCAT(%s,' Republicación de agenda: Dr. ',
                          m.nombre,' ',m.apellido_paterno,
                          ' — ',e.nombre,' ',a.turno,' ',
                          %s,' — ',%s),
                   'sistema', NOW(), 'no_leido'
            FROM usuarios u
            JOIN roles r ON r.id_rol = u.id_rol
            JOIN medicos m ON m.id_medico = %s
            JOIN especialidades e ON e.id_especialidad = %s
            JOIN agenda_medico a ON a.id_agenda = %s
            WHERE r.nombre = 'admin'
        """, (nivel, nueva_fecha, extra,
              id_medico, agenda["id_especialidad"], nueva_id))

        _registrar_auditoria(cursor, request.usuario_actual.get("sub"),
                             f"REPUBLICAR_AGENDA origen={id} nueva={nueva_id} fecha={nueva_fecha}")
        conn.commit()

        return jsonify({
            "success":     True,
            "message":     "Agenda republicada. Esperando aprobación del admin.",
            "id_agenda":   nueva_id,
            "mismos_cupos": mismos_cupos
        }), 201

    except Exception as e:
        print(f"[REPUBLICAR AGENDA ERROR] {e}")
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error al republicar agenda."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# AGENDA — ELIMINAR — DELETE /api/medico/agenda/<id>
# Solo si está pendiente y sin fichas
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/agenda/<int:id>', methods=['DELETE'])
@requiere_token(["medico"])
def eliminar_agenda(id):
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_medico = _id_medico_desde_token(cursor)
        if not id_medico:
            return jsonify({"success": False, "message": "Perfil médico no encontrado."}), 404

        cursor.execute("""
            SELECT id_agenda, estado, cupos_ocupados
            FROM agenda_medico
            WHERE id_agenda = %s AND id_medico = %s LIMIT 1
        """, (id, id_medico))
        agenda = cursor.fetchone()
        if not agenda:
            return jsonify({"success": False, "message": "Agenda no encontrada."}), 404

        if agenda["estado"] not in ("pendiente", "rechazada", "vencida"):
            return jsonify({"success": False,
                            "message": "Solo puedes eliminar agendas pendientes, rechazadas o vencidas."}), 400

        if agenda["cupos_ocupados"] > 0:
            return jsonify({"success": False,
                            "message": "No puedes eliminar una agenda con pacientes asignados."}), 400

        cursor.execute("DELETE FROM agenda_medico WHERE id_agenda = %s", (id,))
        _registrar_auditoria(cursor, request.usuario_actual.get("sub"),
                             f"ELIMINAR_AGENDA id={id}")
        conn.commit()

        return jsonify({"success": True, "message": "Agenda eliminada correctamente."}), 200

    except Exception as e:
        print(f"[ELIMINAR AGENDA ERROR] {e}")
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error al eliminar agenda."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# AGENDAS DISPONIBLES PARA PACIENTES — GET /api/agendas_disponibles
# Ruta pública — no requiere token
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/agendas_disponibles', methods=['GET'])
def agendas_disponibles():
    """
    Devuelve agendas aprobadas con cupos disponibles.
    Filtros opcionales: especialidad, fecha, turno
    """
    id_especialidad = request.args.get("especialidad") or None
    fecha_filtro    = request.args.get("fecha")        or None
    turno_filtro    = request.args.get("turno")        or None

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
                a.cupos_aprobados,
                a.cupos_ocupados,
                (a.cupos_aprobados - a.cupos_ocupados) AS cupos_disponibles,
                ROUND(
                    TIME_TO_SEC(TIMEDIFF(a.hora_fin, a.hora_inicio)) / 60
                    / a.cupos_aprobados
                ) AS tiempo_promedio,
                m.id_medico,
                CONCAT('Dr. ', m.nombre, ' ', m.apellido_paterno) AS medico_nombre,
                e.id_especialidad,
                e.nombre AS especialidad
            FROM agenda_medico a
            JOIN medicos       m ON m.id_medico       = a.id_medico
            JOIN especialidades e ON e.id_especialidad = a.id_especialidad
            WHERE a.estado = 'aprobada'
              AND a.fecha >= CURDATE()
              AND (a.cupos_aprobados - a.cupos_ocupados) > 0
        """
        params = []

        if id_especialidad:
            query += " AND e.id_especialidad = %s"
            params.append(id_especialidad)

        if fecha_filtro:
            query += " AND a.fecha = %s"
            params.append(fecha_filtro)

        if turno_filtro:
            query += " AND a.turno = %s"
            params.append(turno_filtro)

        query += " ORDER BY a.fecha ASC, a.turno ASC, m.nombre ASC"

        cursor.execute(query, params)
        agendas = cursor.fetchall()

        for ag in agendas:
            if ag.get("fecha"):       ag["fecha"]       = str(ag["fecha"])
            if ag.get("hora_inicio"): ag["hora_inicio"] = str(ag["hora_inicio"])
            if ag.get("hora_fin"):    ag["hora_fin"]    = str(ag["hora_fin"])

            # Calcular hora estimada de cada ficha disponible
            h_ini = ag["hora_inicio"][:5] if ag["hora_inicio"] else "00:00"
            h, m  = map(int, h_ini.split(":"))
            tp    = ag["tiempo_promedio"] or 20
            ocupados = ag["cupos_ocupados"] or 0

            fichas_disponibles = []
            for num in range(1, ag["cupos_aprobados"] + 1):
                mins_totales = h * 60 + m + (num - 1) * tp
                hora_est = f"{mins_totales // 60:02d}:{mins_totales % 60:02d}"
                if num > ocupados:  # solo fichas no ocupadas
                    fichas_disponibles.append({
                        "numero": num,
                        "hora_estimada": hora_est
                    })

            ag["fichas_disponibles"] = fichas_disponibles

        return jsonify({
            "success": True,
            "agendas": agendas,
            "total":   len(agendas)
        }), 200

    except Exception as e:
        print(f"[AGENDAS DISPONIBLES ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener agendas."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# ESPECIALIDADES CON AGENDAS DISPONIBLES — GET /api/especialidades_disponibles
# Para el portal del paciente — ruta pública
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/especialidades_disponibles', methods=['GET'])
def especialidades_disponibles():
    """
    Devuelve especialidades que tienen al menos una agenda
    aprobada con cupos disponibles hoy o en los próximos 7 días.
    """
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT DISTINCT
                e.id_especialidad,
                e.nombre,
                e.descripcion,
                COUNT(DISTINCT a.id_agenda)                    AS agendas_disponibles,
                MIN(a.fecha)                                   AS proxima_fecha,
                SUM(a.cupos_aprobados - a.cupos_ocupados)      AS total_cupos_disponibles
            FROM especialidades e
            JOIN agenda_medico a  ON a.id_especialidad = e.id_especialidad
            WHERE a.estado   = 'aprobada'
              AND a.fecha   >= CURDATE()
              AND a.fecha   <= DATE_ADD(CURDATE(), INTERVAL 7 DAY)
              AND (a.cupos_aprobados - a.cupos_ocupados) > 0
              AND e.estado  = 'activa'
            GROUP BY e.id_especialidad, e.nombre, e.descripcion
            ORDER BY e.nombre
        """)
        especialidades = cursor.fetchall()
        for e in especialidades:
            if e.get("proxima_fecha"):
                e["proxima_fecha"] = str(e["proxima_fecha"])

        return jsonify({
            "success":       True,
            "especialidades": especialidades
        }), 200

    except Exception as e:
        print(f"[ESPECIALIDADES DISPONIBLES ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener especialidades."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()

# ══════════════════════════════════════════════════════════════
# GUARDAR CONSULTA — POST /api/medico/consulta
# Guarda diagnóstico, opcionalmente receta, cambia ficha a completada
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/consulta', methods=['POST'])
@requiere_token(["medico"])
def guardar_consulta():
    data = request.get_json(silent=True) or {}

    id_ficha        = data.get("id_ficha")
    motivo_consulta = (data.get("motivo_consulta") or "").strip()
    sintomas        = (data.get("sintomas")        or "").strip()
    diagnostico     = (data.get("diagnostico")     or "").strip()
    tratamiento     = (data.get("tratamiento")     or "").strip()
    observaciones   = (data.get("observaciones")   or "").strip()
    requiere_receta = bool(data.get("requiere_receta", False))
    receta          = data.get("receta") or {}
    items_receta    = data.get("items_receta") or []
    requiere_posterior = bool(data.get("requiere_atencion_posterior", False))
    fecha_posterior    = data.get("fecha_atencion_posterior")

    if not id_ficha:
        return jsonify({"success": False, "message": "id_ficha es requerido."}), 400
    if not motivo_consulta:
        return jsonify({"success": False, "message": "El motivo de consulta es requerido."}), 400
    if not sintomas:
        return jsonify({"success": False, "message": "Los síntomas son requeridos."}), 400
    if not diagnostico:
        return jsonify({"success": False, "message": "El diagnóstico es requerido."}), 400
    if requiere_receta and not items_receta:
        return jsonify({"success": False, "message": "Debes agregar al menos un medicamento a la receta."}), 400
    if requiere_posterior and not fecha_posterior:
        return jsonify({"success": False, "message": "Selecciona la fecha de atención posterior."}), 400

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_medico = _id_medico_desde_token(cursor)
        if not id_medico:
            return jsonify({"success": False, "message": "Perfil médico no encontrado."}), 404

        # Verificar que la ficha pertenece a este médico y está en estado pendiente o en_atencion
        cursor.execute("""
            SELECT f.id_ficha, f.id_paciente, f.id_especialidad, ef.nombre AS estado
            FROM fichas f
            JOIN estados_ficha ef ON ef.id_estado = f.id_estado
            WHERE f.id_ficha = %s AND f.id_medico = %s LIMIT 1
        """, (id_ficha, id_medico))
        ficha = cursor.fetchone()

        if not ficha:
            return jsonify({"success": False, "message": "Ficha no encontrada o no te pertenece."}), 404
        if ficha["estado"] not in ("pendiente", "en_atencion"):
            return jsonify({"success": False, "message": "Esta ficha ya fue completada."}), 400

        id_paciente = ficha["id_paciente"]

        # 1. Insertar consulta
        cursor.execute("""
            INSERT INTO consultas
                (id_ficha, id_paciente, id_medico, motivo_consulta,
                 sintomas, diagnostico, tratamiento, observaciones)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (id_ficha, id_paciente, id_medico,
              motivo_consulta, sintomas, diagnostico,
              tratamiento or None, observaciones or None))
        id_consulta = cursor.lastrowid

        # 2. Insertar receta si requiere
        if requiere_receta and items_receta:
            indicaciones = (receta.get("indicaciones") or "").strip() or None
            cursor.execute("""
                INSERT INTO recetas (id_consulta, id_paciente, id_medico, indicaciones)
                VALUES (%s, %s, %s, %s)
            """, (id_consulta, id_paciente, id_medico, indicaciones))
            id_receta = cursor.lastrowid

            for item in items_receta:
                medicamento = (item.get("medicamento") or "").strip()
                dosis       = (item.get("dosis")       or "").strip()
                frecuencia  = (item.get("frecuencia")  or "").strip()
                duracion    = (item.get("duracion")    or "").strip()
                indicacion  = (item.get("indicacion")  or "").strip() or None
                if medicamento and dosis and frecuencia and duracion:
                    cursor.execute("""
                        INSERT INTO receta_items
                            (id_receta, medicamento, dosis, frecuencia, duracion, indicacion)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (id_receta, medicamento, dosis, frecuencia, duracion, indicacion))

        # 3. Registrar en historial del paciente
        cursor.execute("""
            INSERT INTO pacientes_historial (id_paciente, id_ficha, descripcion, id_consulta)
            VALUES (%s, %s, %s, %s)
        """, (id_paciente, id_ficha,
              f"Consulta: {diagnostico[:100]}", id_consulta))

        # 4. Cambiar ficha a completada
        cursor.execute(
            "SELECT id_estado FROM estados_ficha WHERE nombre = 'completada' LIMIT 1"
        )
        estado_completada = cursor.fetchone()
        if estado_completada:
            cursor.execute(
                "UPDATE fichas SET id_estado = %s WHERE id_ficha = %s",
                (estado_completada["id_estado"], id_ficha)
            )

        # 5. Crear ficha pre-asignada si requiere atención posterior
        id_ficha_posterior = None
        if requiere_posterior and fecha_posterior:
            cursor.execute(
                "SELECT id_estado FROM estados_ficha WHERE nombre = 'pre-asignada' LIMIT 1"
            )
            estado_pre = cursor.fetchone()
            if estado_pre:
                # Turno cronológico: cuenta cuántas fichas (de cualquier estado)
                # ya existen para ese médico/especialidad/fecha y le asigna el siguiente número
                cursor.execute("""
                    SELECT COUNT(*) AS total FROM fichas
                    WHERE id_medico = %s AND id_especialidad = %s AND fecha = %s
                """, (id_medico, ficha["id_especialidad"], fecha_posterior))
                siguiente_turno = (cursor.fetchone()["total"] or 0) + 1

                # Código de ficha único
                import random as _rnd, string as _str
                chars = [c for c in (_str.ascii_uppercase + _str.digits)
                         if c not in ('O', '0', 'I', '1', 'L')]
                codigo_ficha = f"HC-{fecha_posterior.replace('-','')}-" + \
                                "".join(_rnd.choices(chars, k=6))

                cursor.execute("""
                    INSERT INTO fichas
                        (codigo_ficha, id_paciente, id_especialidad, id_medico,
                         fecha, numero_turno, id_estado,
                         fecha_preasignacion, id_consulta_origen)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), %s)
                """, (codigo_ficha, id_paciente, ficha["id_especialidad"], id_medico,
                      fecha_posterior, siguiente_turno, estado_pre["id_estado"],
                      id_consulta))
                id_ficha_posterior = cursor.lastrowid

                # Notificar al paciente que tiene una cita pre-asignada
                cursor.execute("""
                    SELECT u.id_usuario FROM usuarios u
                    WHERE u.id_paciente = %s LIMIT 1
                """, (id_paciente,))
                u_pac = cursor.fetchone()
                if u_pac:
                    cursor.execute("""
                        INSERT INTO notificaciones
                            (id_usuario, mensaje, tipo, fecha, estado)
                        VALUES (%s, %s, 'sistema', NOW(), 'no_leido')
                    """, (u_pac["id_usuario"],
                          f"📅 Tu médico te indicó una atención de control para el "
                          f"{fecha_posterior}. Será confirmada en cuanto se publique la agenda."))

        _registrar_auditoria(cursor, request.usuario_actual.get("sub"),
                             f"GUARDAR_CONSULTA id_ficha={id_ficha} id_consulta={id_consulta}")
        conn.commit()

        return jsonify({
            "success":            True,
            "message":            "Consulta guardada correctamente.",
            "id_consulta":        id_consulta,
            "id_ficha_posterior": id_ficha_posterior
        }), 201

    except Exception as e:
        import traceback; traceback.print_exc()
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error al guardar consulta."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# CONSULTAS DE UN PACIENTE — GET /api/medico/paciente/<id>/consultas
# Historial completo de consultas de un paciente atendido por este médico
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/paciente/<int:id>/consultas', methods=['GET'])
@requiere_token(["medico"])
def consultas_paciente(id):
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_medico = _id_medico_desde_token(cursor)
        if not id_medico:
            return jsonify({"success": False, "message": "Perfil médico no encontrado."}), 404

        # Info del paciente
        cursor.execute("""
            SELECT p.id_paciente,
                   CONCAT(p.nombre,' ',p.apellido_paterno,' ',p.apellido_materno) AS nombre_completo,
                   p.ci, p.telefono, p.fecha_nacimiento, p.sexo
            FROM pacientes p WHERE p.id_paciente = %s LIMIT 1
        """, (id,))
        paciente = cursor.fetchone()
        if not paciente:
            return jsonify({"success": False, "message": "Paciente no encontrado."}), 404
        if paciente.get("fecha_nacimiento"):
            paciente["fecha_nacimiento"] = str(paciente["fecha_nacimiento"])

        # Consultas del paciente con este médico
        cursor.execute("""
            SELECT c.id_consulta, c.motivo_consulta, c.sintomas,
                   c.diagnostico, c.tratamiento, c.observaciones,
                   c.fecha_consulta,
                   e.nombre AS especialidad,
                   r.id_receta
            FROM consultas c
            JOIN fichas f ON f.id_ficha = c.id_ficha
            JOIN especialidades e ON e.id_especialidad = f.id_especialidad
            LEFT JOIN recetas r ON r.id_consulta = c.id_consulta
            WHERE c.id_paciente = %s AND c.id_medico = %s
            ORDER BY c.fecha_consulta DESC
        """, (id, id_medico))
        consultas = cursor.fetchall()

        for c in consultas:
            if c.get("fecha_consulta"):
                c["fecha_consulta"] = c["fecha_consulta"].isoformat()
            # Si tiene receta, cargar los items
            if c.get("id_receta"):
                cursor.execute("""
                    SELECT medicamento, dosis, frecuencia, duracion, indicacion
                    FROM receta_items WHERE id_receta = %s
                """, (c["id_receta"],))
                c["receta_items"] = cursor.fetchall()
            else:
                c["receta_items"] = []

        return jsonify({
            "success":   True,
            "paciente":  paciente,
            "consultas": consultas
        }), 200

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"success": False, "message": "Error al obtener consultas."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# FICHAS DEL DÍA — GET /api/medico/fichas/hoy
# Solo fichas de hoy o mañana, pendientes o en_atencion
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/fichas/hoy', methods=['GET'])
@requiere_token(["medico"])
def fichas_hoy():
    dia = request.args.get("dia", "hoy")  # "hoy" o "manana"

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_medico = _id_medico_desde_token(cursor)
        if not id_medico:
            return jsonify({"success": False, "message": "Perfil médico no encontrado."}), 404

        fecha = "CURDATE()" if dia == "hoy" else "DATE_ADD(CURDATE(), INTERVAL 1 DAY)"

        cursor.execute(f"""
            SELECT f.id_ficha, f.codigo_ficha, f.numero_turno, f.fecha,
                   f.id_paciente, f.confirmada, f.fecha_limite_confirmacion,
                   CONCAT(p.nombre,' ',p.apellido_paterno,' ',p.apellido_materno) AS paciente,
                   p.ci, p.telefono,
                   e.nombre  AS especialidad,
                   ef.nombre AS estado,
                   (SELECT TIME_FORMAT(
                       ADDTIME(
                           ag.hora_inicio,
                           SEC_TO_TIME(
                               FLOOR(
                                   TIME_TO_SEC(TIMEDIFF(ag.hora_fin, ag.hora_inicio))
                                   / ag.cupos_solicitados
                               ) * (f.numero_turno - 1)
                           )
                       ), '%H:%i')
                    FROM agenda_medico ag
                    WHERE ag.id_medico = f.id_medico
                      AND ag.id_especialidad = f.id_especialidad
                      AND ag.fecha = f.fecha
                      AND ag.estado = 'aprobada'
                    LIMIT 1
                   ) AS hora_estimada
            FROM fichas f
            JOIN pacientes     p  ON p.id_paciente    = f.id_paciente
            JOIN especialidades e  ON e.id_especialidad = f.id_especialidad
            JOIN estados_ficha ef  ON ef.id_estado      = f.id_estado
            WHERE f.id_medico = %s
              AND f.fecha = {fecha}
              AND ef.nombre IN ('pendiente', 'en_atencion')
            ORDER BY f.numero_turno ASC
        """, (id_medico,))

        fichas = cursor.fetchall()
        for f in fichas:
            if f.get("fecha"): f["fecha"] = str(f["fecha"])
            f["confirmada"] = bool(f.get("confirmada"))
            if f.get("fecha_limite_confirmacion"):
                f["fecha_limite_confirmacion"] = f["fecha_limite_confirmacion"].isoformat()

        return jsonify({"success": True, "fichas": fichas, "dia": dia}), 200

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"success": False, "message": "Error al obtener fichas."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# FECHAS DISPONIBLES PARA ATENCIÓN POSTERIOR
# GET /api/medico/fechas-posteriores
# Devuelve los días hábiles (según horarios activos) en los
# próximos 30 días, para elegir la fecha de control.
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/fechas-posteriores', methods=['GET'])
@requiere_token(["medico"])
def fechas_posteriores():
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_medico = _id_medico_desde_token(cursor)
        if not id_medico:
            return jsonify({"success": False, "message": "Perfil médico no encontrado."}), 404

        cursor.execute("""
            SELECT dia_semana, hora_inicio, hora_fin
            FROM horarios_medico
            WHERE id_medico = %s AND activo = 1
        """, (id_medico,))
        horarios = cursor.fetchall()

        if not horarios:
            return jsonify({"success": True, "fechas": [],
                            "message": "Sin horarios activos registrados."}), 200

        dias_activos = {h["dia_semana"] for h in horarios}

        from datetime import date as _date, timedelta as _td
        JS_DIA = ["lunes","martes","miercoles","jueves","viernes","sabado","domingo"]
        hoy    = _date.today()

        fechas = []
        for i in range(1, 31):
            f = hoy + _td(days=i)
            dia_nombre = JS_DIA[f.weekday()]
            if dia_nombre in dias_activos:
                fechas.append({"fecha": f.isoformat(), "dia_semana": dia_nombre})

        return jsonify({"success": True, "fechas": fechas}), 200

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"success": False, "message": "Error al obtener fechas."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# JOB: NOTIFICAR FICHAS PRE-ASIGNADAS SIN AGENDA
# POST /api/medico/job/notificar-preasignadas
# Pensado para ser llamado por un scheduler (APScheduler / cron)
# una vez al día. No requiere token de usuario, pero sí una
# clave interna simple para evitar llamadas públicas accidentales.
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/job/notificar-preasignadas', methods=['POST'])
def job_notificar_preasignadas():
    clave = request.headers.get("X-Job-Key", "")
    if clave != os.environ.get("JOB_INTERNAL_KEY", "hospital-job-2026"):
        return jsonify({"success": False, "message": "No autorizado."}), 403

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        hoy = date.today()

        # ── 1. Vencer fichas pre-asignadas cuya fecha ya llegó sin agenda aprobada ──
        cursor.execute("""
            SELECT f.id_ficha, f.id_paciente, f.fecha
            FROM fichas f
            JOIN estados_ficha ef ON ef.id_estado = f.id_estado
            WHERE ef.nombre = 'pre-asignada' AND f.fecha <= %s
        """, (hoy,))
        vencidas = cursor.fetchall()

        cursor.execute("SELECT id_estado FROM estados_ficha WHERE nombre = 'vencida' LIMIT 1")
        estado_vencida = cursor.fetchone()

        for v in vencidas:
            cursor.execute("UPDATE fichas SET id_estado = %s WHERE id_ficha = %s",
                           (estado_vencida["id_estado"], v["id_ficha"]))
            cursor.execute(
                "SELECT id_usuario FROM usuarios WHERE id_paciente = %s LIMIT 1",
                (v["id_paciente"],)
            )
            u_pac = cursor.fetchone()
            if u_pac:
                cursor.execute("""
                    INSERT INTO notificaciones (id_usuario, mensaje, tipo, fecha, estado)
                    VALUES (%s, %s, 'sistema', NOW(), 'no_leido')
                """, (u_pac["id_usuario"],
                      f"⚠️ Tu cita de control del {v['fecha']} no pudo ser confirmada. "
                      f"Por favor contacta al hospital para reagendar."))

        # ── 2. Notificar a médicos con fichas pre-asignadas sin agenda, ──
        #      desde el día 3 después de creada, una vez al día.
        cursor.execute("""
            SELECT f.id_ficha, f.id_medico, f.fecha, f.notificaciones_enviadas,
                   f.fecha_preasignacion,
                   CONCAT(p.nombre,' ',p.apellido_paterno) AS paciente,
                   DATEDIFF(%s, DATE(f.fecha_preasignacion)) AS dias_transcurridos
            FROM fichas f
            JOIN estados_ficha ef ON ef.id_estado = f.id_estado
            JOIN pacientes p ON p.id_paciente = f.id_paciente
            WHERE ef.nombre = 'pre-asignada' AND f.fecha > %s
        """, (hoy, hoy))
        pendientes = cursor.fetchall()

        total_notificadas = 0
        for fp in pendientes:
            if fp["dias_transcurridos"] < 3:
                continue  # aún no llega al día 3

            # Verificar si ya existe agenda aprobada para esa fecha/medico/especialidad
            cursor.execute("""
                SELECT id_agenda FROM agenda_medico am
                JOIN fichas f2 ON f2.id_ficha = %s
                WHERE am.id_medico = f2.id_medico
                  AND am.id_especialidad = f2.id_especialidad
                  AND am.fecha = f2.fecha
                  AND am.estado = 'aprobada'
                LIMIT 1
            """, (fp["id_ficha"],))
            if cursor.fetchone():
                continue  # ya tiene agenda aprobada, no necesita más recordatorios

            numero_notif = fp["notificaciones_enviadas"] + 1

            cursor.execute("""
                SELECT u.id_usuario FROM usuarios u WHERE u.id_medico = %s LIMIT 1
            """, (fp["id_medico"],))
            u_med = cursor.fetchone()

            if u_med:
                cursor.execute("""
                    INSERT INTO notificaciones (id_usuario, mensaje, tipo, fecha, estado)
                    VALUES (%s, %s, 'recordatorio', NOW(), 'no_leido')
                """, (u_med["id_usuario"],
                      f"🔔 Tienes una ficha pre-asignada para {fp['paciente']} el "
                      f"{fp['fecha']}. Aún no has publicado agenda para ese día."))

            # A partir de la 3ra notificación, también avisar al admin
            admin_notificado = False
            if numero_notif >= 3:
                cursor.execute("""
                    SELECT u.id_usuario FROM usuarios u
                    JOIN roles r ON r.id_rol = u.id_rol
                    WHERE r.nombre = 'admin' AND u.estado = 'activo'
                """)
                admins = cursor.fetchall()
                for a in admins:
                    cursor.execute("""
                        INSERT INTO notificaciones (id_usuario, mensaje, tipo, fecha, estado)
                        VALUES (%s, %s, 'sistema', NOW(), 'no_leido')
                    """, (a["id_usuario"],
                          f"⚠️ Ficha pre-asignada sin agenda publicada (3+ recordatorios) "
                          f"para {fp['paciente']} el {fp['fecha']}. Requiere intervención."))
                admin_notificado = True

            cursor.execute("""
                INSERT INTO notificaciones_preasignada
                    (id_ficha, id_medico, numero_notificacion, admin_notificado)
                VALUES (%s, %s, %s, %s)
            """, (fp["id_ficha"], fp["id_medico"], numero_notif, admin_notificado))

            cursor.execute(
                "UPDATE fichas SET notificaciones_enviadas = %s WHERE id_ficha = %s",
                (numero_notif, fp["id_ficha"])
            )
            total_notificadas += 1

        conn.commit()
        return jsonify({
            "success":            True,
            "fichas_vencidas":    len(vencidas),
            "notificaciones_enviadas": total_notificadas
        }), 200

    except Exception as e:
        import traceback; traceback.print_exc()
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error en el job."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# JOB: VENCER AGENDAS Y CALCULAR HISTORIAL
# POST /api/medico/job/vencer-agendas
# Corre 1 vez al día. Busca agendas 'aprobada' cuya fecha pasó
# hace 24+ horas, calcula el resumen y las mueve a 'vencida'.
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/job/vencer-agendas', methods=['POST'])
def job_vencer_agendas():
    clave = request.headers.get("X-Job-Key", "")
    if clave != os.environ.get("JOB_INTERNAL_KEY", "hospital-job-2026"):
        return jsonify({"success": False, "message": "No autorizado."}), 403

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        # Agendas aprobadas cuya fecha ya pasó hace 1 día o más (24h de gracia)
        cursor.execute("""
            SELECT id_agenda, id_medico, id_especialidad, fecha, turno,
                   hora_inicio, hora_fin, cupos_solicitados, cupos_aprobados, cupos_ocupados
            FROM agenda_medico
            WHERE estado = 'aprobada' AND fecha <= DATE_SUB(CURDATE(), INTERVAL 1 DAY)
        """)
        agendas = cursor.fetchall()

        JS_DIA = ["lunes","martes","miercoles","jueves","viernes","sabado","domingo"]

        procesadas = 0
        for ag in agendas:
            # Contar fichas por estado para esa agenda
            cursor.execute("""
                SELECT ef.nombre AS estado, COUNT(*) AS total
                FROM fichas f
                JOIN estados_ficha ef ON ef.id_estado = f.id_estado
                WHERE f.id_medico = %s AND f.id_especialidad = %s AND f.fecha = %s
                GROUP BY ef.nombre
            """, (ag["id_medico"], ag["id_especialidad"], ag["fecha"]))
            conteos = {r["estado"]: r["total"] for r in cursor.fetchall()}

            atendidos    = conteos.get("completada", 0)
            no_asistio   = conteos.get("no_se_presento", 0)
            pendientes   = conteos.get("pendiente", 0) + conteos.get("en_atencion", 0)

            # Tiempo promedio por paciente según duración / cupos solicitados
            cursor.execute("SELECT TIME_TO_SEC(TIMEDIFF(%s,%s)) AS segs",
                           (ag["hora_fin"], ag["hora_inicio"]))
            segs = cursor.fetchone()["segs"] or 0
            tiempo_prom = int(segs / 60 / ag["cupos_solicitados"]) if ag["cupos_solicitados"] else None

            dia_nombre = JS_DIA[ag["fecha"].weekday()]

            # Guardar resumen (idempotente gracias a UNIQUE en id_agenda)
            cursor.execute("""
                INSERT IGNORE INTO agenda_historial_stats
                    (id_agenda, id_medico, id_especialidad, fecha, dia_semana, turno,
                     hora_inicio, hora_fin, cupos_solicitados, cupos_aprobados, cupos_ocupados,
                     pacientes_atendidos, pacientes_no_asistio, pacientes_pendientes,
                     tiempo_promedio_min)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (ag["id_agenda"], ag["id_medico"], ag["id_especialidad"], ag["fecha"],
                  dia_nombre, ag["turno"], ag["hora_inicio"], ag["hora_fin"],
                  ag["cupos_solicitados"], ag["cupos_aprobados"], ag["cupos_ocupados"],
                  atendidos, no_asistio, pendientes, tiempo_prom))

            # Cambiar agenda a vencida
            cursor.execute(
                "UPDATE agenda_medico SET estado = 'vencida' WHERE id_agenda = %s",
                (ag["id_agenda"],)
            )
            procesadas += 1

        conn.commit()
        return jsonify({"success": True, "agendas_procesadas": procesadas}), 200

    except Exception as e:
        import traceback; traceback.print_exc()
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error en el job."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# HISTORIAL DE AGENDA — LISTA
# GET /api/medico/historial-agenda
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/historial-agenda', methods=['GET'])
@requiere_token(["medico"])
def historial_agenda():
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_medico = _id_medico_desde_token(cursor)
        if not id_medico:
            return jsonify({"success": False, "message": "Perfil médico no encontrado."}), 404

        cursor.execute("""
            SELECT s.id_stat, s.id_agenda, s.fecha, s.dia_semana, s.turno,
                   s.hora_inicio, s.hora_fin, s.cupos_solicitados, s.cupos_aprobados,
                   s.cupos_ocupados, s.pacientes_atendidos, s.pacientes_no_asistio,
                   s.pacientes_pendientes, s.tiempo_promedio_min,
                   e.nombre AS especialidad
            FROM agenda_historial_stats s
            JOIN especialidades e ON e.id_especialidad = s.id_especialidad
            WHERE s.id_medico = %s
            ORDER BY s.fecha DESC
        """, (id_medico,))
        historial = cursor.fetchall()

        for h in historial:
            if h.get("fecha"):        h["fecha"]        = str(h["fecha"])
            if h.get("hora_inicio"):  h["hora_inicio"]   = str(h["hora_inicio"])[:5]
            if h.get("hora_fin"):     h["hora_fin"]      = str(h["hora_fin"])[:5]

        return jsonify({"success": True, "historial": historial}), 200

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"success": False, "message": "Error al obtener historial."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# HISTORIAL DE AGENDA — DETALLE DE PACIENTES
# GET /api/medico/historial-agenda/<id_agenda>/pacientes
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/historial-agenda/<int:id_agenda>/pacientes', methods=['GET'])
@requiere_token(["medico"])
def historial_agenda_pacientes(id_agenda):
    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        id_medico = _id_medico_desde_token(cursor)
        if not id_medico:
            return jsonify({"success": False, "message": "Perfil médico no encontrado."}), 404

        cursor.execute("""
            SELECT id_medico, id_especialidad, fecha FROM agenda_historial_stats
            WHERE id_agenda = %s AND id_medico = %s LIMIT 1
        """, (id_agenda, id_medico))
        stat = cursor.fetchone()
        if not stat:
            return jsonify({"success": False, "message": "Registro no encontrado."}), 404

        cursor.execute("""
            SELECT f.id_ficha, f.numero_turno,
                   CONCAT(p.nombre,' ',p.apellido_paterno,' ',p.apellido_materno) AS paciente,
                   p.ci, p.telefono,
                   ef.nombre AS estado
            FROM fichas f
            JOIN pacientes p ON p.id_paciente = f.id_paciente
            JOIN estados_ficha ef ON ef.id_estado = f.id_estado
            WHERE f.id_medico = %s AND f.id_especialidad = %s AND f.fecha = %s
            ORDER BY f.numero_turno ASC
        """, (stat["id_medico"], stat["id_especialidad"], stat["fecha"]))
        pacientes = cursor.fetchall()

        return jsonify({"success": True, "pacientes": pacientes}), 200

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"success": False, "message": "Error al obtener pacientes."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# JOB: LIBERAR FICHAS NO CONFIRMADAS
# POST /api/medico/job/liberar-no-confirmadas
# Corre periódicamente (ideal: cada hora). Busca fichas 'pendiente'
# cuyo plazo de confirmación (24h antes de la cita) ya venció sin
# que el paciente confirmara, las cancela y libera el cupo.
# ══════════════════════════════════════════════════════════════
@medico_bp.route('/medico/job/liberar-no-confirmadas', methods=['POST'])
def job_liberar_no_confirmadas():
    clave = request.headers.get("X-Job-Key", "")
    if clave != os.environ.get("JOB_INTERNAL_KEY", "hospital-job-2026"):
        return jsonify({"success": False, "message": "No autorizado."}), 403

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT f.id_ficha, f.id_paciente, f.id_especialidad, f.fecha
            FROM fichas f
            JOIN estados_ficha ef ON ef.id_estado = f.id_estado
            WHERE ef.nombre = 'pendiente'
              AND f.confirmada = FALSE
              AND f.fecha_limite_confirmacion IS NOT NULL
              AND f.fecha_limite_confirmacion <= NOW()
        """)
        vencidas = cursor.fetchall()

        cursor.execute("SELECT id_estado FROM estados_ficha WHERE nombre = 'cancelada' LIMIT 1")
        estado_cancelada = cursor.fetchone()

        liberadas = 0
        for v in vencidas:
            cursor.execute("UPDATE fichas SET id_estado = %s WHERE id_ficha = %s",
                           (estado_cancelada["id_estado"], v["id_ficha"]))

            cursor.execute("""
                UPDATE cupos SET cantidad_reservada = GREATEST(cantidad_reservada - 1, 0)
                WHERE id_especialidad = %s AND fecha = %s
            """, (v["id_especialidad"], v["fecha"]))
            cursor.execute("""
                UPDATE agenda_medico SET cupos_ocupados = GREATEST(cupos_ocupados - 1, 0)
                WHERE id_especialidad = %s AND fecha = %s AND estado = 'aprobada'
            """, (v["id_especialidad"], v["fecha"]))

            cursor.execute(
                "SELECT id_usuario FROM usuarios WHERE id_paciente = %s LIMIT 1",
                (v["id_paciente"],)
            )
            u_pac = cursor.fetchone()
            if u_pac:
                cursor.execute("""
                    INSERT INTO notificaciones (id_usuario, mensaje, tipo, fecha, estado)
                    VALUES (%s, %s, 'sistema', NOW(), 'no_leido')
                """, (u_pac["id_usuario"],
                      f"⚠️ Tu ficha del {v['fecha']} fue liberada por no confirmar "
                      f"tu asistencia a tiempo. Puedes reservar nuevamente si hay cupos."))
            liberadas += 1

        conn.commit()
        return jsonify({"success": True, "fichas_liberadas": liberadas}), 200

    except Exception as e:
        import traceback; traceback.print_exc()
        if conn:
            try: conn.rollback()
            except: pass
        return jsonify({"success": False, "message": "Error en el job."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()