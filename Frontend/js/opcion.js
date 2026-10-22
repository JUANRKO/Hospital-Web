
const API = "http://127.0.0.1:5000/api";

// ── Ir sin cuenta → página de fichas disponibles ───────────
function irSinCuenta() {
    window.location.href = "/Frontend/pages/fichas_disponibles.html";
}

// ── Abrir modal de registro ─────────────────────────────────
function abrirRegistro() {
    document.getElementById("formRegistro").reset();
    limpiarMensaje();
    // Bloquear fecha máxima = hoy - 18 años
    const hoy = new Date();
    hoy.setFullYear(hoy.getFullYear() - 18);
    document.getElementById("reg_fecha_nac").max = hoy.toISOString().split("T")[0];
    document.getElementById("modalRegistro").classList.add("open");
}

// ── Cerrar modal ────────────────────────────────────────────
function cerrarModal() {
    document.getElementById("modalRegistro").classList.remove("open");
}

// Cerrar al hacer clic fuera del modal
document.getElementById("modalRegistro").addEventListener("click", function (e) {
    if (e.target === this) cerrarModal();
});

// ── Mensaje del formulario ──────────────────────────────────
function mostrarMensaje(texto, tipo = "error") {
    const el = document.getElementById("msgRegistro");
    el.textContent = texto;
    el.className = `form-msg ${tipo}`;
}

function limpiarMensaje() {
    const el = document.getElementById("msgRegistro");
    el.textContent = "";
    el.className = "form-msg";
}

// ── Validar mayor de 18 años ────────────────────────────────
function esMayorDeEdad(fechaNac) {
    const nacimiento = new Date(fechaNac);
    const hoy = new Date();
    const edad = hoy.getFullYear() - nacimiento.getFullYear();
    const cumplioEsteAno =
        hoy.getMonth() > nacimiento.getMonth() ||
        (hoy.getMonth() === nacimiento.getMonth() && hoy.getDate() >= nacimiento.getDate());
    return edad > 18 || (edad === 18 && cumplioEsteAno);
}

// ── Validación compartida ────────────────────────────────────
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

// ── Registro de paciente ────────────────────────────────────
async function registrarPaciente(e) {
    e.preventDefault();
    limpiarMensaje();

    const nombre     = document.getElementById("reg_nombre").value.trim();
    const ap_paterno = document.getElementById("reg_ap_paterno").value.trim();
    const ap_materno = document.getElementById("reg_ap_materno").value.trim();
    const fecha_nac  = document.getElementById("reg_fecha_nac").value;
    const sexo       = document.getElementById("reg_sexo").value;
    const ci         = document.getElementById("reg_ci").value.trim();
    const telefono   = document.getElementById("reg_telefono").value.trim();
    const direccion  = document.getElementById("reg_direccion").value.trim();
    const email      = document.getElementById("reg_email").value.trim().toLowerCase();
    const password   = document.getElementById("reg_password").value;
    const password2  = document.getElementById("reg_password2").value;

    // 1. CAMPOS VACÍOS
    if (!nombre || !ap_paterno || !ap_materno || !fecha_nac || !sexo || !ci || !telefono || !email || !password) {
        mostrarMensaje("Completa todos los campos obligatorios (*).");
        return;
    }

    // 2. SOLO LETRAS (NOMBRES) + LONGITUD MÍNIMA
    const regexNombre = /^[A-Za-zÁÉÍÓÚáéíóúÜüÑñ\s]{2,}$/;
    if (!regexNombre.test(nombre) || !regexNombre.test(ap_paterno) || !regexNombre.test(ap_materno)) {
        mostrarMensaje("Nombre y apellidos solo deben contener letras (mínimo 2 caracteres).");
        return;
    }

    // 3. FILTRO DE PALABRAS OBSCENAS EN NOMBRES
    if (contieneObscenidad(nombre) || contieneObscenidad(ap_paterno) || contieneObscenidad(ap_materno)) {
        mostrarMensaje("El nombre o apellido contiene palabras no permitidas.");
        return;
    }

    // 4. CI: 6 a 9 dígitos numéricos
    if (!/^\d{6,9}$/.test(ci)) {
        mostrarMensaje("El CI debe tener entre 6 y 9 dígitos numéricos.");
        return;
    }

    // 5. TELÉFONO: exactamente 8 dígitos, empieza en 6 o 7
    if (!/^[67]\d{7}$/.test(telefono)) {
        mostrarMensaje("El teléfono debe tener exactamente 8 dígitos y comenzar en 6 o 7.");
        return;
    }

    // 6. EMAIL
    if (!email.endsWith("@gmail.com")) {
        mostrarMensaje("El correo debe ser @gmail.com");
        return;
    }

    // 7. MAYOR DE EDAD
    if (!esMayorDeEdad(fecha_nac)) {
        mostrarMensaje("Debes ser mayor de 18 años.");
        return;
    }

    // 8. CONTRASEÑA SEGURA
    if (password.length < 8) {
        mostrarMensaje("La contraseña debe tener al menos 8 caracteres.");
        return;
    }

    if (!/[A-Z]/.test(password)) {
        mostrarMensaje("La contraseña debe incluir al menos una mayúscula.");
        return;
    }

    if (!/[0-9]/.test(password)) {
        mostrarMensaje("La contraseña debe incluir al menos un número.");
        return;
    }

    // 9. CONFIRMAR CONTRASEÑA
    if (password !== password2) {
        mostrarMensaje("Las contraseñas no coinciden.");
        return;
    }

    // 👉 AQUÍ SIGUE TU FETCH


    // Deshabilitar botón
    const btn = document.getElementById("btnRegistrar");
    btn.disabled = true;
    btn.querySelector(".btn-text").textContent = "Registrando...";

    try {
        const res = await fetch(`${API}/registro_paciente`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                nombre,
                apellido_paterno: ap_paterno,
                apellido_materno: ap_materno,
                fecha_nacimiento: fecha_nac,
                sexo,
                ci,
                telefono,
                direccion,
                email,
                password
            })
        });

        const data = await res.json();

        if (data.success) {
            mostrarMensaje("¡Cuenta creada exitosamente! Redirigiendo...", "success");

            // Guardar token/usuario si el backend lo devuelve
            if (data.token) {
                sessionStorage.setItem("token", data.token);
            }
            if (data.user) {
                sessionStorage.setItem("usuario", JSON.stringify(data.user));
            }

            // Redirigir al dashboard de paciente o a fichas
            setTimeout(() => {
                window.location.href = data.user
                    ? "/Frontend/pages/dashboard_paciente.html"
                    : "/Frontend/pages/fichas_disponibles.html";
            }, 1400);

        } else {
            mostrarMensaje(data.message || "Error al crear la cuenta. Intenta nuevamente.");
        }

    } catch (error) {
        console.error("[REGISTRO]", error);
        mostrarMensaje("Error de conexión con el servidor.");
    } finally {
        btn.disabled = false;
        btn.querySelector(".btn-text").textContent = "Crear mi cuenta";
    }
}
