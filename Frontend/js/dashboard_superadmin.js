
const API = "http://127.0.0.1:5000/api";

// ── Token JWT ───────────────────────────────────────────────
function getToken() {
    return sessionStorage.getItem("token") || localStorage.getItem("token") || "";
}
function authHeaders() {
    return {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${getToken()}`
    };
}

// ── Fecha en topbar ─────────────────────────────────────────
(function setFecha() {
    const opts = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
    document.getElementById("pageDate").textContent =
        new Date().toLocaleDateString('es-BO', opts);
})();

// ── Usuario logueado ────────────────────────────────────────
(function cargarUsuarioActual() {
    try {
        const raw = sessionStorage.getItem("usuario") || localStorage.getItem("usuario");
        if (!raw) return;
        const u = JSON.parse(raw);
        document.getElementById("userEmail").textContent = u.email || "superadmin";
        document.getElementById("userAvatar").textContent = (u.email || "S")[0].toUpperCase();

        // ── BLOQUEO: perfil incompleto ───────────────────────
        // Si el usuario tiene perfil_completo = false, mostramos el overlay obligatorio
        if (u.perfil_completo === false || u.perfil_completo === 0) {
            mostrarOverlayCompletarPerfil(u);
        }
    } catch (_) {}
})();

// ══════════════════════════════════════════════════════════════
// OVERLAY — COMPLETAR PERFIL (bloquea el dashboard)
// ══════════════════════════════════════════════════════════════
function mostrarOverlayCompletarPerfil(usuario) {
    // Prevenir cerrar con ESC
    document.addEventListener("keydown", function(e) {
        if (e.key === "Escape") e.preventDefault();
    });

    const overlay = document.createElement("div");
    overlay.className = "profile-lock-overlay";
    overlay.id = "profileLockOverlay";

    // Determinar si es superadmin o admin para label
    const rolLabel = (usuario.rol === "superadmin") ? "👑 SuperAdmin" : "🧑‍💼 Admin";

    overlay.innerHTML = `
    <div class="profile-lock-card">
        <div class="profile-lock-header">
            <span class="lock-icon">🔒</span>
            <h2>Completa tu perfil para continuar</h2>
            <p>Bienvenido/a. Antes de acceder al sistema debes completar tu información y cambiar tu contraseña temporal.</p>
        </div>
        <div class="profile-lock-body">
            <div class="profile-lock-steps">
                <div class="step-item">
                    <div class="step-num">1</div>
                    <div class="step-text"><strong>Datos personales</strong>CI, nombre, teléfono y dirección</div>
                </div>
                <div class="step-item">
                    <div class="step-num">2</div>
                    <div class="step-text"><strong>Nueva contraseña</strong>Cambia tu contraseña temporal</div>
                </div>
                <div class="step-item">
                    <div class="step-num">3</div>
                    <div class="step-text"><strong>Datos médicos</strong>Matrícula, especialidad, email</div>
                </div>
                <div class="step-item">
                    <div class="step-num">4</div>
                    <div class="step-text"><strong>Acceso completo</strong>Ya podrás usar el sistema</div>
                </div>
            </div>

            <!-- Paso 1: Datos personales -->
            <div id="lockStep1">
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
                    <div class="field-group">
                        <label class="field-label">CI <span class="field-required">*</span></label>
                        <input class="field-input" type="text" id="lockCI" placeholder="1234567">
                    </div>
                    <div class="field-group">
                        <label class="field-label">Teléfono <span class="field-required">*</span></label>
                        <input class="field-input" type="tel" id="lockTel" placeholder="7XXXXXXX">
                    </div>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
                    <div class="field-group">
                        <label class="field-label">Nombre <span class="field-required">*</span></label>
                        <input class="field-input" type="text" id="lockNombre" placeholder="Nombre">
                    </div>
                    <div class="field-group">
                        <label class="field-label">Apellido Paterno <span class="field-required">*</span></label>
                        <input class="field-input" type="text" id="lockApPat" placeholder="Apellido paterno">
                    </div>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
                    <div class="field-group">
                        <label class="field-label">Apellido Materno</label>
                        <input class="field-input" type="text" id="lockApMat" placeholder="Apellido materno">
                    </div>
                    <div class="field-group">
                        <label class="field-label">Fecha de nacimiento <span class="field-required">*</span></label>
                        <input class="field-input" type="date" id="lockFechaNac">
                    </div>
                </div>
                <div class="field-group">
                    <label class="field-label">Dirección <span class="field-required">*</span></label>
                    <input class="field-input" type="text" id="lockDireccion" placeholder="Av. Ejemplo 123, La Paz">
                </div>
                <div class="field-group">
                    <label class="field-label">Matrícula Profesional <span class="field-required">*</span></label>
                    <input class="field-input" type="text" id="lockMatricula" placeholder="MP-XXXXX">
                </div>
                <div class="field-group">
                    <label class="field-label">Email de contacto <span class="field-required">*</span></label>
                    <input class="field-input" type="email" id="lockEmailContacto" placeholder="contacto@gmail.com">
                    <span class="field-hint">Debe ser @gmail.com</span>
                </div>
            </div>

            <!-- Paso 2: Nueva contraseña -->
            <div id="lockStep2" style="display:none">
                <div class="field-group">
                    <label class="field-label">Nueva contraseña <span class="field-required">*</span></label>
                    <div class="input-eye-wrap">
                        <input class="field-input" type="password" id="lockNewPass"
                            placeholder="Mín. 8 caracteres"
                            oninput="medirSeguridad(this.value, 'lockBar', 'lockBarLabel')">
                        <button type="button" class="btn-eye" onclick="toggleEye('lockNewPass', this)">👁</button>
                    </div>
                    <div class="password-strength">
                        <div class="strength-bar" id="lockBar"><div class="strength-fill"></div></div>
                        <span class="strength-label" id="lockBarLabel">—</span>
                    </div>
                </div>
                <div class="field-group">
                    <label class="field-label">Confirmar contraseña <span class="field-required">*</span></label>
                    <div class="input-eye-wrap">
                        <input class="field-input" type="password" id="lockConfirmPass" placeholder="Repite la contraseña">
                        <button type="button" class="btn-eye" onclick="toggleEye('lockConfirmPass', this)">👁</button>
                    </div>
                </div>
            </div>
        </div>

        <div class="profile-lock-footer">
            <p class="profile-lock-msg" id="lockMsg"></p>
            <div style="display:flex;gap:10px;justify-content:center">
                <button class="btn-secondary" id="lockBtnBack" style="display:none" onclick="lockPaso(1)">← Anterior</button>
                <button class="btn-primary" id="lockBtnNext" onclick="lockPasoSiguiente(${usuario.id_usuario || ''})">
                    Siguiente →
                </button>
            </div>
        </div>
    </div>`;

    document.body.appendChild(overlay);
}

let _lockPasoActual = 1;

function lockPaso(n) {
    _lockPasoActual = n;
    document.getElementById("lockStep1").style.display = n === 1 ? "block" : "none";
    document.getElementById("lockStep2").style.display = n === 2 ? "block" : "none";
    document.getElementById("lockBtnBack").style.display = n === 2 ? "inline-flex" : "none";
    document.getElementById("lockBtnNext").textContent = n === 1 ? "Siguiente →" : "Guardar y Acceder";
    document.getElementById("lockMsg").textContent = "";
}

async function lockPasoSiguiente(idUsuario) {
    const msg = document.getElementById("lockMsg");

    if (_lockPasoActual === 1) {
        // ── Validar paso 1 ──
        const ci          = document.getElementById("lockCI").value.trim();
        const tel         = document.getElementById("lockTel").value.trim();
        const nombre      = document.getElementById("lockNombre").value.trim();
        const apPat       = document.getElementById("lockApPat").value.trim();
        const fechaNac    = document.getElementById("lockFechaNac").value;
        const direccion   = document.getElementById("lockDireccion").value.trim();
        const matricula   = document.getElementById("lockMatricula").value.trim();
        const emailContact= document.getElementById("lockEmailContacto").value.trim();

        if (!ci || !tel || !nombre || !apPat || !fechaNac || !direccion || !matricula || !emailContact) {
            msg.textContent = "Por favor completa todos los campos obligatorios."; return;
        }
        if (!emailContact.toLowerCase().endsWith("@gmail.com")) {
            msg.textContent = "El email de contacto debe ser @gmail.com"; return;
        }

        lockPaso(2);

    } else {
        // ── Validar paso 2 y enviar ──
        const newPass     = document.getElementById("lockNewPass").value;
        const confirmPass = document.getElementById("lockConfirmPass").value;

        if (newPass.length < 8) {
            msg.textContent = "La contraseña debe tener al menos 8 caracteres."; return;
        }
        if (newPass !== confirmPass) {
            msg.textContent = "Las contraseñas no coinciden."; return;
        }

        const btn = document.getElementById("lockBtnNext");
        btn.textContent = "Guardando...";
        btn.disabled = true;

        const payload = {
            ci:                   document.getElementById("lockCI").value.trim(),
            nombre:               document.getElementById("lockNombre").value.trim(),
            apellido_paterno:     document.getElementById("lockApPat").value.trim(),
            apellido_materno:     document.getElementById("lockApMat").value.trim(),
            telefono:             document.getElementById("lockTel").value.trim(),
            fecha_nacimiento:     document.getElementById("lockFechaNac").value,
            direccion:            document.getElementById("lockDireccion").value.trim(),
            matricula_profesional:document.getElementById("lockMatricula").value.trim(),
            email_contacto:       document.getElementById("lockEmailContacto").value.trim(),
            nueva_password:       newPass
        };

        try {
            const res  = await fetch(`${API}/completar_perfil/${idUsuario}`, {
                method: "POST",
                headers: authHeaders(),
                body: JSON.stringify(payload)
            });
            const data = await res.json();

            if (data.success) {
                // Actualizar perfil_completo en storage
                try {
                    const raw = sessionStorage.getItem("usuario") || localStorage.getItem("usuario");
                    if (raw) {
                        const u = JSON.parse(raw);
                        u.perfil_completo = true;
                        const dest = sessionStorage.getItem("usuario") ? "session" : "local";
                        if (dest === "session") sessionStorage.setItem("usuario", JSON.stringify(u));
                        else localStorage.setItem("usuario", JSON.stringify(u));
                    }
                } catch(_) {}

                // Eliminar overlay
                const overlay = document.getElementById("profileLockOverlay");
                if (overlay) overlay.remove();

                toast("✓ Perfil completado. ¡Bienvenido/a al sistema!", "ok");
                cargarDashboard();
            } else {
                msg.textContent = data.message || "Error al guardar. Intenta nuevamente.";
                btn.textContent = "Guardar y Acceder";
                btn.disabled = false;
            }
        } catch (_) {
            msg.textContent = "Error de conexión con el servidor.";
            btn.textContent = "Guardar y Acceder";
            btn.disabled = false;
        }
    }
}

// ══════════════════════════════════════════════════════════════
// UTILIDADES UI
// ══════════════════════════════════════════════════════════════
function toast(msg, tipo = "ok") {
    const t = document.getElementById("toast");
    t.textContent = msg;
    t.className = `toast toast-${tipo} show`;
    setTimeout(() => { t.className = "toast"; }, 3500);
}

function abrirModal(id) {
    document.getElementById(id).classList.add("open");
}

function cerrarModal(id) {
    document.getElementById(id).classList.remove("open");
}

// Mostrar/ocultar contraseña
function toggleEye(inputId, btn) {
    const input = document.getElementById(inputId);
    if (input.type === "password") {
        input.type = "text";
        btn.textContent = "🙈";
    } else {
        input.type = "password";
        btn.textContent = "👁";
    }
}

// ── Barra de seguridad de contraseña ──────────────────────
function medirSeguridad(pass, barId, labelId) {
    const fill  = document.querySelector(`#${barId} .strength-fill`);
    const label = document.getElementById(labelId);

    let score = 0;
    if (pass.length >= 8)                          score++;
    if (/[A-Z]/.test(pass) && /[a-z]/.test(pass)) score++;
    if (/[0-9]/.test(pass))                        score++;
    if (/[^A-Za-z0-9]/.test(pass))                score++;

    const niveles = [
        { clase: "",       texto: "—",          labelCls: "" },
        { clase: "level-1", texto: "Débil",     labelCls: "l1" },
        { clase: "level-2", texto: "Media",     labelCls: "l2" },
        { clase: "level-3", texto: "Fuerte",    labelCls: "l3" },
        { clase: "level-4", texto: "Muy fuerte",labelCls: "l4" }
    ];

    const nivel = pass.length === 0 ? niveles[0] : niveles[score] || niveles[4];

    fill.className  = `strength-fill ${nivel.clase}`;
    label.textContent = nivel.texto;
    label.className = `strength-label ${nivel.labelCls}`;
}

// ── Cerrar sesión ──────────────────────────────────────────
function cerrarSesion() {
    sessionStorage.clear();
    localStorage.removeItem("token");
    localStorage.removeItem("usuario");
    window.location.href = "/Frontend/pages/login.html";
}

// ── Toggle sidebar ─────────────────────────────────────────
function toggleSidebar() {
    const sb   = document.getElementById("sidebar");
    const main = document.getElementById("mainContent");
    if (window.innerWidth <= 768) {
        sb.classList.toggle("open");
    } else {
        sb.classList.toggle("collapsed");
        main.classList.toggle("expanded");
    }
}

// ── Fecha topbar ───────────────────────────────────────────
function formatFecha(str) {
    if (!str) return "—";
    const d = new Date(str);
    return isNaN(d) ? str : d.toLocaleString('es-BO', { dateStyle: 'short', timeStyle: 'short' });
}

function actualizarBadge(id, n) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = n;
    el.classList.toggle("show", n > 0);
}

function filtrarTabla(input, tablaId) {
    const filtro = input.value.toLowerCase();
    document.querySelectorAll(`#${tablaId} tbody tr`).forEach(fila => {
        fila.style.display = fila.textContent.toLowerCase().includes(filtro) ? "" : "none";
    });
}

function clasificarEvento(accion = "") {
    const a = accion.toUpperCase();
    if (a.includes("LOGIN_OK"))                        return { clase: "badge-ok",    label: "Login OK" };
    if (a.includes("BLOQUEADO"))                       return { clase: "badge-block",  label: "Bloqueado" };
    if (a.includes("INTENTO") || a.includes("FAIL"))   return { clase: "badge-fail",   label: "Fallo" };
    return { clase: "badge-ok", label: accion };
}

// ── Modal de confirmación genérico ─────────────────────────
function confirmar(titulo, mensaje, claseBtn, callback) {
    document.getElementById("confirmTitle").textContent = titulo;
    document.getElementById("confirmMsg").textContent   = mensaje;
    const btn = document.getElementById("confirmBtn");
    btn.className = `btn-primary ${claseBtn}`;
    btn.onclick = () => { cerrarModal("modalConfirm"); callback(); };
    abrirModal("modalConfirm");
}

// ── Animación de número ────────────────────────────────────
function animarNumero(id, fin) {
    const el = document.getElementById(id);
    if (!el) return;
    let actual = 0;
    const paso = Math.ceil(fin / 40) || 1;
    const iv = setInterval(() => {
        actual = Math.min(actual + paso, fin);
        el.textContent = actual.toLocaleString('es-BO');
        if (actual >= fin) clearInterval(iv);
    }, 30);
}

// ══════════════════════════════════════════════════════════════
// NAVEGACIÓN
// ══════════════════════════════════════════════════════════════
const TITULOS = {
    dashboard:    "Panel de Control",
    superadmins:  "Gestión de SuperAdmins",
    admins:       "Gestión de Admins",
    medicos:      "Control de Médicos",
    solicitudes:  "Solicitudes de Recuperación",
    bloqueados:   "Usuarios Bloqueados",
    auditoria:    "Auditoría del Sistema"
};

function mostrarSeccion(id, el) {
    document.querySelectorAll(".section").forEach(s => s.classList.remove("active"));
    document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
    document.getElementById(`sec-${id}`).classList.add("active");
    if (el) el.classList.add("active");
    document.getElementById("pageTitle").textContent = TITULOS[id] || id;

    const loaders = {
        dashboard:   cargarDashboard,
        superadmins: cargarSuperAdmins,
        admins:      cargarAdmins,
        medicos:     cargarMedicos,
        solicitudes: cargarSolicitudes,
        bloqueados:  cargarBloqueados,
        auditoria:   cargarAuditoria
    };
    if (loaders[id]) loaders[id]();
}

// ══════════════════════════════════════════════════════════════
// 1. DASHBOARD
// ══════════════════════════════════════════════════════════════
async function cargarDashboard() {
    try {
        const res  = await fetch(`${API}/stats`, { headers: authHeaders() });
        const data = await res.json();
        animarNumero("totalUsuarios",  data.total_usuarios  || 0);
        animarNumero("totalMedicos",   data.total_medicos   || 0);
        animarNumero("totalPacientes", data.total_pacientes || 0);
        animarNumero("totalFichas",    data.fichas_hoy      || 0);
    } catch (_) {
        ["totalUsuarios","totalMedicos","totalPacientes","totalFichas"]
            .forEach(id => { const el = document.getElementById(id); if(el) el.textContent = "—"; });
    }
    cargarActividadReciente();
    cargarBloqueadosResumen();
}

async function cargarActividadReciente() {
    const ul = document.getElementById("actividadReciente");
    try {
        const res  = await fetch(`${API}/auditoria?limit=5`, { headers: authHeaders() });
        const data = await res.json();
        const logs = data.logs || data || [];
        ul.innerHTML = logs.length ? logs.map(log => {
            const tipo  = clasificarEvento(log.accion);
            return `<li class="activity-item">
                <span class="activity-badge ${tipo.clase}">${tipo.label}</span>
                <span style="flex:1;font-size:0.82rem">${log.email || log.id_usuario}</span>
                <span style="font-size:0.75rem;color:var(--text-muted)">${formatFecha(log.fecha)}</span>
            </li>`;
        }).join("") : `<li class="activity-item" style="color:var(--text-muted)">Sin actividad reciente</li>`;
    } catch (_) {
        ul.innerHTML = `<li class="activity-item" style="color:var(--text-muted)">No disponible</li>`;
    }
}

async function cargarBloqueadosResumen() {
    const ul = document.getElementById("bloqueadosResumen");
    try {
        const res   = await fetch(`${API}/bloqueados`, { headers: authHeaders() });
        const data  = await res.json();
        const lista = data.usuarios || data || [];
        actualizarBadge("badgeBloqueados", lista.length);
        ul.innerHTML = lista.length ? lista.slice(0,3).map(u => `
            <li class="activity-item">
                <span>⚠️</span>
                <span style="flex:1;font-size:0.82rem">${u.email}</span>
                <button class="btn-sm btn-warning" onclick="desbloquearUsuario(${u.id_usuario},'${u.email}')">Desbloquear</button>
            </li>`).join("") :
            `<li class="activity-item" style="color:var(--text-muted)">Sin cuentas bloqueadas 🎉</li>`;
    } catch (_) {
        ul.innerHTML = `<li class="activity-item" style="color:var(--text-muted)">No disponible</li>`;
    }
}

// ══════════════════════════════════════════════════════════════
// FUNCIÓN GENÉRICA CREAR USUARIO (SuperAdmin o Admin)
// ══════════════════════════════════════════════════════════════
async function crearUsuario(rol, emailInputId, passInputId, msgId, modalId, recargarFn) {
    const email    = document.getElementById(emailInputId).value.trim();
    const password = document.getElementById(passInputId).value.trim();
    const msg      = document.getElementById(msgId);

    // Validaciones
    if (!email || !password) {
        msg.textContent = "Completa todos los campos obligatorios."; return;
    }
    if (!email.toLowerCase().endsWith("@gmail.com")) {
        msg.textContent = "El correo debe ser una dirección @gmail.com"; return;
    }
    if (password.length < 8) {
        msg.textContent = "La contraseña temporal debe tener al menos 8 caracteres."; return;
    }
    if (!/[A-Z]/.test(password)) {
        msg.textContent = "La contraseña debe incluir al menos una mayúscula."; return;
    }

    msg.textContent = "";

    try {
        const endpoint = rol === "superadmin" ? `${API}/crear_superadmin` : `${API}/crear_admin`;
        const res = await fetch(endpoint, {
            method: "POST",
            headers: authHeaders(),
            body: JSON.stringify({ email, password, rol })
        });
        const data = await res.json();

        if (res.ok && data.success) {
            cerrarModal(modalId);
            // Limpiar campos
            document.getElementById(emailInputId).value = "";
            document.getElementById(passInputId).value  = "";
            toast(`✓ ${rol === "superadmin" ? "SuperAdmin" : "Admin"} creado correctamente`, "ok");
            recargarFn();
        } else {
            msg.textContent = data.message || `Error al crear ${rol}.`;
        }
    } catch (_) {
        msg.textContent = "Error de conexión con el servidor.";
    }
}

// ══════════════════════════════════════════════════════════════
// 2. SUPERADMINS
// ══════════════════════════════════════════════════════════════
async function cargarSuperAdmins() {
    const tbody = document.getElementById("bodySuperAdmins");
    tbody.innerHTML = `<tr><td colspan="5" class="table-loading">Cargando...</td></tr>`;
    try {
        
        const res   = await fetch(`${API}/superadmins`, { headers: authHeaders() });
        const data  = await res.json();
        const lista = data.superadmins || data || [];

        tbody.innerHTML = lista.length ? lista.map(u => `
            <tr>
                <td>${u.email}</td>
                <td><span class="estado-badge estado-${u.estado}">${u.estado}</span></td>
                <td>
                    <span class="estado-badge ${u.perfil_completo ? 'estado-completo' : 'estado-pendiente'}">
                        ${u.perfil_completo ? 'Completo' : 'Pendiente'}
                    </span>
                </td>
                <td>${formatFecha(u.fecha_registro)}</td>
                <td class="td-actions">
                    <button class="btn-sm btn-${u.estado === 'activo' ? 'warning' : 'success'}"
                        onclick="toggleEstadoUsuario(${u.id_usuario}, '${u.estado}', '${u.email}', 'superadmin')">
                        ${u.estado === 'activo' ? 'Desactivar' : 'Activar'}
                    </button>
                    <button class="btn-sm btn-danger"
                        onclick="eliminarUsuario(${u.id_usuario}, '${u.email}', 'superadmin')">
                        Eliminar
                    </button>
                </td>
            </tr>`).join("") :
            `<tr><td colspan="5" class="table-loading">No hay superadmins registrados</td></tr>`;
    } catch (_) {
        tbody.innerHTML = `<tr><td colspan="5" class="table-loading">Error al cargar</td></tr>`;
    }
}

// ══════════════════════════════════════════════════════════════
// 3. ADMINS
// ══════════════════════════════════════════════════════════════
async function cargarAdmins() {
    const tbody = document.getElementById("bodyAdmins");
    tbody.innerHTML = `<tr><td colspan="5" class="table-loading">Cargando...</td></tr>`;
    try {
        const res   = await fetch(`${API}/admins`, { headers: authHeaders() });
        const data  = await res.json();
        const lista = data.admins || data || [];

        tbody.innerHTML = lista.length ? lista.map(a => `
            <tr>
                <td>${a.email}</td>
                <td><span class="estado-badge estado-${a.estado}">${a.estado}</span></td>
                <td>
                    <span class="estado-badge ${a.perfil_completo ? 'estado-completo' : 'estado-pendiente'}">
                        ${a.perfil_completo ? 'Completo' : 'Pendiente'}
                    </span>
                </td>
                <td>${formatFecha(a.fecha_registro)}</td>
                <td class="td-actions">
                    <button class="btn-sm btn-${a.estado === 'activo' ? 'warning' : 'success'}"
                        onclick="toggleEstadoUsuario(${a.id_usuario}, '${a.estado}', '${a.email}', 'admin')">
                        ${a.estado === 'activo' ? 'Desactivar' : 'Activar'}
                    </button>
                    <button class="btn-sm btn-danger"
                        onclick="eliminarUsuario(${a.id_usuario}, '${a.email}', 'admin')">
                        Eliminar
                    </button>
                </td>
            </tr>`).join("") :
            `<tr><td colspan="5" class="table-loading">No hay admins registrados</td></tr>`;
    } catch (_) {
        tbody.innerHTML = `<tr><td colspan="5" class="table-loading">Error al cargar</td></tr>`;
    }
}

// ── Activar / Desactivar usuario (SA o Admin) ──────────────
async function toggleEstadoUsuario(id, estadoActual, email, rol) {
    const nuevoEstado = estadoActual === "activo" ? "inactivo" : "activo";
    const accion = nuevoEstado === "activo" ? "Activar" : "Desactivar";

    confirmar(
        `${accion} ${rol === "superadmin" ? "SuperAdmin" : "Admin"}`,
        `¿Seguro que deseas ${accion.toLowerCase()} la cuenta de ${email}?`,
        nuevoEstado === "activo" ? "" : "btn-danger",
        async () => {
            try {
                const endpoint = rol === "superadmin"
                    ? `${API}/superadmin/${id}/estado`
                    : `${API}/admin/${id}/estado`;
                const res  = await fetch(endpoint, {
                    method: "PUT",
                    headers: authHeaders(),
                    body: JSON.stringify({ estado: nuevoEstado })
                });
                const data = await res.json();
                if (data.success) {
                    toast(`${email} ${nuevoEstado === 'activo' ? 'activado' : 'desactivado'} ✓`,
                        nuevoEstado === 'activo' ? "ok" : "warning");
                    rol === "superadmin" ? cargarSuperAdmins() : cargarAdmins();
                } else {
                    toast(data.message || "Error al cambiar estado", "error");
                }
            } catch (_) { toast("Error de conexión", "error"); }
        }
    );
}

// ── Eliminar usuario ────────────────────────────────────────
async function eliminarUsuario(id, email, rol) {
    confirmar(
        "Eliminar cuenta",
        `¿Eliminar permanentemente la cuenta de ${email}? Esta acción no se puede deshacer.`,
        "btn-danger",
        async () => {
            try {
                const endpoint = rol === "superadmin"
                    ? `${API}/superadmin/${id}`
                    : `${API}/admin/${id}`;
                const res  = await fetch(endpoint, { method: "DELETE", headers: authHeaders() });
                const data = await res.json();
                if (data.success) {
                    toast(`Cuenta de ${email} eliminada`, "warning");
                    rol === "superadmin" ? cargarSuperAdmins() : cargarAdmins();
                } else {
                    toast(data.message || "Error", "error");
                }
            } catch (_) { toast("Error de conexión", "error"); }
        }
    );
}

// ══════════════════════════════════════════════════════════════
// 4. MÉDICOS
// ══════════════════════════════════════════════════════════════
async function cargarMedicos() {
    const tbody = document.getElementById("bodyMedicos");
    tbody.innerHTML = `<tr><td colspan="5" class="table-loading">Cargando...</td></tr>`;
    try {
        const res   = await fetch(`${API}/medicos`, { headers: authHeaders() });
        const data  = await res.json();
        const lista = data.medicos || data || [];

        tbody.innerHTML = lista.length ? lista.map(m => `
            <tr>
                <td>${m.nombre || m.email}</td>
                <td>${m.especialidad || '—'}</td>
                <td>
                    <span class="estado-badge ${m.perfil_completo ? 'estado-completo' : 'estado-pendiente'}">
                        ${m.perfil_completo ? 'Completo' : 'Pendiente'}
                    </span>
                </td>
                <td><span class="estado-badge estado-${m.estado}">${m.estado}</span></td>
                <td class="td-actions">
                    <button class="btn-sm btn-${m.estado === 'activo' ? 'warning' : 'success'}"
                        onclick="toggleEstadoMedico(${m.id_usuario || m.id}, '${m.estado}')">
                        ${m.estado === 'activo' ? 'Desactivar' : 'Activar'}
                    </button>
                </td>
            </tr>`).join("") :
            `<tr><td colspan="5" class="table-loading">No hay médicos registrados</td></tr>`;
    } catch (_) {
        tbody.innerHTML = `<tr><td colspan="5" class="table-loading">Error al cargar</td></tr>`;
    }
}

async function toggleEstadoMedico(id, estadoActual) {
    const nuevoEstado = estadoActual === "activo" ? "inactivo" : "activo";
    try {
        const res  = await fetch(`${API}/medico/${id}/estado`, {
            method: "PUT",
            headers: authHeaders(),
            body: JSON.stringify({ estado: nuevoEstado })
        });
        const data = await res.json();
        if (data.success) {
            toast(`Médico ${nuevoEstado} ✓`, nuevoEstado === 'activo' ? "ok" : "warning");
            cargarMedicos();
        } else { toast(data.message || "Error", "error"); }
    } catch (_) { toast("Error de conexión", "error"); }
}

// ══════════════════════════════════════════════════════════════
// 5. SOLICITUDES
// ══════════════════════════════════════════════════════════════
async function cargarSolicitudes() {
    const tbody = document.getElementById("bodySolicitudes");
    tbody.innerHTML = `<tr><td colspan="4" class="table-loading">Cargando...</td></tr>`;
    try {
        const res   = await fetch(`${API}/solicitudes`, { headers: authHeaders() });
        const data  = await res.json();
        const lista = data.solicitudes || data || [];

        const pendientes = lista.filter(s => s.estado === "pendiente").length;
        actualizarBadge("badgeSolicitudes", pendientes);

        tbody.innerHTML = lista.length ? lista.map(s => `
            <tr>
                <td>${s.email}</td>
                <td>${formatFecha(s.fecha)}</td>
                <td><span class="estado-badge estado-${s.estado}">${s.estado}</span></td>
                <td class="td-actions">
                    ${s.estado === 'pendiente' ? `
                    <button class="btn-sm btn-success" onclick="responderSolicitud(${s.id}, 'aprobada')">Aprobar</button>
                    <button class="btn-sm btn-danger"  onclick="responderSolicitud(${s.id}, 'rechazada')">Rechazar</button>
                    ` : '—'}
                </td>
            </tr>`).join("") :
            `<tr><td colspan="4" class="table-loading">Sin solicitudes pendientes</td></tr>`;
    } catch (_) {
        tbody.innerHTML = `<tr><td colspan="4" class="table-loading">Error al cargar</td></tr>`;
    }
}

async function responderSolicitud(id, decision) {
    try {
        const res  = await fetch(`${API}/solicitud/${id}`, {
            method: "PUT",
            headers: authHeaders(),
            body: JSON.stringify({ estado: decision })
        });
        const data = await res.json();
        if (data.success) {
            toast(`Solicitud ${decision} ✓`, decision === 'aprobada' ? "ok" : "warning");
            cargarSolicitudes();
        } else { toast(data.message || "Error", "error"); }
    } catch (_) { toast("Error de conexión", "error"); }
}

// ══════════════════════════════════════════════════════════════
// 6. BLOQUEADOS
// ══════════════════════════════════════════════════════════════
async function cargarBloqueados() {
    const tbody = document.getElementById("tablaBloqueados");
    tbody.innerHTML = `<tr><td colspan="4" class="table-loading">Cargando...</td></tr>`;
    try {
        const res   = await fetch(`${API}/bloqueados`, { headers: authHeaders() });
        const data  = await res.json();
        const lista = data.usuarios || data || [];
        actualizarBadge("badgeBloqueados", lista.length);

        tbody.innerHTML = lista.length ? lista.map(u => `
            <tr>
                <td>${u.email}</td>
                <td>${u.intentos_fallidos || 0}</td>
                <td>${formatFecha(u.fecha_bloqueo)}</td>
                <td>
                    <button class="btn-sm btn-success"
                        onclick="desbloquearUsuario(${u.id_usuario}, '${u.email}')">Desbloquear</button>
                </td>
            </tr>`).join("") :
            `<tr><td colspan="4" class="table-loading">Sin usuarios bloqueados 🎉</td></tr>`;
    } catch (_) {
        tbody.innerHTML = `<tr><td colspan="4" class="table-loading">Error al cargar</td></tr>`;
    }
}

async function desbloquearUsuario(id, email) {
    confirmar(
        "Desbloquear cuenta",
        `¿Desbloquear la cuenta de ${email}?`,
        "",
        async () => {
            try {
                const res  = await fetch(`${API}/desbloquear/${id}`, {
                    method: "PUT", headers: authHeaders()
                });
                const data = await res.json();
                if (data.success) {
                    toast(`Cuenta de ${email} desbloqueada ✓`, "ok");
                    cargarBloqueados();
                    cargarBloqueadosResumen();
                } else { toast(data.message || "Error", "error"); }
            } catch (_) { toast("Error de conexión", "error"); }
        }
    );
}

// ══════════════════════════════════════════════════════════════
// 7. AUDITORÍA
// ══════════════════════════════════════════════════════════════
async function cargarAuditoria() {
    const tbody = document.getElementById("bodyAuditoria");
    tbody.innerHTML = `<tr><td colspan="3" class="table-loading">Cargando...</td></tr>`;
    try {
        const res  = await fetch(`${API}/auditoria`, { headers: authHeaders() });
        const data = await res.json();
        const logs = data.logs || data || [];

        tbody.innerHTML = logs.length ? logs.map(log => {
            const tipo = clasificarEvento(log.accion);
            return `<tr>
                <td>${log.email || log.id_usuario}</td>
                <td><span class="activity-badge ${tipo.clase}">${log.accion}</span></td>
                <td>${formatFecha(log.fecha)}</td>
            </tr>`;
        }).join("") :
        `<tr><td colspan="3" class="table-loading">Sin registros</td></tr>`;
    } catch (_) {
        tbody.innerHTML = `<tr><td colspan="3" class="table-loading">Error al cargar</td></tr>`;
    }
}

// ══════════════════════════════════════════════════════════════
// INIT
// ══════════════════════════════════════════════════════════════
cargarDashboard();
