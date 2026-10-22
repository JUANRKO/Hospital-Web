(function () {
    "use strict";

    // ── Elementos del DOM ──────────────────────────────────────
    const form       = document.getElementById("loginForm");
    const emailInput = document.getElementById("email");
    const passInput  = document.getElementById("password");
    const mensaje    = document.getElementById("mensaje");
    const btnSubmit  = document.getElementById("btnSubmit");
    const btnText    = btnSubmit.querySelector(".btn-text");
    const spinner    = document.getElementById("spinner");
    const togglePass = document.getElementById("togglePass");

    // ── Estado ─────────────────────────────────────────────────
    let intentos = 0;
    const MAX_INTENTOS = 3;

    // ── Toggle mostrar/ocultar contraseña ──────────────────────
    togglePass.addEventListener("click", function () {
        const visible = passInput.type === "text";
        passInput.type = visible ? "password" : "text";

        togglePass.querySelector("svg").innerHTML = visible
            ? `<path d="M1 10s3-6 9-6 9 6 9 6-3 6-9 6-9-6-9-6z" stroke="currentColor" stroke-width="1.4"/>
               <circle cx="10" cy="10" r="2.5" stroke="currentColor" stroke-width="1.4"/>`
            : `<path d="M2 2l16 16M7.5 7.7A4 4 0 0013 13M5 5.2C3 6.6 1.5 8.7 1 10c1.4 3.5 5 6 9 6 1.6 0 3-.4 4.2-1"
                    stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
               <path d="M10 4c4 0 7.5 2.5 9 6a10 10 0 01-2 3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>`;
    });

    // ── Helpers ────────────────────────────────────────────────
    function mostrarError(html) {
        mensaje.innerHTML = html;
        mensaje.className = "mensaje show-error";
    }

    function mostrarExito(texto) {
        mensaje.textContent = texto;
        mensaje.className = "mensaje show-success";
    }

    function limpiarMensaje() {
        mensaje.textContent = "";
        mensaje.className = "mensaje";
    }

    function marcarError(input) {
        input.classList.add("error");
        input.addEventListener("input", function quitar() {
            input.classList.remove("error");
            input.removeEventListener("input", quitar);
        }, { once: true });
    }

    function setLoading(loading) {
        btnSubmit.disabled = loading;
        btnText.textContent = loading ? "Verificando..." : "Ingresar al sistema";
        spinner.hidden = !loading;
    }

    // ── Redirección por rol ────────────────────────────────────
    const RUTAS = {
        superadmin: "dashboard_superadmin.html",
        admin:      "dashboard_admin.html",
        medico:     "dashboard_medico.html",
        paciente:   "dashboard_paciente.html",
    };

    function redirigirPorRol(rol) {
        const ruta = RUTAS[rol];
        if (ruta) {
            mostrarExito("✓ Acceso autorizado. Redirigiendo...");
            setTimeout(() => { window.location.href = ruta; }, 900);
        } else {
            mostrarError("Rol de usuario no reconocido. Contacte al administrador.");
        }
    }

    // ── Submit ─────────────────────────────────────────────────
    form.addEventListener("submit", async function (e) {
        e.preventDefault();
        limpiarMensaje();

        const email    = emailInput.value.trim();
        const password = passInput.value.trim();

        if (!email && !password) {
            marcarError(emailInput); marcarError(passInput);
            mostrarError("Completa todos los campos para continuar.");
            return;
        }
        if (!email) {
            marcarError(emailInput);
            mostrarError("Ingresa tu correo electrónico.");
            return;
        }
        if (!password) {
            marcarError(passInput);
            mostrarError("Ingresa tu contraseña.");
            return;
        }

        if (intentos >= MAX_INTENTOS) {
            mostrarError(`Demasiados intentos fallidos.<br><a href="recuperar.html">Recuperar contraseña</a>`);
            return;
        }

        setLoading(true);

        try {
            const res = await fetch("http://127.0.0.1:5000/api/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email, password }),
            });

            const contentType = res.headers.get("content-type") || "";
            if (!contentType.includes("application/json")) {
                throw new Error("Respuesta inesperada del servidor.");
            }

            const data = await res.json();

            if (data.success) {
                intentos = 0;

                // ✅ Guardar en sessionStorage (más seguro, y es lo que lee el dashboard)
                sessionStorage.setItem("token",   data.token);
                sessionStorage.setItem("usuario", JSON.stringify(data.user));

                // Limpiar localStorage por si quedó algo viejo
                localStorage.removeItem("token");
                localStorage.removeItem("usuario");

                redirigirPorRol(data.user.rol);
            } else {
                intentos++;

                if (intentos >= MAX_INTENTOS) {
                    mostrarError(
                        `Cuenta bloqueada o demasiados intentos fallidos.<br>
                         <a href="recuperar.html">Recuperar contraseña</a>`
                    );
                } else {
                    const restantes = MAX_INTENTOS - intentos;
                    const aviso = restantes === 1
                        ? " Te queda <strong>1 intento</strong> antes del bloqueo."
                        : ` Te quedan <strong>${restantes} intentos</strong>.`;
                    mostrarError((data.message || "Credenciales incorrectas.") + aviso);
                }

                marcarError(passInput);
                passInput.value = "";
                passInput.focus();
            }

        } catch (error) {
            console.error("[Login Error]", error);
            mostrarError(
                error.message === "Failed to fetch"
                    ? "No se pudo conectar con el servidor. Verifica tu conexión."
                    : "Error inesperado. Intenta nuevamente."
            );
        } finally {
            setLoading(false);
        }
    });

    // ── Limpiar error visual al escribir ───────────────────────
    [emailInput, passInput].forEach(function (input) {
        input.addEventListener("input", limpiarMensaje);
    });

})();
