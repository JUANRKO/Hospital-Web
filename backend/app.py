from flask import Flask
from flask_cors import CORS
from routes.auth import auth
from routes.superadmin import superadmin_bp
from routes.admin import admin_bp
from routes.fichas_routes import fichas
from routes.paciente_routes import paciente_bp
from routes.medico_routes import medico_bp
from routes.recuperar_routes import recuperar_bp
from scheduler import iniciar_scheduler

app = Flask(__name__)
CORS(app, resources={r"/api/*": {
    "origins": "*",
    "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization"]
}})

app.register_blueprint(auth,          url_prefix='/api')
app.register_blueprint(fichas,        url_prefix='/api')
app.register_blueprint(superadmin_bp, url_prefix='/api')
app.register_blueprint(admin_bp,      url_prefix='/api')
app.register_blueprint(paciente_bp,   url_prefix='/api')
app.register_blueprint(medico_bp,     url_prefix='/api')
app.register_blueprint(recuperar_bp,  url_prefix='/api')

@app.route('/')
def home():
    return "API Hospital de Clínicas 🚀"

@app.before_request
def handle_options():
    from flask import request, make_response
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        return response

if __name__ == '__main__':
    iniciar_scheduler()
    print("🔥 Servidor iniciado en http://127.0.0.1:5000")
    app.run(debug=True, use_reloader=False)
