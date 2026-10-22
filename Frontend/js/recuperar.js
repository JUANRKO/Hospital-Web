const API = "http://127.0.0.1:5000/api";

let _idUsuario      = null;
let _idRecuperacion = null;
let _timerInterval  = null;
let _segs           = 300;

// ── Helpers ──────────────────────────────────────────────────
function mostrarMsg(idMsg, texto, tipo) {
    const el = document.getElementById(idMsg);
    el.textContent = texto;
    el.className = `msg ${tipo}`;
}
function limpiarMsg(idMsg) {
    const el = document.getElementById(idMsg);
    el.className = "msg";
    el.textContent = "";
}

function setBtn(id, txtId, cargando, textoOriginal) {
    const btn = document.getElementById(id);
    btn.disabled = cargando;
    document.getElementById(txtId).textContent = cargando ? "Cargando..." : textoOriginal;
}

function irPaso(n) {
    document.querySelectorAll(".paso").forEach(p => p.classList.remove("activo"));
    document.getElementById(`paso${n}`).classList.add("activo");
    [0, 1, 2].forEach(i => {
        const d = document.getElementById(`dot${i}`);
        if (!d) return;
        d.classList.remove("activo", "hecho");
        if (i < n - 1)       d.classList.add("hecho");
        else if (i === n - 1) d.classList.add("activo");
    });
}

function toggleVer(inputId, btn) {
    const inp = document.getElementById(inputId);
    inp.type = inp.type === "password" ? "text" : "password";
    // cambiar icono: ojo abierto / tachado
    btn.innerHTML = inp.type === "text"
        ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
               <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>
               <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>
               <line x1="1" y1="1" x2="23" y2="23"/>
           </svg>`
        : `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
               <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
               <circle cx="12" cy="12" r="3"/>
           </svg>`;
}

// ── OTP ──────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    const otps = Array.from({length: 6}, (_, i) => document.getElementById(`otp${i}`));

    otps.forEach((inp, i) => {
        inp.addEventListener("input", e => {
            const v = e.target.value.replace(/\D/g, "");
            e.target.value = v;
            e.target.classList.toggle("filled", !!v);
            if (v && i < 5) otps[i + 1].focus();
        });
        inp.addEventListener("keydown", e => {
            if (e.key === "Backspace" && !inp.value && i > 0) {
                otps[i - 1].focus();
                otps[i - 1].value = "";
                otps[i - 1].classList.remove("filled");
            }
            if (e.key === "Enter") verificarCodigo();
        });
        inp.addEventListener("paste", e => {
            e.preventDefault();
            const txt = (e.clipboardData.getData("text") || "").replace(/\D/g, "").slice(0, 6);
            txt.split("").forEach((c, j) => {
                if (otps[j]) { otps[j].value = c; otps[j].classList.add("filled"); }
            });
            otps[Math.min(txt.length, 5)].focus();
        });
    });

    document.getElementById("inpIdentificador").addEventListener("keydown", e => {
        if (e.key === "Enter") solicitarCodigo();
    });
});

function leerOTP() {
    return Array.from({length: 6}, (_, i) => document.getElementById(`otp${i}`).value).join("");
}
function limpiarOTP() {
    for (let i = 0; i < 6; i++) {
        const el = document.getElementById(`otp${i}`);
        el.value = ""; el.classList.remove("filled", "err");
    }
}

// ── Timer ─────────────────────────────────────────────────────
function iniciarTimer() {
    _segs = 300;
    clearInterval(_timerInterval);
    renderTimer();
    _timerInterval = setInterval(() => {
        _segs--;
        renderTimer();
        if (_segs <= 0) {
            clearInterval(_timerInterval);
            const tv = document.getElementById("timerVal");
            tv.textContent = "Expirado";
            tv.classList.add("expiro");
            document.getElementById("btnReenviar").disabled = false;
        }
    }, 1000);
    // habilitar reenvío a los 60s
    setTimeout(() => {
        if (_segs > 0) document.getElementById("btnReenviar").disabled = false;
    }, 60000);
}

function renderTimer() {
    const m = Math.floor(_segs / 60);
    const s = _segs % 60;
    document.getElementById("timerVal").textContent = `${m}:${String(s).padStart(2, "0")}`;
}

// ── Fuerza contraseña ─────────────────────────────────────────
function evaluarFuerza(v) {
    let p = 0;
    if (v.length >= 8)            p++;
    if (/[A-Z]/.test(v))          p++;
    if (/[0-9]/.test(v))          p++;
    if (/[^A-Za-z0-9]/.test(v))  p++;

    const niveles = [
        {c:"#EF4444", t:"Muy débil",  w:"20%"},
        {c:"#F97316", t:"Débil",      w:"40%"},
        {c:"#EAB308", t:"Regular",    w:"60%"},
        {c:"#22C55E", t:"Fuerte",     w:"80%"},
        {c:"#10B981", t:"Muy fuerte", w:"100%"},
    ];
    const n = niveles[Math.max(0, p - 1)];
    const fill = document.getElementById("strengthFill");
    fill.style.width      = v.length > 0 ? n.w : "0%";
    fill.style.background = n.c;
    document.getElementById("strengthTxt").textContent = v.length > 0 ? n.t : "";
}

// ══ PASO 1: Solicitar ════════════════════════════════════════
async function solicitarCodigo() {
    limpiarMsg("msg1");
    const identificador = document.getElementById("inpIdentificador").value.trim();
    if (!identificador) {
        mostrarMsg("msg1", "Ingresá tu teléfono o correo.", "error"); return;
    }

    setBtn("btnSolicitar", "btnSolicitarTxt", true, "Enviar código");
    try {
        const res  = await fetch(`${API}/recuperar/solicitar`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({identificador})
        });
        const data = await res.json();

        if (!data.success) {
            mostrarMsg("msg1", data.message || "Error al enviar.", "error"); return;
        }

        // Si el teléfono/correo no existe, mostrar mensaje y no avanzar
        if (!data.id_usuario) {
            mostrarMsg("msg1", "Si el dato está registrado, recibirás el código.", "info");
            return;
        }

        _idUsuario = data.id_usuario;
        document.getElementById("destinoTexto").textContent = data.destino || "tu dispositivo";
        limpiarOTP();
        iniciarTimer();
        irPaso(2);
        setTimeout(() => document.getElementById("otp0").focus(), 150);

    } catch (_) {
        mostrarMsg("msg1", "Error de conexión. Intentá de nuevo.", "error");
    } finally {
        setBtn("btnSolicitar", "btnSolicitarTxt", false, "Enviar código");
    }
}

// ══ PASO 2: Verificar ════════════════════════════════════════
async function verificarCodigo() {
    limpiarMsg("msg2");
    const codigo = leerOTP();

    if (codigo.length < 6) {
        mostrarMsg("msg2", "Ingresá los 6 dígitos del código.", "error"); return;
    }
    if (_segs <= 0) {
        mostrarMsg("msg2", "El código expiró. Solicitá uno nuevo.", "error"); return;
    }

    setBtn("btnVerificar", "btnVerificarTxt", true, "Verificar código");
    try {
        const res  = await fetch(`${API}/recuperar/verificar`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({id_usuario: _idUsuario, codigo})
        });
        const data = await res.json();

        if (!data.success) {
            mostrarMsg("msg2", data.message || "Código incorrecto.", "error");
            limpiarOTP();
            // marcar en rojo los digits
            for (let i = 0; i < 6; i++) document.getElementById(`otp${i}`).classList.add("err");
            setTimeout(() => {
                for (let i = 0; i < 6; i++) document.getElementById(`otp${i}`).classList.remove("err");
            }, 700);
            document.getElementById("otp0").focus();
            return;
        }

        clearInterval(_timerInterval);
        _idRecuperacion = data.id_recuperacion;
        irPaso(3);
        setTimeout(() => document.getElementById("inpPass1").focus(), 150);

    } catch (_) {
        mostrarMsg("msg2", "Error de conexión.", "error");
    } finally {
        setBtn("btnVerificar", "btnVerificarTxt", false, "Verificar código");
    }
}

// ── Reenviar ──────────────────────────────────────────────────
async function reenviarCodigo() {
    const identificador = document.getElementById("inpIdentificador").value.trim();
    if (!identificador) return;
    document.getElementById("btnReenviar").disabled = true;
    limpiarMsg("msg2");

    try {
        const res  = await fetch(`${API}/recuperar/solicitar`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({identificador})
        });
        const data = await res.json();
        if (data.success) {
            _idUsuario = data.id_usuario;
            limpiarOTP();
            iniciarTimer();
            mostrarMsg("msg2", "Código reenviado correctamente.", "success");
            document.getElementById("otp0").focus();
        } else {
            mostrarMsg("msg2", data.message || "No se pudo reenviar.", "error");
            document.getElementById("btnReenviar").disabled = false;
        }
    } catch (_) {
        mostrarMsg("msg2", "Error de conexión.", "error");
        document.getElementById("btnReenviar").disabled = false;
    }
}

// ══ PASO 3: Nueva contraseña ═════════════════════════════════
async function cambiarPassword() {
    limpiarMsg("msg3");
    const p1 = document.getElementById("inpPass1").value;
    const p2 = document.getElementById("inpPass2").value;

    if (!p1 || !p2)             { mostrarMsg("msg3", "Completá ambos campos.", "error"); return; }
    if (p1 !== p2)              { mostrarMsg("msg3", "Las contraseñas no coinciden.", "error"); return; }
    if (p1.length < 8)          { mostrarMsg("msg3", "Mínimo 8 caracteres.", "error"); return; }
    if (!/[A-Z]/.test(p1))      { mostrarMsg("msg3", "Debe incluir al menos una mayúscula.", "error"); return; }
    if (!/[0-9]/.test(p1))      { mostrarMsg("msg3", "Debe incluir al menos un número.", "error"); return; }

    setBtn("btnCambiar", "btnCambiarTxt", true, "Guardar contraseña");
    try {
        const res  = await fetch(`${API}/recuperar/nueva_password`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                id_usuario:      _idUsuario,
                id_recuperacion: _idRecuperacion,
                password:  p1,
                password2: p2
            })
        });
        const data = await res.json();

        if (!data.success) {
            mostrarMsg("msg3", data.message || "Error al guardar.", "error"); return;
        }

        // Paso 4 éxito — ocultar dots
        document.querySelectorAll(".paso").forEach(p => p.classList.remove("activo"));
        document.getElementById("paso4").classList.add("activo");
        document.querySelector(".steps").style.display = "none";

    } catch (_) {
        mostrarMsg("msg3", "Error de conexión.", "error");
    } finally {
        setBtn("btnCambiar", "btnCambiarTxt", false, "Guardar contraseña");
    }
}