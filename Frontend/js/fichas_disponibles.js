const API = "http://127.0.0.1:5000/api";

// Íconos por especialidad
const ICONOS = {
    "cardiología":       "❤️",
    "neurología":        "🧠",
    "pediatría":         "👶",
    "ginecología":       "👩",
    "traumatología":     "🦴",
    "medicina interna":  "🩺",
    "oftalmología":      "👁️",
    "dermatología":      "🧴",   // ← corregido (antes era 🫁)
    "oncología":         "🔬",
    "default":           "🏥"
};

function getIcono(nombre) {
    const key = nombre.toLowerCase();
    for (const k in ICONOS) { if (key.includes(k)) return ICONOS[k]; }
    return ICONOS.default;
}

// ── Estado global ────────────────────────────────────────────
let especialidades   = [];
let espSeleccionada  = null;
let cupoSeleccionado = null;
let _cuposCache      = [];   // cache para evitar JSON en onclick

// ── PASO 1: Cargar especialidades ────────────────────────────
async function cargarEspecialidades() {
    try {
        const res  = await fetch(`${API}/especialidades_disponibles`);
        const data = await res.json();
        especialidades = data.especialidades || data || [];
        renderEspecialidades(especialidades);
    } catch (e) {
        console.error("[ESP]", e);
        document.getElementById("espGrid").innerHTML =
            `<p style="color:rgba(255,255,255,0.5);grid-column:1/-1">
                No se pudo conectar con el servidor.
             </p>`;
    }
}

function renderEspecialidades(lista) {
    const grid = document.getElementById("espGrid");
    if (!lista.length) {
        grid.innerHTML = `<p style="color:rgba(255,255,255,0.5);grid-column:1/-1">
            No hay especialidades disponibles por el momento.</p>`;
        return;
    }
    grid.innerHTML = lista.map((esp, i) => `
        <div class="esp-card" style="animation-delay:${i * 0.05}s"
             onclick="seleccionarEspecialidad(${esp.id_especialidad}, '${esc(esp.nombre)}', '${esc(esp.descripcion)}')">
            <div class="esp-card-icon">${getIcono(esp.nombre)}</div>
            <div class="esp-card-name">${esp.nombre}</div>
            <div class="esp-card-desc">${esp.descripcion}</div>
        </div>`).join("");
}

function filtrarEspecialidades(texto) {
    const filtro   = texto.toLowerCase();
    const filtradas = especialidades.filter(e =>
        e.nombre.toLowerCase().includes(filtro) ||
        e.descripcion.toLowerCase().includes(filtro)
    );
    renderEspecialidades(filtradas);
}

// ── Seleccionar especialidad → ir paso 2 ─────────────────────
async function seleccionarEspecialidad(id, nombre, desc) {
    espSeleccionada = { id, nombre, desc };

    document.getElementById("tituloEsp").innerHTML =
        `Fechas disponibles — <span class="accent">${nombre}</span>`;

    document.getElementById("step1").classList.remove("active");
    document.getElementById("step2").classList.add("active");

    document.getElementById("cupoDetalle").hidden = true;
    cupoSeleccionado = null;

    await cargarFechas(id);
}

function volverPaso1() {
    document.getElementById("step2").classList.remove("active");
    document.getElementById("step1").classList.add("active");
    espSeleccionada  = null;
    cupoSeleccionado = null;
}

// ── PASO 2: Cargar fechas/cupos ──────────────────────────────
async function cargarFechas(idEsp) {
    const grid = document.getElementById("fechasGrid");
    grid.innerHTML = `
        <div class="fecha-skeleton"></div>
        <div class="fecha-skeleton"></div>
        <div class="fecha-skeleton"></div>`;

    try {
        const res   = await fetch(`${API}/cupos_disponibles/${idEsp}`);
        const data  = await res.json();
        const cupos = data.cupos || data || [];
        _cuposCache = cupos;   // guardar en cache
        renderFechas(cupos);
    } catch (e) {
        grid.innerHTML = `<p style="color:rgba(255,255,255,0.5)">
            Error al cargar fechas disponibles.</p>`;
    }
}

function renderFechas(cupos) {
    const grid = document.getElementById("fechasGrid");
    if (!cupos.length) {
        grid.innerHTML = `<p style="color:rgba(255,255,255,0.5);grid-column:1/-1">
            No hay fechas disponibles para esta especialidad.</p>`;
        return;
    }

    grid.innerHTML = cupos.map((c, i) => {
        const fecha   = new Date(c.fecha + "T00:00:00");
        const dia     = fecha.getDate();
        const mes     = fecha.toLocaleDateString('es-BO', { month: 'short' });
        const diaSem  = fecha.toLocaleDateString('es-BO', { weekday: 'short' });
        const libres  = c.cantidad_maxima - c.cantidad_reservada;
        const agotada = libres <= 0;
        const claseC  = libres === 0 ? "cupos-nada" : libres <= 3 ? "cupos-poco" : "cupos-ok";
        const textoC  = agotada ? "Agotado" : `${libres} cupo${libres !== 1 ? "s" : ""}`;

        // ✅ Se usa índice en lugar de JSON.stringify en el onclick
        return `
        <div class="fecha-card ${agotada ? "fecha-agotada" : ""}"
             style="animation-delay:${i * 0.06}s"
             onclick="${agotada ? "" : `seleccionarFecha(${i}, event)`}">
            <div class="fecha-dia">${dia}</div>
            <div class="fecha-mes">${diaSem} · ${mes}</div>
            <span class="fecha-cupos ${claseC}">${textoC}</span>
        </div>`;
    }).join("");
}

// ── Seleccionar fecha → mostrar detalle ──────────────────────
async function seleccionarFecha(index, e) {
    const cupo = _cuposCache[index];   // ✅ se obtiene del cache
    cupoSeleccionado = cupo;

    // Marcar seleccionada
    document.querySelectorAll(".fecha-card").forEach(c => c.classList.remove("selected"));
    e.currentTarget.classList.add("selected");   // ✅ sin 'event' global

    // Mostrar "cargando médico" mientras se obtiene
    document.getElementById("detalleMedico").textContent = "Cargando...";

    let medico = "Por asignar";
    try {
        const res  = await fetch(`${API}/medico_especialidad/${cupo.id_especialidad}`);
        const data = await res.json();
        if (data.medico) {
            medico = `Dr. ${data.medico.nombre} ${data.medico.apellido_paterno}`;
        }
    } catch (_) {}

    const libres = cupo.cantidad_maxima - cupo.cantidad_reservada;
    const turno  = cupo.cantidad_reservada + 1;
    const fecha  = new Date(cupo.fecha + "T00:00:00")
        .toLocaleDateString('es-BO', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });

    document.getElementById("detalleFecha").textContent  = fecha;
    document.getElementById("detalleEsp").textContent    = espSeleccionada.nombre;
    document.getElementById("detalleMedico").textContent = medico;
    document.getElementById("detalleCupos").textContent  = `${libres} disponible${libres !== 1 ? "s" : ""}`;
    document.getElementById("detalleTurno").textContent  = `N° ${turno}`;

    cupoSeleccionado._medico = medico;
    cupoSeleccionado._turno  = turno;
    cupoSeleccionado._fecha  = fecha;

    document.getElementById("cupoDetalle").hidden = false;
    document.getElementById("cupoDetalle").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// ── Modal reserva ────────────────────────────────────────────
let _credencialesNuevas = null;
let _credActuales = null;

function abrirModalReserva() {
    if (!cupoSeleccionado) return;
    document.getElementById("formReserva").reset();
    limpiarMsg();
    limpiarErrores();

    document.getElementById("resumenEsp").textContent   = espSeleccionada.nombre;
    document.getElementById("resumenFecha").textContent = cupoSeleccionado._fecha;
    document.getElementById("resumenTurno").textContent = cupoSeleccionado._turno;

    document.getElementById("modalReserva").classList.add("open");
}

function cerrarModal() {
    document.getElementById("modalReserva").classList.remove("open");
}

document.getElementById("modalReserva").addEventListener("click", function(e) {
    if (e.target === this) cerrarModal();
});

// ── Validación ───────────────────────────────────────────────

// Lista de palabras obscenas a bloquear en nombre/apellidos
const PALABRAS_OBSCENAS = [
    "puta","puto","mierda","cojudo","idiota","imbecil","imbécil",
    "pendejo","culero","cabrón","cabron","hdp","concha","carajo",
    "joder","marica","maricón","maricon","weon","huevon","huevón",
    "coño","cono","chinga","chingada","perra","perro","bastardo",
    "mamona","mamón","mamon","zorra","zorro","estupido","estúpido"
];

function contieneObscenidad(texto) {
    const t = texto.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    return PALABRAS_OBSCENAS.some(p => {
        const norm = p.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
        return t.includes(norm);
    });
}

const REGLAS = {
    res_ci:         { regex: /^\d{6,9}$/,                             msg: "CI inválido (6 a 9 dígitos)" },
    res_telefono:   { regex: /^[67]\d{7}$/,                           msg: "Teléfono inválido (8 dígitos, debe empezar en 6 o 7)" },
    res_nombre:     { regex: /^[a-zA-ZáéíóúÁÉÍÓÚüÜñÑ\s]{2,}$/,      msg: "Nombre inválido (solo letras)" },
    res_ap_paterno: { regex: /^[a-zA-ZáéíóúÁÉÍÓÚüÜñÑ\s]{2,}$/,      msg: "Apellido paterno inválido (solo letras)" },
    res_ap_materno: { regex: /^[a-zA-ZáéíóúÁÉÍÓÚüÜñÑ\s]{2,}$/,      msg: "Apellido materno inválido (solo letras)" },
};

// Campos de nombre/apellido donde se filtra obscenidad
const CAMPOS_NOMBRE = ["res_nombre", "res_ap_paterno", "res_ap_materno"];

function validarCampos(valores) {
    limpiarErrores();
    let valido = true;
    let primerError = null;

    for (const [id, { regex, msg }] of Object.entries(REGLAS)) {
        const input = document.getElementById(id);
        if (!regex.test(valores[id])) {
            input.style.borderColor = "#e74c3c";
            if (!primerError) primerError = msg;
            valido = false;
        }
    }

    // Validar obscenidades en nombre y apellidos
    for (const id of CAMPOS_NOMBRE) {
        const input = document.getElementById(id);
        if (contieneObscenidad(valores[id])) {
            input.style.borderColor = "#e74c3c";
            if (!primerError) primerError = "El nombre o apellido contiene palabras no permitidas.";
            valido = false;
        }
    }

    if (!valido && primerError) mostrarMsg(primerError, "error");
    return valido;
}

function limpiarErrores() {
    Object.keys(REGLAS).forEach(id => {
        document.getElementById(id).style.borderColor = "";
    });
}

// ── Confirmar reserva ────────────────────────────────────────
async function confirmarReserva(e) {
    e.preventDefault();
    limpiarMsg();

    const valores = {
        res_ci:         document.getElementById("res_ci").value.trim(),
        res_telefono:   document.getElementById("res_telefono").value.trim(),
        res_nombre:     document.getElementById("res_nombre").value.trim(),
        res_ap_paterno: document.getElementById("res_ap_paterno").value.trim(),
        res_ap_materno: document.getElementById("res_ap_materno").value.trim(),
    };

    // ✅ Validación con resaltado en rojo
    if (!validarCampos(valores)) return;

    const btn = document.getElementById("btnConfirmar");
    btn.disabled = true;
    btn.querySelector(".btn-text").textContent = "Reservando...";

    try {
        const res = await fetch(`${API}/reservar_ficha_sin_cuenta`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                ci:               valores.res_ci,
                nombre:           valores.res_nombre,
                apellido_paterno: valores.res_ap_paterno,
                apellido_materno: valores.res_ap_materno,
                telefono:         valores.res_telefono,
                id_especialidad:  espSeleccionada.id,
                id_cupo:          cupoSeleccionado.id_cupo,
                fecha:            cupoSeleccionado.fecha
            })
        });

        const data = await res.json();

        if (res.ok && data.success) {
            cerrarModal();
            _credencialesNuevas = data.credenciales_nuevas || null;
            mostrarExito(data);
        } else {
            mostrarMsg(data.message || "Error al reservar. Intenta nuevamente.", "error");
        }

    } catch (err) {
        console.error("[RESERVA]", err);
        mostrarMsg("Error de conexión con el servidor.", "error");
    } finally {
        btn.disabled = false;
        btn.querySelector(".btn-text").textContent = "Confirmar reserva";
    }
}

// ── Modal éxito ──────────────────────────────────────────────
function mostrarExito(data) {
    const turno       = data.numero_turno || cupoSeleccionado._turno;
    const horaEst     = data.hora_estimada || null;
    const promedio    = data.tiempo_promedio || null;
    const fechaLarga  = cupoSeleccionado._fecha;
    const medico      = cupoSeleccionado._medico;
    const especialidad = espSeleccionada.nombre;
    const paciente    = data.nombre || "—";

    // Usar el código real guardado en BD, o generar uno local de respaldo
    const numFicha    = data.codigo_ficha || `HC-${cupoSeleccionado.fecha.replace(/-/g,'')}-${data.numero_turno || '?'}`;

    const horaHTML = horaEst
        ? `<div class="ficha-hora-badge">
               <span class="ficha-hora-icon">🕐</span>
               <div class="ficha-hora-texts">
                   <div class="ficha-hora-label">Hora estimada de atención</div>
                   <div class="ficha-hora-valor">${horaEst} hs</div>
                   ${promedio ? `<div class="ficha-hora-prom">~${promedio} min por turno</div>` : ""}
               </div>
           </div>`
        : `<div class="ficha-hora-badge ficha-hora-sin">
               <span class="ficha-hora-icon">⏳</span>
               <div class="ficha-hora-texts">
                   <div class="ficha-hora-label">Hora estimada</div>
                   <div class="ficha-hora-valor">Por confirmar</div>
                   <div class="ficha-hora-prom">El médico aún no publicó su agenda</div>
               </div>
           </div>`;

    document.getElementById("exitoDetalle").innerHTML = `
        <div class="ficha-card-exito">
            <!-- Header -->
            <div class="ficha-header-exito">
                <div class="ficha-hospital-info">
                    <div class="ficha-hospital-name">Hospital de Clínicas</div>
                    <div class="ficha-hospital-sub">Sistema de Gestión de Especialidades Médicas</div>
                </div>
                <div class="ficha-num-box">
                    <div class="ficha-num-label">Número de Ficha</div>
                    <div class="ficha-num-valor">${numFicha}</div>
                </div>
            </div>

            <!-- Datos paciente -->
            <div class="ficha-seccion">
                <div class="ficha-seccion-titulo">👤 Datos del Paciente</div>
                <div class="ficha-dato-nombre">${paciente}</div>
            </div>

            <!-- Datos cita -->
            <div class="ficha-seccion">
                <div class="ficha-seccion-titulo">📅 Datos de la Cita Médica</div>
                <div class="ficha-cita-grid">
                    <div class="ficha-cita-item">
                        <div class="ficha-cita-label">Especialidad</div>
                        <div class="ficha-cita-valor">${especialidad}</div>
                    </div>
                    <div class="ficha-cita-item">
                        <div class="ficha-cita-label">Médico Asignado</div>
                        <div class="ficha-cita-valor">${medico}</div>
                    </div>
                    <div class="ficha-cita-item">
                        <div class="ficha-cita-label">Fecha de Atención</div>
                        <div class="ficha-cita-valor">${fechaLarga}</div>
                    </div>
                    <div class="ficha-cita-item">
                        <div class="ficha-cita-label">Turno Asignado</div>
                        <div class="ficha-cita-valor">Turno #${turno}</div>
                    </div>
                </div>
            </div>

            <!-- Hora estimada (destacada) -->
            ${horaHTML}

            <!-- Instrucciones -->
            <div class="ficha-instrucciones">
                <div class="ficha-instr-titulo">📋 Instrucciones Importantes:</div>
                <ul class="ficha-instr-lista">
                    <li>Llegue 15 minutos antes de su turno asignado</li>
                    <li>Traiga su cédula de identidad original</li>
                    <li>Traiga estudios previos si los tiene</li>
                    <li>Muestre esta ficha o el código QR en recepción</li>
                </ul>
            </div>
        </div>`;

    document.getElementById("modalExito").classList.add("open");
}

function cerrarExito() {
    document.getElementById("modalExito").classList.remove("open");

    if (_credencialesNuevas) {
        mostrarCredenciales(_credencialesNuevas);
        _credencialesNuevas = null;
        return;
    }

    if (espSeleccionada) cargarFechas(espSeleccionada.id);
    document.getElementById("cupoDetalle").hidden = true;
}

function mostrarCredenciales(cred) {
    document.getElementById("credUsuario").textContent  = cred.usuario;
    document.getElementById("credPassword").textContent = cred.contrasena;
    document.getElementById("btnIrLogin").disabled = true;
    document.getElementById("btnDescargarCred").textContent = "📥 Descargar mis credenciales";
    _credActuales = cred;
    document.getElementById("modalCredenciales").classList.add("open");
}

function descargarCredenciales() {
    if (!_credActuales) return;

    const canvas = document.createElement("canvas");
    canvas.width  = 640;
    canvas.height = 420;
    const ctx = canvas.getContext("2d");

    // Fondo
    ctx.fillStyle = "#0F172A";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Encabezado
    ctx.fillStyle = "#2DD4BF";
    ctx.font = "bold 26px Arial";
    ctx.fillText("Hospital de Clínicas", 40, 60);
    ctx.fillStyle = "#94A3B8";
    ctx.font = "15px Arial";
    ctx.fillText("Credenciales de acceso al Portal Paciente", 40, 88);

    // Caja credenciales
    ctx.fillStyle = "#1E293B";
    ctx.fillRect(40, 120, 560, 200);
    ctx.strokeStyle = "#FCD34D";
    ctx.lineWidth = 2;
    ctx.strokeRect(40, 120, 560, 200);

    ctx.fillStyle = "#FCD34D";
    ctx.font = "bold 13px Arial";
    ctx.fillText("USUARIO (TU CI)", 64, 160);
    ctx.fillStyle = "#FFFFFF";
    ctx.font = "bold 28px Courier New";
    ctx.fillText(_credActuales.usuario, 64, 195);

    ctx.fillStyle = "#FCD34D";
    ctx.font = "bold 13px Arial";
    ctx.fillText("CONTRASEÑA (TU CELULAR)", 64, 245);
    ctx.fillStyle = "#FFFFFF";
    ctx.font = "bold 28px Courier New";
    ctx.fillText(_credActuales.contrasena, 64, 280);

    // Pie
    ctx.fillStyle = "#64748B";
    ctx.font = "13px Arial";
    ctx.fillText("Usa estos datos para iniciar sesión en el Portal Paciente", 40, 360);
    ctx.fillText("y confirmar tu asistencia antes de cada cita.", 40, 380);

    // Descargar
    const link = document.createElement("a");
    link.download = `credenciales_${_credActuales.usuario}.png`;
    link.href = canvas.toDataURL("image/png");
    link.click();

    // Desbloquear botón de login
    document.getElementById("btnDescargarCred").textContent = "✓ Credenciales descargadas";
    document.getElementById("btnIrLogin").disabled = false;
}

function irALogin() {
    window.location.href = "login.html";
}

// ── Helpers ──────────────────────────────────────────────────
function mostrarMsg(texto, tipo) {
    const el = document.getElementById("msgReserva");
    el.textContent = texto;
    el.className = `form-msg ${tipo}`;
}
function limpiarMsg() {
    const el = document.getElementById("msgReserva");
    el.textContent = "";
    el.className = "form-msg";
}
function esc(str) {
    return (str || "").replace(/'/g, "\\'").replace(/"/g, '\\"');
}

// ── Inicio ───────────────────────────────────────────────────
cargarEspecialidades();