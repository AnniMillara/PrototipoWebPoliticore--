from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import os
import ssl
import json
from datetime import datetime, date, timedelta
import pymysql
from functools import wraps
from flask_mail import Mail, Message
import random
import string
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-12345')

# Configuración MySQL
app.config['MYSQL_HOST'] = os.getenv('DB_HOST', 'localhost')
app.config['MYSQL_USER'] = os.getenv('DB_USER', 'root')
app.config['MYSQL_PASSWORD'] = os.getenv('DB_PASSWORD', 'root')
app.config['MYSQL_DB'] = os.getenv('DB_NAME', 'politicore')

# Configuración de Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

# Configuración de correo
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'true').lower() == 'true'
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')
mail = Mail(app)

# Configuración de subida de archivos
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'zip', 'rar'}
os.makedirs(os.path.join(UPLOAD_FOLDER, 'autoridades'), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, 'perfiles'), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, 'tareas'), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, 'foro'), exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB

def get_db_connection():
    # SSL obligatorio para TiDB Cloud (y opcional para local)
    ssl_config = None
    if os.getenv('DB_SSL', 'false').lower() == 'true':
        ssl_config = ssl.create_default_context()

    return pymysql.connect(
        host=app.config['MYSQL_HOST'],
        user=app.config['MYSQL_USER'],
        password=app.config['MYSQL_PASSWORD'],
        database=app.config['MYSQL_DB'],
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
        ssl=ssl_config
    )

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

class User(UserMixin):
    def __init__(self, user_data):
        self.id = user_data['id']
        self.nombre = user_data['nombre']
        self.apellido_paterno = user_data.get('apellido_paterno', '')
        self.email = user_data['email']
        self.tipo_usuario_id = user_data.get('tipo_usuario_id', 4)
        self.nivel = user_data.get('nivel', 1)
        self.xp = user_data.get('xp', 0)
        self.activo = user_data.get('activo', True)
        self.password = user_data.get('password', '')
        self.es_premium = user_data.get('es_premium', False)
        self.fecha_expiracion = user_data.get('fecha_expiracion')
        self.foto_perfil = user_data.get('foto_perfil')
    
    @property
    def is_admin(self):
        return self.tipo_usuario_id in [1, 2]
    
    @property
    def is_super_admin(self):
        return self.tipo_usuario_id == 1
    
    @property
    def is_admin_or_super(self):
        return self.tipo_usuario_id in [1, 2]
    
    @property
    def is_docente(self):
        return self.tipo_usuario_id == 3
    
    @property
    def is_premium_active(self):
        if self.is_docente:
            return True
        if not self.es_premium:
            return False
        if self.fecha_expiracion:
            return date.today() <= self.fecha_expiracion
        return True

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Debes iniciar sesión', 'danger')
            return redirect(url_for('login'))
        if not current_user.is_admin_or_super:
            flash('No tienes permisos de administrador', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Debes iniciar sesión', 'danger')
            return redirect(url_for('login'))
        if not current_user.is_super_admin:
            flash('Necesitas permisos de Super Admin', 'danger')
            return redirect(url_for('admin_dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def premium_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Debes iniciar sesión', 'danger')
            return redirect(url_for('login'))
        if not current_user.is_premium_active:
            flash('Esta función es para profesores premium. ¡Solo $1.000 CLP!', 'warning')
            return redirect(url_for('suscripcion'))
        return f(*args, **kwargs)
    return decorated_function

@login_manager.user_loader
def load_user(user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM usuarios WHERE id = %s AND activo = TRUE", (user_id,))
        user_data = cur.fetchone()
        cur.close()
        conn.close()
        if user_data:
            return User(user_data)
        return None
    except:
        return None

# ======================== RUTAS PRINCIPALES ========================

def get_noticias_from_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM noticias WHERE activa = 1 ORDER BY fecha DESC, fecha_publicacion DESC LIMIT 3")
        noticias = cur.fetchall()
        cur.close()
        conn.close()
        return noticias
    except Exception as e:
        print(f"Error cargando noticias: {e}")
        return []

@app.route('/noticias')
def noticias():
    """Listado público completo de noticias activas"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM noticias
            WHERE activa = 1
            ORDER BY destacada DESC, fecha DESC, fecha_publicacion DESC
        """)
        noticias = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error en /noticias: {e}")
        noticias = []
    return render_template('noticias/index.html', noticias=noticias)


@app.route('/noticia/<int:id>')
def noticia_detalle(id):
    """Detalle público de una noticia"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM noticias WHERE id = %s AND activa = 1", (id,))
        noticia = cur.fetchone()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error en /noticia/{id}: {e}")
        noticia = None

    if not noticia:
        flash('Noticia no encontrada', 'danger')
        return redirect(url_for('noticias'))

    return render_template('noticias/detalle.html', noticia=noticia)

@app.route('/')
def index():
    noticias = get_noticias_from_db()
    if not noticias:
        noticias = [
            {'titulo': 'Megarreforma económica avanza en el Senado', 'descripcion': 'El proyecto de ley que rebaja el impuesto a empresas del 27% al 23% quedó en discusión clave.', 'fecha': '2026-07-29', 'icono': 'landmark'},
            {'titulo': 'Presidente Kast mantiene Estado de Catástrofe en Coquimbo y Huasco', 'descripcion': 'El mandatario mantiene el Decreto de Excepción tras el temporal.', 'fecha': '2026-07-28', 'icono': 'cloud-rain'},
            {'titulo': 'Gobierno refuerza control fronterizo en el norte', 'descripcion': 'El Ministerio del Interior intensifica la presencia de las Fuerzas Armadas en pasos fronterizos.', 'fecha': '2026-07-27', 'icono': 'shield-alt'}
        ]
    proximas_funciones = [
        {'nombre': 'Elecciones en vivo', 'icono': 'vote-yea'},
        {'nombre': 'Comparador de candidatos', 'icono': 'balance-scale'},
        {'nombre': 'Seguimiento de promesas', 'icono': 'clipboard-check'},
        {'nombre': 'Panel para colegios', 'icono': 'school'}
    ]
    return render_template('index.html', noticias_destacadas=noticias[:3], proximas_funciones=proximas_funciones)

# ======================== AUTENTICACIÓN ========================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM usuarios WHERE email = %s AND activo = TRUE", (email,))
            user_data = cur.fetchone()
            cur.close()
            conn.close()
            if user_data and password == user_data['password']:
                user = User(user_data)
                login_user(user)
                flash(f'¡Bienvenido {user.nombre}!', 'success')
                if user.is_admin:
                    return redirect(url_for('admin_dashboard'))
                return redirect(url_for('index'))
            else:
                flash('Credenciales incorrectas', 'danger')
        except Exception as e:
            flash('Error al iniciar sesión', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Has cerrado sesión', 'success')
    return redirect(url_for('index'))

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        plan = request.form.get('plan', 'gratis')
        tipo_usuario = request.form.get('tipo_usuario', 4)

        if not nombre or not email or not password or not confirm_password:
            flash('Todos los campos son obligatorios', 'danger')
            return render_template('registro.html')
        if password != confirm_password:
            flash('Las contraseñas no coinciden', 'danger')
            return render_template('registro.html')
        if len(password) < 8:
            flash('La contraseña debe tener al menos 8 caracteres', 'danger')
            return render_template('registro.html')

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT id FROM usuarios WHERE email = %s", (email,))
            if cur.fetchone():
                flash('Este email ya está registrado', 'danger')
                cur.close()
                conn.close()
                return render_template('registro.html')

            es_premium = 1 if plan in ['mensual', 'anual'] else 0
            hoy = date.today()
            if plan == 'anual':
                fecha_expiracion = hoy + timedelta(days=365)
            elif plan == 'mensual':
                fecha_expiracion = hoy + timedelta(days=30)
            else:
                fecha_expiracion = None

            cur.execute("""
                INSERT INTO usuarios (
                    tipo_usuario_id, nombre, apellido_paterno, email, password,
                    nivel, xp, activo, es_premium, fecha_suscripcion, fecha_expiracion, plan
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    1, 0, 1, %s, CURDATE(), %s, %s
                )
            """, (tipo_usuario, nombre, '', email, password, es_premium, fecha_expiracion, plan))
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Registro exitoso!', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash('Error al registrar usuario', 'danger')
    return render_template('registro.html')

@app.route('/registro_profesor', methods=['GET', 'POST'])
def registro_profesor():
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        plan = request.form.get('plan', 'mensual')
        if password != confirm_password:
            flash('Las contraseñas no coinciden', 'danger')
            return render_template('registro_profesor.html')
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT id FROM usuarios WHERE email = %s", (email,))
            if cur.fetchone():
                flash('Este email ya está registrado', 'danger')
                cur.close()
                conn.close()
                return render_template('registro_profesor.html')

            hoy = date.today()
            if plan == 'anual':
                fecha_expiracion = hoy + timedelta(days=365)
                precio = 11000
            else:
                fecha_expiracion = hoy + timedelta(days=30)
                precio = 1000

            cur.execute("""
                INSERT INTO usuarios (
                    tipo_usuario_id, nombre, apellido_paterno, email, password,
                    nivel, xp, activo, es_premium, fecha_suscripcion, fecha_expiracion, plan
                ) VALUES (
                    3, %s, %s, %s, %s,
                    1, 0, 1, 1, CURDATE(), %s, %s
                )
            """, (nombre, '', email, password, fecha_expiracion, plan))
            conn.commit()
            cur.close()
            conn.close()
            flash(f'✅ Registro exitoso! Premium activado por {precio} CLP (demo)', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash('Error al registrar usuario', 'danger')
    return render_template('registro_profesor.html')

@app.route('/api/simular_pago', methods=['POST'])
def simular_pago():
    data = request.json
    plan = data.get('plan', 'mensual')
    return jsonify({'success': True, 'message': 'Pago simulado exitosamente', 'plan': plan, 'precio': 11000 if plan == 'anual' else 1000})

@app.route('/suscripcion')
@login_required
def suscripcion():
    return render_template('suscripcion.html', usuario=current_user)

@app.route('/api/activar_premium', methods=['POST'])
@login_required
def activar_premium():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE usuarios 
            SET es_premium = TRUE,
                fecha_suscripcion = CURDATE(),
                fecha_expiracion = DATE_ADD(CURDATE(), INTERVAL 30 DAY),
                plan = 'profesional'
            WHERE id = %s
        """, (current_user.id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'message': '¡Premium activado!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/activar_premium_demo', methods=['POST'])
@login_required
def activar_premium_demo():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE usuarios 
            SET es_premium = TRUE,
                fecha_suscripcion = CURDATE(),
                fecha_expiracion = DATE_ADD(CURDATE(), INTERVAL 30 DAY),
                plan = 'profesional'
            WHERE id = %s
        """, (current_user.id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'message': 'Premium activado (demo)'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ======================== PERFIL ========================

@app.route('/perfil')
@login_required
def perfil():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT u.*, tu.nombre as tipo_usuario
            FROM usuarios u
            LEFT JOIN tipos_usuario tu ON u.tipo_usuario_id = tu.id
            WHERE u.id = %s
        """, (current_user.id,))
        usuario = cur.fetchone()
        cur.execute("""
            SELECT COUNT(*) as total
            FROM progreso_lecciones
            WHERE usuario_id = %s AND completada = TRUE
        """, (current_user.id,))
        completadas = cur.fetchone()
        cur.execute("SELECT * FROM insignias_obtenidas WHERE usuario_id = %s", (current_user.id,))
        insignias_raw = cur.fetchall()
        insignias = []
        for ins in insignias_raw:
            cur.execute("SELECT * FROM insignias WHERE id = %s", (ins['insignia_id'],))
            insignia_data = cur.fetchone()
            if insignia_data:
                insignias.append(insignia_data)
        cur.close()
        conn.close()
        return render_template('perfil/index.html', usuario=usuario, completadas=completadas['total'] if completadas else 0, insignias=insignias)
    except Exception as e:
        flash('Error al cargar perfil', 'danger')
        return redirect(url_for('index'))

@app.route('/api/subir_foto_perfil', methods=['POST'])
@login_required
def subir_foto_perfil():
    if 'foto' not in request.files:
        return jsonify({'error': 'No se seleccionó ningún archivo'}), 400
    file = request.files['foto']
    if file.filename == '':
        return jsonify({'error': 'No se seleccionó ningún archivo'}), 400
    if not allowed_file(file.filename):
        return jsonify({'error': 'Formato no permitido'}), 400
    try:
        filename = secure_filename(file.filename)
        extension = filename.rsplit('.', 1)[1].lower()
        nuevo_nombre = f"perfil_{current_user.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{extension}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'perfiles', nuevo_nombre)
        file.save(file_path)
        ruta_guardada = f"uploads/perfiles/{nuevo_nombre}"
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE usuarios SET foto_perfil = %s WHERE id = %s", (ruta_guardada, current_user.id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'foto': url_for('static', filename=ruta_guardada), 'message': 'Foto actualizada'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/eliminar_foto_perfil', methods=['POST'])
@login_required
def eliminar_foto_perfil():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT foto_perfil FROM usuarios WHERE id = %s", (current_user.id,))
        usuario = cur.fetchone()
        if usuario and usuario['foto_perfil']:
            foto_path = os.path.join(app.config['UPLOAD_FOLDER'], usuario['foto_perfil'].replace('uploads/', ''))
            if os.path.exists(foto_path):
                os.remove(foto_path)
            cur.execute("UPDATE usuarios SET foto_perfil = NULL WHERE id = %s", (current_user.id,))
            conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'message': 'Foto eliminada'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ======================== ESTADO (AUTORIDADES) ========================

def get_autoridades_from_json():
    try:
        json_path = os.path.join(os.path.dirname(__file__), 'data', 'autoridades_2026.json')
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            autoridades = data.get('autoridades', [])
        if autoridades:
            sync_autoridades_to_db(autoridades)
        return autoridades
    except Exception as e:
        print(f"Error cargando autoridades: {e}")
        return []

def sync_autoridades_to_db(autoridades):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("TRUNCATE autoridades")
        for auth in autoridades:
            cur.execute("""
                INSERT INTO autoridades (
                    id, nombre, apellido_paterno, cargo, descripcion_cargo, 
                    partido, activo, prioridad, biografia
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                auth.get('id', 0),
                auth.get('nombre', ''),
                auth.get('apellido', ''),
                auth.get('cargo', ''),
                auth.get('descripcion_cargo', '') or auth.get('como_funciona_su_cargo', ''),
                auth.get('partido', ''),
                1,
                auth.get('id', 1),
                auth.get('biografia', '')
            ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error sincronizando BD: {e}")

@app.route('/estado')
def estado():
    autoridades = get_autoridades_from_json()
    return render_template('estado/index.html', autoridades=autoridades)

@app.route('/estado/perfil/<int:id>')
def perfil_autoridad(id):
    autoridades = get_autoridades_from_json()
    autoridad = next((a for a in autoridades if a['id'] == id), None)
    if not autoridad:
        flash('Autoridad no encontrada', 'danger')
        return redirect(url_for('estado'))
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM propuestas
            WHERE autoridad_id = %s AND estado != 'Archivada'
            ORDER BY fecha_publicacion DESC, created_at DESC
        """, (id,))
        propuestas = cur.fetchall()
        cur.close()
        conn.close()
    except:
        propuestas = []
    return render_template('estado/perfil_autoridad.html', autoridad=autoridad, propuestas=propuestas)

@app.route('/propuesta/<int:id>')
def detalle_propuesta(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT p.*, a.nombre as autoridad_nombre, a.apellido_paterno as autoridad_apellido, a.cargo
            FROM propuestas p
            JOIN autoridades a ON p.autoridad_id = a.id
            WHERE p.id = %s
        """, (id,))
        propuesta = cur.fetchone()
        cur.close()
        conn.close()
        if not propuesta:
            flash('Propuesta no encontrada', 'danger')
            return redirect(url_for('estado'))
        return render_template('estado/propuestas_detalle.html', propuesta=propuesta)
    except Exception as e:
        flash('Error al cargar la propuesta', 'danger')
        return redirect(url_for('estado'))

# ======================== LECCIONES ========================

@app.route('/lecciones')
def lecciones():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM mundos_aprendizaje ORDER BY orden")
        mundos = cur.fetchall()
        for mundo in mundos:
            cur.execute("""
                SELECT l.*, 
                       CASE 
                           WHEN pl.completada THEN 'completada'
                           ELSE 'disponible'
                       END as estado,
                       CASE 
                           WHEN pl.completada THEN 100
                           ELSE 0
                       END as progreso
                FROM lecciones l
                LEFT JOIN progreso_lecciones pl ON l.id = pl.leccion_id AND pl.usuario_id = %s
                WHERE l.mundo_id = %s AND l.activo = TRUE
                ORDER BY l.orden
            """, (current_user.id if current_user.is_authenticated else 0, mundo['id']))
            lecciones_data = cur.fetchall()
            if not current_user.is_authenticated:
                for leccion in lecciones_data:
                    leccion['estado'] = 'bloqueada'
                    leccion['progreso'] = 0
            mundo['lecciones'] = lecciones_data
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error en lecciones: {e}")
        mundos = []
    return render_template('lecciones/index.html', mundos=mundos)

# ======================== DESCARGAS ========================

@app.route('/descargas')
def descargas():
    """Material de descarga público"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM descargas
            WHERE activo = TRUE
            ORDER BY fecha_creacion DESC
        """)
        descargas = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        print(f"descargas: {e}")
        descargas = []
    return render_template('descargas.html', descargas=descargas)


@app.route('/admin/descargas')
@login_required
@admin_required
def admin_descargas():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM descargas ORDER BY fecha_creacion DESC")
        descargas = cur.fetchall()
        cur.close(); conn.close()
    except Exception:
        descargas = []
    return render_template('admin/descargas.html', descargas=descargas)


@app.route('/admin/descarga/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_descarga_nueva():
    if request.method == 'POST':
        titulo = request.form.get('titulo', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        categoria = request.form.get('categoria', 'General').strip()
        archivo_url = None

        if 'archivo' in request.files:
            file = request.files['archivo']
            if file and file.filename and allowed_file(file.filename):
                nombre = secure_filename(file.filename)
                final = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{nombre}"
                ruta = os.path.join(app.config['UPLOAD_FOLDER'], 'descargas', final)
                os.makedirs(os.path.dirname(ruta), exist_ok=True)
                file.save(ruta)
                archivo_url = f'/uploads/descargas/{final}'

        if not titulo or not archivo_url:
            flash('Título y archivo son obligatorios', 'danger')
            return redirect(url_for('admin_descarga_nueva'))

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO descargas (titulo, descripcion, archivo_url, categoria, creado_por)
                VALUES (%s, %s, %s, %s, %s)
            """, (titulo, descripcion, archivo_url, categoria, current_user.id))
            conn.commit()
            cur.close(); conn.close()
            flash('✅ Descarga creada', 'success')
            return redirect(url_for('admin_descargas'))
        except Exception as e:
            flash(f'Error: {e}', 'danger')
    return render_template('admin/descarga_form.html', descarga=None)


@app.route('/admin/descarga/eliminar/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_descarga_eliminar(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM descargas WHERE id=%s", (id,))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/leccion/<int:id>')
def detalle_leccion(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT l.*, ma.nombre as mundo
            FROM lecciones l
            LEFT JOIN mundos_aprendizaje ma ON l.mundo_id = ma.id
            WHERE l.id = %s AND l.activo = TRUE
        """, (id,))
        leccion = cur.fetchone()
        if leccion:
            cur.execute("SELECT * FROM actividades_leccion WHERE leccion_id = %s ORDER BY orden", (id,))
            actividades = cur.fetchall()
            leccion['actividades'] = []
            for act in actividades:
                leccion['actividades'].append({
                    'id': act['id'],
                    'tipo': act['tipo'],
                    'pregunta': act['pregunta'],
                    'opciones': json.loads(act['opciones']) if act['opciones'] else [],
                    'respuesta_correcta': json.loads(act['respuesta_correcta']) if act['respuesta_correcta'] else 0,
                    'explicacion': act['explicacion'],
                    'orden': act['orden']
                })
        cur.close()
        conn.close()
    except Exception as e:
        flash('Error al cargar la lección', 'danger')
        return redirect(url_for('lecciones'))
    return render_template('lecciones/detalle.html', leccion=leccion)

@app.route('/api/completar_leccion', methods=['POST'])
@login_required
def completar_leccion():
    data = request.json
    leccion_id = data.get('leccion_id')
    sala_id = data.get('sala_id')
    if not leccion_id:
        return jsonify({'success': False, 'error': 'ID de lección requerido'})
    try:
        sala_id_int = int(sala_id) if sala_id else None
    except (ValueError, TypeError):
        sala_id_int = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM progreso_lecciones WHERE usuario_id = %s AND leccion_id = %s", (current_user.id, leccion_id))
        existente = cur.fetchone()
        cur.execute("SELECT xp FROM lecciones WHERE id = %s", (leccion_id,))
        leccion = cur.fetchone()
        xp_ganado = leccion['xp'] if leccion else 50
        if existente and existente['completada']:
            pass
        else:
            if existente:
                cur.execute("""
                    UPDATE progreso_lecciones 
                    SET completada = TRUE, 
                        fecha_completada = NOW(),
                        puntaje = 100,
                        intentos = intentos + 1
                    WHERE usuario_id = %s AND leccion_id = %s
                """, (current_user.id, leccion_id))
            else:
                cur.execute("""
                    INSERT INTO progreso_lecciones (usuario_id, leccion_id, completada, puntaje, fecha_completada)
                    VALUES (%s, %s, TRUE, 100, NOW())
                """, (current_user.id, leccion_id))
            cur.execute("UPDATE usuarios SET xp = xp + %s WHERE id = %s", (xp_ganado, current_user.id))
        if sala_id_int is not None:
            cur.execute("SELECT id FROM sala_alumnos WHERE sala_id = %s AND alumno_id = %s AND activo = TRUE", (sala_id_int, current_user.id))
            if cur.fetchone():
                cur.execute("""
                    INSERT INTO sala_progreso (sala_id, alumno_id, leccion_id, completada, fecha_completada, puntaje)
                    VALUES (%s, %s, %s, TRUE, NOW(), 100)
                    ON DUPLICATE KEY UPDATE
                    completada = TRUE,
                    fecha_completada = NOW(),
                    puntaje = 100
                """, (sala_id_int, current_user.id, leccion_id))
        else:
            cur.execute("SELECT sala_id FROM sala_alumnos WHERE alumno_id = %s AND activo = TRUE", (current_user.id,))
            salas = cur.fetchall()
            for row in salas:
                cur.execute("""
                    INSERT INTO sala_progreso (sala_id, alumno_id, leccion_id, completada, fecha_completada, puntaje)
                    VALUES (%s, %s, %s, TRUE, NOW(), 100)
                    ON DUPLICATE KEY UPDATE
                    completada = TRUE,
                    fecha_completada = NOW(),
                    puntaje = 100
                """, (row['sala_id'], current_user.id, leccion_id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'xp': xp_ganado})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# ======================== SIMULACIONES ========================

def get_carta_evento_aleatoria(campana_id=None, escena_actual=None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        query = "SELECT * FROM cartas_evento WHERE activa = TRUE "
        params = []
        if campana_id:
            query += " AND (campana_id = %s OR campana_id IS NULL)"
            params.append(campana_id)
        else:
            query += " AND campana_id IS NULL"
        if escena_actual is not None:
            query += """ AND (
                escenas_validas IS NULL 
                OR JSON_CONTAINS(escenas_validas, %s)
            )"""
            params.append(str(escena_actual))
        query += " ORDER BY RAND() LIMIT 1"
        cur.execute(query, params)
        carta = cur.fetchone()
        cur.close()
        conn.close()
        if carta:
            if carta.get('efectos'):
                carta['efectos'] = json.loads(carta['efectos']) if isinstance(carta['efectos'], str) else carta['efectos']
            if carta.get('escenas_validas'):
                carta['escenas_validas'] = json.loads(carta['escenas_validas']) if isinstance(carta['escenas_validas'], str) else carta['escenas_validas']
            return carta
    except Exception as e:
        print(f"Error obteniendo carta: {e}")
    return None

def aplicar_carta_evento(carta, indicadores):
    if not carta or not indicadores:
        return indicadores
    efectos = carta.get('efectos', {})
    if isinstance(efectos, str):
        try:
            efectos = json.loads(efectos)
        except:
            efectos = {}
    for key, valor in efectos.items():
        if key in indicadores:
            try:
                cambio = int(valor) * 5
                nuevo_valor = indicadores.get(key, 50) + cambio
                indicadores[key] = max(0, min(100, nuevo_valor))
            except (ValueError, TypeError):
                pass
        else:
            try:
                indicadores[key] = max(0, min(100, int(valor) * 5 + 50))
            except (ValueError, TypeError):
                pass
    return indicadores

def guardar_indicadores(campana_id, escena_actual, indicadores):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM progreso_simulacion WHERE usuario_id = %s AND campana_id = %s", (current_user.id, campana_id))
        existente = cur.fetchone()
        if not isinstance(indicadores, dict):
            indicadores = {'Participacion': 50, 'Confianza': 50, 'Educacion': 50, 'Seguridad': 50, 'Economia': 50}
        for key in indicadores:
            indicadores[key] = max(0, min(100, indicadores.get(key, 50)))
        indicadores_json = json.dumps(indicadores)
        if existente:
            cur.execute("""
                UPDATE progreso_simulacion 
                SET indicadores = %s, escena_actual = %s, updated_at = NOW()
                WHERE usuario_id = %s AND campana_id = %s
            """, (indicadores_json, escena_actual, current_user.id, campana_id))
        else:
            cur.execute("""
                INSERT INTO progreso_simulacion (usuario_id, campana_id, escena_actual, indicadores, fecha_inicio)
                VALUES (%s, %s, %s, %s, NOW())
            """, (current_user.id, campana_id, escena_actual, indicadores_json))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Error guardando indicadores: {e}")
        return False

def get_ruta_alternativa(carta_id, escena_actual):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM rutas_alternativas WHERE carta_id = %s AND escena_id = %s", (carta_id, escena_actual))
        ruta = cur.fetchone()
        cur.close()
        conn.close()
        if ruta and ruta.get('opciones'):
            ruta['opciones'] = json.loads(ruta['opciones']) if isinstance(ruta['opciones'], str) else ruta['opciones']
        return ruta
    except Exception as e:
        print(f"Error obteniendo ruta: {e}")
        return None

@app.route('/simulacion')
def simulacion():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM campanas_simulacion WHERE activa = TRUE ORDER BY id")
        campanas = cur.fetchall()
        cur.close()
        conn.close()
    except:
        campanas = []
    return render_template('simulacion/index.html', campanas=campanas)

@app.route('/simulacion/<int:id>')
@login_required
def simulacion_jugar(id):
    escena_id = request.args.get('escena', 1)
    ruta_activa = request.args.get('ruta', None)
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM campanas_simulacion WHERE id = %s AND activa = TRUE", (id,))
        campana = cur.fetchone()
        cur.close()
        conn.close()
        if campana:
            campana['introduccion'] = json.loads(campana['introduccion']) if campana['introduccion'] else {}
            campana['escenas'] = json.loads(campana['escenas']) if campana['escenas'] else []
            campana['finales'] = json.loads(campana['finales']) if campana['finales'] else []
            campana['eventos'] = json.loads(campana['eventos']) if campana['eventos'] else []
            if len(campana['escenas']) < 10:
                for i in range(len(campana['escenas']) + 1, 11):
                    campana['escenas'].append({'id': i, 'tipo': 'decision' if i % 2 == 1 else 'evento', 'contexto': f'Situación {i}: Describe aquí el contexto.', 'opciones': [{'texto': f'Opción 1'}, {'texto': f'Opción 2'}, {'texto': f'Opción 3'}]})
        else:
            campana = {
                'id': id,
                'titulo': 'Simulación de ejemplo',
                'descripcion': 'Vive una experiencia cívica',
                'introduccion': {},
                'escenas': [{'id': 1, 'tipo': 'decision', 'contexto': 'Situación inicial', 'opciones': [{'texto': 'Opción 1'}, {'texto': 'Opción 2'}, {'texto': 'Opción 3'}]}],
                'finales': [],
                'eventos': []
            }
    except Exception as e:
        flash('Error al cargar la simulación', 'danger')
        return redirect(url_for('simulacion'))
    total_escenas = len(campana['escenas'])
    escena_actual = int(escena_id)
    indicadores = get_indicadores_actuales(id, escena_actual, campana)
    carta_evento = None
    mostrar_carta = False
    ruta_alternativa = None
    if ruta_activa:
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM rutas_alternativas WHERE id = %s", (ruta_activa,))
            ruta_alternativa = cur.fetchone()
            cur.close()
            conn.close()
            if ruta_alternativa:
                ruta_alternativa['opciones'] = json.loads(ruta_alternativa['opciones']) if ruta_alternativa['opciones'] else []
        except:
            pass
    if not ruta_alternativa and escena_actual % 3 == 0 and escena_actual > 1:
        escena_actual_data = campana['escenas'][escena_actual - 1] if escena_actual <= len(campana['escenas']) else None
        if escena_actual_data and escena_actual_data.get('tipo') == 'decision':
            if random.random() < 0.20:
                carta_evento = get_carta_evento_aleatoria(campana_id=id, escena_actual=escena_actual)
                if carta_evento:
                    mostrar_carta = True
                    ruta = get_ruta_alternativa(carta_evento['id'], escena_actual)
                    if ruta:
                        ruta_alternativa = ruta
                    indicadores = aplicar_carta_evento(carta_evento, indicadores)
                    guardar_indicadores(id, escena_actual, indicadores)
    if ruta_alternativa:
        escena = {
            'id': escena_actual,
            'tipo': 'decision',
            'contexto': ruta_alternativa['nuevo_contexto'],
            'opciones': ruta_alternativa['opciones'],
            'es_ruta_alternativa': True,
            'problema': ruta_alternativa.get('nuevo_problema', ''),
            'siguiente_escena': ruta_alternativa.get('siguiente_escena', escena_actual + 1)
        }
    else:
        escena = campana['escenas'][escena_actual - 1] if escena_actual <= len(campana['escenas']) else campana['escenas'][0]
    if escena_actual > total_escenas:
        final = calcular_final(campana.get('finales', []), indicadores)
        escena_final = {
            'tipo': 'final',
            'titulo': final.get('titulo', 'El Ciudadano Activo'),
            'contexto': final.get('texto', 'Completaste tu camino como ciudadano.'),
            'reflexion': final.get('reflexion', 'La democracia se construye con cada decisión.')
        }
        return render_template('simulacion/jugar.html', campana=campana, escena=escena_final, escena_actual=escena_actual, total_escenas=total_escenas, indicadores=indicadores, carta_evento=carta_evento if mostrar_carta else None, ruta_alternativa=ruta_alternativa)
    return render_template('simulacion/jugar.html', campana=campana, escena=escena, escena_actual=escena_actual, total_escenas=total_escenas, indicadores=indicadores, carta_evento=carta_evento if mostrar_carta else None, ruta_alternativa=ruta_alternativa)

def get_indicadores_actuales(campana_id, escena_actual, campana):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT indicadores FROM progreso_simulacion WHERE usuario_id = %s AND campana_id = %s", (current_user.id, campana_id))
        progreso = cur.fetchone()
        cur.close()
        conn.close()
        if progreso and progreso['indicadores']:
            if isinstance(progreso['indicadores'], str):
                indicadores = json.loads(progreso['indicadores'])
            else:
                indicadores = progreso['indicadores']
            for key in ['Participacion', 'Confianza', 'Educacion', 'Seguridad', 'Economia']:
                if key not in indicadores:
                    indicadores[key] = 50
            return indicadores
    except:
        pass
    dificultad = campana.get('dificultad', 'Intermedio')
    if dificultad == 'Básico':
        return {'Participacion': 60, 'Confianza': 60, 'Educacion': 60, 'Seguridad': 60, 'Economia': 60}
    elif dificultad == 'Avanzado':
        return {'Participacion': 35, 'Confianza': 35, 'Educacion': 35, 'Seguridad': 35, 'Economia': 35}
    else:
        return {'Participacion': 50, 'Confianza': 50, 'Educacion': 50, 'Seguridad': 50, 'Economia': 50}

# ======================== FUNCIÓN CALCULAR FINAL MEJORADA ========================

def calcular_final(finales, indicadores, nombre_usuario=None):
    """
    Siempre genera un final personalizado basado en los indicadores.
    Ignora los finales predefinidos de la base de datos.
    """
    return generar_final_personalizado(indicadores, nombre_usuario)

def generar_final_personalizado(indicadores, nombre_usuario=None):
    """Genera un final personalizado con el nombre del usuario y recomendaciones."""
    # Determinar el indicador más alto
    max_key = max(indicadores, key=lambda k: indicadores[k])
    titulos = {
        'Participacion': 'Ciudadano Participativo',
        'Confianza': 'Ciudadano Confiable',
        'Educacion': 'Ciudadano Informado',
        'Seguridad': 'Ciudadano Seguro',
        'Economia': 'Ciudadano Próspero'
    }
    titulo_base = titulos.get(max_key, 'Ciudadano Activo')
    
    # Si tenemos nombre, incluirlo en el título
    if nombre_usuario:
        titulo = f"{nombre_usuario}, eres un {titulo_base}"
    else:
        titulo = titulo_base
    
    # Resumen de cada indicador
    resumen = "📊 Resumen de tu desempeño:\n"
    for key, value in indicadores.items():
        nivel = "bajo" if value < 40 else "medio" if value < 70 else "alto"
        emoji = "🔴" if value < 40 else "🟡" if value < 70 else "🟢"
        resumen += f"{emoji} {key}: {value}% ({nivel})\n"
    
    # Recomendaciones
    recomendaciones = []
    if indicadores.get('Participacion', 50) < 50:
        recomendaciones.append("🗣️ Participa más en actividades comunitarias y expresa tus ideas.")
    if indicadores.get('Confianza', 50) < 50:
        recomendaciones.append("🔍 Fortalece la confianza informándote y contrastando fuentes.")
    if indicadores.get('Educacion', 50) < 50:
        recomendaciones.append("📚 Aprovecha las lecciones para seguir aprendiendo sobre el sistema.")
    if indicadores.get('Seguridad', 50) < 50:
        recomendaciones.append("🛡️ Infórmate sobre las medidas de seguridad y prevención en tu entorno.")
    if indicadores.get('Economia', 50) < 50:
        recomendaciones.append("💰 Conoce más sobre economía y finanzas para tomar mejores decisiones.")
    
    if not recomendaciones:
        recomendaciones = ["🌟 ¡Excelente desempeño! Sigue participando activamente."]
    
    reflexion = "💡 Basado en tus decisiones, te recomendamos:\n" + "\n".join(f"  • {r}" for r in recomendaciones)
    
    return {
        'titulo': titulo,
        'texto': resumen,
        'reflexion': reflexion
    }

@app.route('/api/procesar_decision_simulacion', methods=['POST'])
@login_required
def procesar_decision_simulacion():
    data = request.json
    campana_id = data.get('campana_id')
    escena_id = data.get('escena_id')
    opcion = data.get('opcion')
    next_scene = int(escena_id) + 1
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT escenas, dificultad FROM campanas_simulacion WHERE id = %s", (campana_id,))
        result = cur.fetchone()
        if not result:
            return jsonify({'next_scene': next_scene})
        escenas = json.loads(result['escenas']) if result['escenas'] else []
        escena_actual = next((e for e in escenas if e.get('id') == int(escena_id)), None)
        if not escena_actual or not escena_actual.get('opciones') or len(escena_actual['opciones']) <= opcion:
            return jsonify({'next_scene': next_scene})
        opcion_data = escena_actual['opciones'][opcion]
        consecuencias = opcion_data.get('consecuencias', {})
        cur.execute("SELECT indicadores FROM progreso_simulacion WHERE usuario_id = %s AND campana_id = %s", (current_user.id, campana_id))
        progreso = cur.fetchone()
        if progreso and progreso['indicadores']:
            if isinstance(progreso['indicadores'], str):
                indicadores = json.loads(progreso['indicadores'])
            else:
                indicadores = progreso['indicadores']
        else:
            dificultad = result.get('dificultad', 'Intermedio')
            if dificultad == 'Básico':
                indicadores = {'Participacion': 60, 'Confianza': 60, 'Educacion': 60, 'Seguridad': 60, 'Economia': 60}
            elif dificultad == 'Avanzado':
                indicadores = {'Participacion': 35, 'Confianza': 35, 'Educacion': 35, 'Seguridad': 35, 'Economia': 35}
            else:
                indicadores = {'Participacion': 50, 'Confianza': 50, 'Educacion': 50, 'Seguridad': 50, 'Economia': 50}
        for key in ['Participacion', 'Confianza', 'Educacion', 'Seguridad', 'Economia']:
            if key not in indicadores:
                indicadores[key] = 50
        for key, value in consecuencias.items():
            if key in indicadores:
                try:
                    cambio = int(value) * 5
                    nuevo_valor = indicadores.get(key, 50) + cambio
                    indicadores[key] = max(0, min(100, nuevo_valor))
                except (ValueError, TypeError):
                    pass
        if progreso:
            cur.execute("""
                UPDATE progreso_simulacion 
                SET escena_actual = %s, indicadores = %s, updated_at = NOW()
                WHERE usuario_id = %s AND campana_id = %s
            """, (next_scene, json.dumps(indicadores), current_user.id, campana_id))
        else:
            cur.execute("""
                INSERT INTO progreso_simulacion (usuario_id, campana_id, escena_actual, indicadores)
                VALUES (%s, %s, %s, %s)
            """, (current_user.id, campana_id, next_scene, json.dumps(indicadores)))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error procesando decisión: {e}")
    return jsonify({'next_scene': next_scene})

@app.route('/api/procesar_evento_simulacion', methods=['POST'])
@login_required
def procesar_evento_simulacion():
    data = request.json
    escena_id = data.get('escena_id')
    next_scene = int(escena_id) + 1
    return jsonify({'next_scene': next_scene})

# ======================== ESTUDIANTE ========================

@app.route('/estudiante/unirse', methods=['GET', 'POST'])
@login_required
def estudiante_unirse():
    if current_user.is_docente:
        flash('Los profesores no pueden unirse a clases como estudiantes', 'warning')
        return redirect(url_for('profesor_salas'))
    if request.method == 'POST':
        codigo = request.form.get('codigo', '').strip().upper()
        if not codigo:
            flash('Ingresa un código de clase', 'danger')
            return render_template('estudiante/unirse.html')
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT id, nombre, profesor_id FROM salas_clase WHERE codigo_acceso = %s AND activa = TRUE", (codigo,))
            sala = cur.fetchone()
            if not sala:
                flash('Código inválido', 'danger')
                cur.close()
                conn.close()
                return render_template('estudiante/unirse.html')
            cur.execute("SELECT id FROM sala_alumnos WHERE sala_id = %s AND alumno_id = %s AND activo = TRUE", (sala['id'], current_user.id))
            if cur.fetchone():
                flash('Ya estás en esta clase', 'info')
                return redirect(url_for('estudiante_mis_clases'))
            cur.execute("INSERT INTO sala_alumnos (sala_id, alumno_id) VALUES (%s, %s)", (sala['id'], current_user.id))
            conn.commit()
            cur.close()
            conn.close()
            flash(f'✅ Te has unido a la clase "{sala["nombre"]}"', 'success')
            return redirect(url_for('estudiante_mis_clases'))
        except Exception as e:
            flash('Error al unirte a la clase', 'danger')
    return render_template('estudiante/unirse.html')

@app.route('/estudiante/mis-clases')
@login_required
def estudiante_mis_clases():
    if current_user.is_docente:
        flash('Los profesores usan "Mis Salas de Clase"', 'warning')
        return redirect(url_for('profesor_salas'))
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT s.id, s.nombre, s.codigo_acceso, 
                   u.nombre as profesor_nombre,
                   sa.fecha_ingreso,
                   (SELECT COUNT(*) FROM sala_progreso 
                    WHERE sala_id = s.id AND alumno_id = %s AND completada = TRUE) as lecciones_completadas
            FROM sala_alumnos sa
            JOIN salas_clase s ON sa.sala_id = s.id
            JOIN usuarios u ON s.profesor_id = u.id
            WHERE sa.alumno_id = %s AND sa.activo = TRUE
            ORDER BY sa.fecha_ingreso DESC
        """, (current_user.id, current_user.id))
        clases = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        clases = []
    return render_template('estudiante/mis_clases.html', clases=clases)

@app.route('/estudiante/clase/<int:sala_id>')
@login_required
def estudiante_clase_detalle(sala_id):
    if current_user.is_docente:
        flash('Los profesores no pueden ver esto como estudiantes', 'warning')
        return redirect(url_for('profesor_salas'))
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT s.*, u.nombre as profesor_nombre
            FROM salas_clase s
            JOIN sala_alumnos sa ON s.id = sa.sala_id
            JOIN usuarios u ON s.profesor_id = u.id
            WHERE s.id = %s AND sa.alumno_id = %s AND sa.activo = TRUE
        """, (sala_id, current_user.id))
        sala = cur.fetchone()
        if not sala:
            flash('No tienes acceso a esta clase', 'danger')
            return redirect(url_for('estudiante_mis_clases'))
        cur.execute("""
            SELECT l.id, l.titulo, l.xp,
                   sp.completada, sp.puntaje, sp.fecha_completada
            FROM lecciones l
            LEFT JOIN sala_progreso sp ON l.id = sp.leccion_id 
                AND sp.alumno_id = %s AND sp.sala_id = %s
            WHERE l.activo = TRUE
            ORDER BY l.id
        """, (current_user.id, sala_id))
        progreso = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        flash('Error al cargar la clase', 'danger')
        return redirect(url_for('estudiante_mis_clases'))
    return render_template('estudiante/clase_detalle.html', sala=sala, progreso=progreso)

# ======================== PROFESOR ========================

@app.route('/profesor/tareas')
@login_required
@premium_required
def profesor_tareas():
    if not current_user.is_docente:
        flash('Solo profesores pueden acceder', 'danger')
        return redirect(url_for('index'))
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM tareas ORDER BY fecha_creacion DESC")
        tareas = cur.fetchall()
        cur.close()
        conn.close()
    except:
        tareas = []
    return render_template('profesor/tareas.html', tareas=tareas)

@app.route('/profesor/salas')
@login_required
def profesor_salas():
    if not current_user.is_docente:
        flash('Solo profesores pueden acceder', 'danger')
        return redirect(url_for('index'))
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT s.*, 
                   (SELECT COUNT(*) FROM sala_alumnos WHERE sala_id = s.id AND activo = TRUE) as total_alumnos,
                   (SELECT COUNT(*) FROM sala_progreso WHERE sala_id = s.id AND completada = TRUE) as total_lecciones_completadas
            FROM salas_clase s
            WHERE s.profesor_id = %s AND s.activa = TRUE
            ORDER BY s.creada_en DESC
        """, (current_user.id,))
        salas = cur.fetchall()
        cur.close()
        conn.close()
    except:
        salas = []
    return render_template('profesor/salas.html', salas=salas)

@app.route('/profesor/sala/nueva', methods=['GET', 'POST'])
@login_required
def profesor_sala_nueva():
    if not current_user.is_docente:
        flash('Solo profesores pueden acceder', 'danger')
        return redirect(url_for('index'))
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion')
        if not nombre:
            flash('El nombre de la sala es obligatorio', 'danger')
            return render_template('profesor/sala_form.html')
        codigo = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO salas_clase (nombre, descripcion, codigo_acceso, profesor_id)
                VALUES (%s, %s, %s, %s)
            """, (nombre, descripcion, codigo, current_user.id))
            conn.commit()
            cur.close()
            conn.close()
            flash(f'✅ Sala creada! Código: {codigo}', 'success')
            return redirect(url_for('profesor_salas'))
        except Exception as e:
            flash('Error al crear la sala', 'danger')
    return render_template('profesor/sala_form.html')

@app.route('/profesor/sala/<int:sala_id>')
@login_required
def profesor_sala_detalle(sala_id):
    if not current_user.is_docente:
        flash('Solo profesores pueden acceder', 'danger')
        return redirect(url_for('index'))
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM salas_clase WHERE id = %s AND profesor_id = %s AND activa = TRUE", (sala_id, current_user.id))
        sala = cur.fetchone()
        if not sala:
            flash('Sala no encontrada', 'danger')
            return redirect(url_for('profesor_salas'))
        cur.execute("""
            SELECT u.id, u.nombre, u.apellido_paterno, u.email, u.nivel, u.xp,
                   sa.fecha_ingreso,
                   (SELECT COUNT(*) FROM sala_progreso 
                    WHERE sala_id = %s AND alumno_id = u.id AND completada = TRUE) as lecciones_completadas,
                   (SELECT ROUND(AVG(puntaje)) FROM sala_progreso 
                    WHERE sala_id = %s AND alumno_id = u.id AND completada = TRUE) as promedio_puntaje
            FROM sala_alumnos sa
            JOIN usuarios u ON sa.alumno_id = u.id
            WHERE sa.sala_id = %s AND sa.activo = TRUE
            ORDER BY u.nombre
        """, (sala_id, sala_id, sala_id))
        alumnos = cur.fetchall()
        cur.execute("""
            SELECT l.id, l.titulo, l.xp, l.icono,
                   COUNT(DISTINCT sp.alumno_id) as alumnos_completaron,
                   ROUND(AVG(sp.puntaje)) as promedio_puntaje_leccion
            FROM lecciones l
            LEFT JOIN sala_progreso sp ON l.id = sp.leccion_id 
                AND sp.sala_id = %s AND sp.completada = TRUE
            WHERE l.activo = TRUE
            GROUP BY l.id
            ORDER BY l.id
        """, (sala_id,))
        lecciones_progreso = cur.fetchall()
        total_alumnos = len(alumnos)
        for leccion in lecciones_progreso:
            leccion['porcentaje'] = round((leccion['alumnos_completaron'] / total_alumnos) * 100) if total_alumnos > 0 else 0
        estadisticas = {
            'total_alumnos': total_alumnos,
            'total_lecciones': len(lecciones_progreso),
            'lecciones_completadas_totales': sum(l['alumnos_completaron'] for l in lecciones_progreso),
            'promedio_general': round(sum(l['promedio_puntaje_leccion'] or 0 for l in lecciones_progreso) / len(lecciones_progreso) if lecciones_progreso else 0)
        }
        cur.close()
        conn.close()
    except Exception as e:
        flash('Error al cargar la sala', 'danger')
        return redirect(url_for('profesor_salas'))
    return render_template('profesor/sala_detalle.html', sala=sala, alumnos=alumnos, lecciones_progreso=lecciones_progreso, estadisticas=estadisticas, total_alumnos=total_alumnos)

@app.route('/profesor/sala/<int:sala_id>/alumno/<int:alumno_id>')
@login_required
def profesor_sala_alumno(sala_id, alumno_id):
    if not current_user.is_docente:
        flash('Solo profesores pueden acceder', 'danger')
        return redirect(url_for('index'))
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM salas_clase WHERE id = %s AND profesor_id = %s AND activa = TRUE", (sala_id, current_user.id))
        sala = cur.fetchone()
        if not sala:
            flash('Sala no encontrada', 'danger')
            return redirect(url_for('profesor_salas'))
        cur.execute("""
            SELECT u.*, sa.fecha_ingreso
            FROM usuarios u
            JOIN sala_alumnos sa ON u.id = sa.alumno_id
            WHERE u.id = %s AND sa.sala_id = %s AND sa.activo = TRUE
        """, (alumno_id, sala_id))
        alumno = cur.fetchone()
        if not alumno:
            flash('Alumno no encontrado en esta sala', 'danger')
            return redirect(url_for('profesor_sala_detalle', sala_id=sala_id))
        cur.execute("""
            SELECT l.id, l.titulo, l.xp, l.icono,
                   sp.completada, sp.puntaje, sp.fecha_completada,
                   CASE WHEN sp.completada THEN 'Completada' ELSE 'Pendiente' END as estado
            FROM lecciones l
            LEFT JOIN sala_progreso sp ON l.id = sp.leccion_id 
                AND sp.alumno_id = %s AND sp.sala_id = %s
            WHERE l.activo = TRUE
            ORDER BY l.id
        """, (alumno_id, sala_id))
        progreso = cur.fetchall()
        total_lecciones = len(progreso)
        completadas = sum(1 for p in progreso if p['completada'])
        promedio = round(sum(p['puntaje'] or 0 for p in progreso if p['completada']) / completadas if completadas > 0 else 0)
        cur.close()
        conn.close()
    except Exception as e:
        flash('Error al cargar los datos', 'danger')
        return redirect(url_for('profesor_sala_detalle', sala_id=sala_id))
    return render_template('profesor/sala_alumno.html', sala=sala, alumno=alumno, progreso=progreso, total_lecciones=total_lecciones, completadas=completadas, promedio=promedio)

@app.route('/profesor/sala/<int:sala_id>/eliminar', methods=['POST'])
@login_required
def profesor_sala_eliminar(sala_id):
    if not current_user.is_docente:
        return jsonify({'error': 'No autorizado'}), 403
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE salas_clase SET activa = FALSE WHERE id = %s AND profesor_id = %s", (sala_id, current_user.id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ======================== ADMIN ========================

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash('No tienes permisos', 'danger')
        return redirect(url_for('index'))
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as total FROM usuarios WHERE activo = TRUE")
        total_usuarios = cur.fetchone()['total']
        cur.execute("SELECT COUNT(*) as total FROM lecciones WHERE activo = TRUE")
        total_lecciones = cur.fetchone()['total']
        cur.execute("SELECT COUNT(*) as total FROM campanas_simulacion WHERE activa = TRUE")
        total_simulaciones = cur.fetchone()['total']
        cur.execute("SELECT COUNT(*) as total FROM autoridades WHERE activo = TRUE")
        total_autoridades = cur.fetchone()['total']
        cur.close()
        conn.close()
        estadisticas = [
            {'nombre': 'Usuarios', 'valor': total_usuarios, 'icono': 'users', 'color': '#14B8A6'},
            {'nombre': 'Lecciones', 'valor': total_lecciones, 'icono': 'book', 'color': '#A78BFA'},
            {'nombre': 'Simulaciones', 'valor': total_simulaciones, 'icono': 'gamepad', 'color': '#F59E0B'},
            {'nombre': 'Autoridades', 'valor': total_autoridades, 'icono': 'landmark', 'color': '#FBBF24'}
        ]
    except:
        estadisticas = [
            {'nombre': 'Usuarios', 'valor': 0, 'icono': 'users', 'color': '#14B8A6'},
            {'nombre': 'Lecciones', 'valor': 0, 'icono': 'book', 'color': '#A78BFA'},
            {'nombre': 'Simulaciones', 'valor': 0, 'icono': 'gamepad', 'color': '#F59E0B'},
            {'nombre': 'Autoridades', 'valor': 0, 'icono': 'landmark', 'color': '#FBBF24'}
        ]
    return render_template('admin/dashboard.html', estadisticas=estadisticas)

# --- ADMIN: LECCIONES ---

@app.route('/admin/lecciones')
@login_required
@admin_required
def admin_lecciones():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT l.*, ma.nombre as mundo_nombre 
            FROM lecciones l
            LEFT JOIN mundos_aprendizaje ma ON l.mundo_id = ma.id
            ORDER BY l.id DESC
        """)
        lecciones = cur.fetchall()
        cur.close()
        conn.close()
    except:
        lecciones = []
    return render_template('admin/lecciones.html', lecciones=lecciones)

def get_mundos():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM mundos_aprendizaje ORDER BY nombre")
        mundos = cur.fetchall()
        cur.close()
        conn.close()
        return mundos
    except:
        return []

@app.route('/admin/leccion/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_leccion_nueva():
    if request.method == 'POST':
        titulo = request.form.get('titulo', '').strip()
        mundo_id = request.form.get('mundo_id', '').strip()
        if not titulo or not mundo_id:
            flash('Título y mundo son obligatorios', 'danger')
            return render_template('admin/leccion_form.html', mundos=get_mundos(), leccion=None)
        try:
            mundo_id = int(mundo_id)
        except ValueError:
            flash('ID de mundo inválido', 'danger')
            return render_template('admin/leccion_form.html', mundos=get_mundos(), leccion=None)
        situacion_inicial = request.form.get('situacion_inicial', '')
        explicacion = request.form.get('explicacion', '')
        ejemplo = request.form.get('ejemplo', '')
        historia = request.form.get('historia', '')
        curiosidad = request.form.get('curiosidad', '')
        reflexion = request.form.get('reflexion', '')
        xp = request.form.get('xp', 50)
        icono = request.form.get('icono', 'book')
        try:
            xp = int(xp)
            if xp < 0:
                xp = 50
        except ValueError:
            xp = 50
        preguntas = request.form.getlist('preguntas[]')
        opciones1 = request.form.getlist('opciones1[]')
        opciones2 = request.form.getlist('opciones2[]')
        opciones3 = request.form.getlist('opciones3[]')
        respuestas_correctas = request.form.getlist('respuestas_correctas[]')
        explicaciones = request.form.getlist('explicaciones[]')
        if not preguntas or len(preguntas) == 0 or not preguntas[0].strip():
            flash('Debe haber al menos una pregunta.', 'danger')
            return render_template('admin/leccion_form.html', mundos=get_mundos(), leccion=None)
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO lecciones (
                    mundo_id, titulo, situacion_inicial, explicacion, 
                    ejemplo, historia, curiosidad, reflexion, xp, icono, activo
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
            """, (mundo_id, titulo, situacion_inicial, explicacion, ejemplo, historia, curiosidad, reflexion, xp, icono))
            leccion_id = cur.lastrowid
            for i in range(len(preguntas)):
                if not preguntas[i].strip():
                    continue
                pregunta = preguntas[i].strip()
                op1 = opciones1[i].strip() if i < len(opciones1) and opciones1[i].strip() else 'Opción 1'
                op2 = opciones2[i].strip() if i < len(opciones2) and opciones2[i].strip() else 'Opción 2'
                op3 = opciones3[i].strip() if i < len(opciones3) and opciones3[i].strip() else 'Opción 3'
                try:
                    respuesta_correcta = int(respuestas_correctas[i]) if i < len(respuestas_correctas) else 0
                    if respuesta_correcta not in [0, 1, 2]:
                        respuesta_correcta = 0
                except (ValueError, IndexError):
                    respuesta_correcta = 0
                explicacion_act = explicaciones[i].strip() if i < len(explicaciones) and explicaciones[i].strip() else ''
                opciones_json = json.dumps([op1, op2, op3])
                respuesta_json = json.dumps(respuesta_correcta)
                cur.execute("""
                    INSERT INTO actividades_leccion (
                        leccion_id, tipo, pregunta, opciones, respuesta_correcta, explicacion, orden
                    ) VALUES (%s, 'alternativas', %s, %s, %s, %s, %s)
                """, (leccion_id, pregunta, opciones_json, respuesta_json, explicacion_act, i))
            conn.commit()
            cur.close()
            conn.close()
            flash(f'¡Lección creada exitosamente con {len(preguntas)} pregunta(s)!', 'success')
            return redirect(url_for('admin_lecciones'))
        except Exception as e:
            flash(f'Error al crear la lección: {str(e)}', 'danger')
    mundos = get_mundos()
    return render_template('admin/leccion_form.html', mundos=mundos, leccion=None)

@app.route('/admin/leccion/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_leccion_editar(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if request.method == 'POST':
            titulo = request.form.get('titulo', '').strip()
            mundo_id = request.form.get('mundo_id', '').strip()
            if not titulo or not mundo_id:
                flash('Título y mundo son obligatorios', 'danger')
                return redirect(url_for('admin_leccion_editar', id=id))
            mundo_id = int(mundo_id)
            situacion_inicial = request.form.get('situacion_inicial', '')
            explicacion = request.form.get('explicacion', '')
            ejemplo = request.form.get('ejemplo', '')
            historia = request.form.get('historia', '')
            curiosidad = request.form.get('curiosidad', '')
            reflexion = request.form.get('reflexion', '')
            xp = request.form.get('xp', 50)
            icono = request.form.get('icono', 'book')
            activo = 1 if request.form.get('activo') else 0
            try:
                xp = int(xp)
                if xp < 0:
                    xp = 50
            except ValueError:
                xp = 50
            cur.execute("""
                UPDATE lecciones 
                SET mundo_id = %s, titulo = %s, situacion_inicial = %s, explicacion = %s, 
                    ejemplo = %s, historia = %s, curiosidad = %s, reflexion = %s, 
                    xp = %s, icono = %s, activo = %s
                WHERE id = %s
            """, (mundo_id, titulo, situacion_inicial, explicacion, ejemplo, historia, curiosidad, reflexion, xp, icono, activo, id))
            cur.execute("DELETE FROM actividades_leccion WHERE leccion_id = %s", (id,))
            preguntas = request.form.getlist('preguntas[]')
            opciones1 = request.form.getlist('opciones1[]')
            opciones2 = request.form.getlist('opciones2[]')
            opciones3 = request.form.getlist('opciones3[]')
            respuestas_correctas = request.form.getlist('respuestas_correctas[]')
            explicaciones = request.form.getlist('explicaciones[]')
            for i in range(len(preguntas)):
                if not preguntas[i].strip():
                    continue
                pregunta = preguntas[i].strip()
                op1 = opciones1[i].strip() if i < len(opciones1) and opciones1[i].strip() else 'Opción 1'
                op2 = opciones2[i].strip() if i < len(opciones2) and opciones2[i].strip() else 'Opción 2'
                op3 = opciones3[i].strip() if i < len(opciones3) and opciones3[i].strip() else 'Opción 3'
                try:
                    respuesta_correcta = int(respuestas_correctas[i]) if i < len(respuestas_correctas) else 0
                    if respuesta_correcta not in [0, 1, 2]:
                        respuesta_correcta = 0
                except (ValueError, IndexError):
                    respuesta_correcta = 0
                explicacion_act = explicaciones[i].strip() if i < len(explicaciones) and explicaciones[i].strip() else ''
                opciones_json = json.dumps([op1, op2, op3])
                respuesta_json = json.dumps(respuesta_correcta)
                cur.execute("""
                    INSERT INTO actividades_leccion (
                        leccion_id, tipo, pregunta, opciones, respuesta_correcta, explicacion, orden
                    ) VALUES (%s, 'alternativas', %s, %s, %s, %s, %s)
                """, (id, pregunta, opciones_json, respuesta_json, explicacion_act, i))
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Lección actualizada exitosamente!', 'success')
            return redirect(url_for('admin_lecciones'))
        cur.execute("SELECT * FROM lecciones WHERE id = %s", (id,))
        leccion = cur.fetchone()
        cur.execute("SELECT * FROM actividades_leccion WHERE leccion_id = %s ORDER BY orden", (id,))
        actividades = cur.fetchall()
        for act in actividades:
            if act.get('opciones'):
                act['opciones'] = json.loads(act['opciones']) if isinstance(act['opciones'], str) else act['opciones']
            if act.get('respuesta_correcta'):
                act['respuesta_correcta'] = json.loads(act['respuesta_correcta']) if isinstance(act['respuesta_correcta'], str) else act['respuesta_correcta']
        leccion['actividades'] = actividades
        cur.execute("SELECT * FROM mundos_aprendizaje ORDER BY nombre")
        mundos = cur.fetchall()
        cur.close()
        conn.close()
        return render_template('admin/leccion_form.html', leccion=leccion, mundos=mundos)
    except Exception as e:
        flash('Error al editar la lección', 'danger')
        return redirect(url_for('admin_lecciones'))

@app.route('/admin/leccion/eliminar/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_leccion_eliminar(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM lecciones WHERE id = %s", (id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- ADMIN: SIMULACIONES ---

@app.route('/admin/simulaciones')
@login_required
@admin_required
def admin_simulaciones():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT s.*, JSON_LENGTH(s.escenas) as total_escenas FROM campanas_simulacion s ORDER BY s.id DESC")
        simulaciones = cur.fetchall()
        cur.close()
        conn.close()
    except:
        simulaciones = []
    return render_template('admin/simulaciones.html', simulaciones=simulaciones)

@app.route('/admin/simulacion/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_simulacion_nueva():
    if request.method == 'POST':
        try:
            titulo = request.form.get('titulo')
            descripcion = request.form.get('descripcion')
            dificultad = request.form.get('dificultad', 'Intermedio')
            xp_recompensa = request.form.get('xp_recompensa', 100)
            activa = 1 if request.form.get('activa') else 0
            escenas_base = []
            for i in range(1, 11):
                escena = {
                    'id': i,
                    'tipo': 'decision' if i != 5 else 'evento',
                    'contexto': f'Situación {i}: Describe aquí el contexto de la escena {i}',
                    'opciones': [{'texto': f'Opción 1 para la situación {i}'}, {'texto': f'Opción 2 para la situación {i}'}, {'texto': f'Opción 3 para la situación {i}'}]
                }
                escenas_base.append(escena)
            introduccion = json.dumps({'contexto': request.form.get('contexto', 'Contexto inicial.'), 'personajes': [{'nombre': 'Personaje 1', 'rol': 'Rol'}, {'nombre': 'Personaje 2', 'rol': 'Rol'}], 'objetivo': request.form.get('objetivo', 'Objetivo.')})
            escenas = json.dumps(escenas_base)
            finales = json.dumps([
                {'titulo': 'El Conciliador', 'condiciones': {'Confianza': '> 50', 'Participacion': '> 50'}, 'texto': 'Lograste unir a todos.', 'reflexion': 'Reflexión.'},
                {'titulo': 'El Reformista', 'condiciones': {'Educacion': '> 50', 'Participacion': '> 40'}, 'texto': 'Implementaste cambios.', 'reflexion': 'Reflexión.'}
            ])
            eventos = json.dumps([{'trigger': 3, 'titulo': 'Evento', 'descripcion': 'Descripción.'}])
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO campanas_simulacion (titulo, descripcion, dificultad, introduccion, escenas, finales, eventos, xp_recompensa, activa)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (titulo, descripcion, dificultad, introduccion, escenas, finales, eventos, xp_recompensa, activa))
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Simulación creada exitosamente!', 'success')
            return redirect(url_for('admin_simulaciones'))
        except Exception as e:
            flash('Error al crear la simulación', 'danger')
    return render_template('admin/simulacion_form.html', simulacion=None)

@app.route('/admin/simulacion/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_simulacion_editar(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if request.method == 'POST':
            titulo = request.form.get('titulo')
            descripcion = request.form.get('descripcion')
            dificultad = request.form.get('dificultad', 'Intermedio')
            xp_recompensa = request.form.get('xp_recompensa', 100)
            activa = 1 if request.form.get('activa') else 0
            cur.execute("""
                UPDATE campanas_simulacion 
                SET titulo = %s, descripcion = %s, dificultad = %s, xp_recompensa = %s, activa = %s
                WHERE id = %s
            """, (titulo, descripcion, dificultad, xp_recompensa, activa, id))
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Simulación actualizada!', 'success')
            return redirect(url_for('admin_simulaciones'))
        cur.execute("SELECT * FROM campanas_simulacion WHERE id = %s", (id,))
        simulacion = cur.fetchone()
        if simulacion:
            simulacion['introduccion'] = json.loads(simulacion['introduccion']) if simulacion['introduccion'] else {}
            simulacion['escenas'] = json.loads(simulacion['escenas']) if simulacion['escenas'] else []
            simulacion['finales'] = json.loads(simulacion['finales']) if simulacion['finales'] else []
            simulacion['eventos'] = json.loads(simulacion['eventos']) if simulacion['eventos'] else []
        cur.close()
        conn.close()
        return render_template('admin/simulacion_form.html', simulacion=simulacion)
    except Exception as e:
        flash('Error al editar la simulación', 'danger')
        return redirect(url_for('admin_simulaciones'))

@app.route('/admin/simulacion/editar_escenas/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_simulacion_editar_escenas(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM campanas_simulacion WHERE id = %s", (id,))
        simulacion = cur.fetchone()
        cur.close()
        conn.close()
        if not simulacion:
            flash('Simulación no encontrada', 'danger')
            return redirect(url_for('admin_simulaciones'))
        escenas = json.loads(simulacion['escenas']) if simulacion['escenas'] else []
        if request.method == 'POST':
            escena_ids = request.form.getlist('escena_id[]')
            escena_original_ids = request.form.getlist('escena_original_id[]')
            escena_contextos = request.form.getlist('escena_contexto[]')
            escena_tipos = request.form.getlist('escena_tipo[]')
            opcion1s = request.form.getlist('opcion1[]')
            opcion2s = request.form.getlist('opcion2[]')
            opcion3s = request.form.getlist('opcion3[]')
            cons_participacion = request.form.getlist('cons_participacion[]')
            cons_confianza = request.form.getlist('cons_confianza[]')
            cons_educacion = request.form.getlist('cons_educacion[]')
            cons_seguridad = request.form.getlist('cons_seguridad[]')
            cons_economia = request.form.getlist('cons_economia[]')
            nuevas_escenas = []
            for i in range(len(escena_ids)):
                if i < len(escena_original_ids) and escena_original_ids[i] != 'new':
                    escena_id = int(escena_original_ids[i])
                else:
                    escena_id = i + 1
                escena = {
                    'id': escena_id,
                    'tipo': escena_tipos[i] if i < len(escena_tipos) else 'decision',
                    'contexto': escena_contextos[i] if i < len(escena_contextos) else ''
                }
                if escena['tipo'] == 'decision':
                    opciones = []
                    textos = []
                    if i < len(opcion1s):
                        textos.append(opcion1s[i].strip())
                    else:
                        textos.append('')
                    if i < len(opcion2s):
                        textos.append(opcion2s[i].strip())
                    else:
                        textos.append('')
                    if i < len(opcion3s):
                        textos.append(opcion3s[i].strip())
                    else:
                        textos.append('')
                    base_idx = i * 3
                    for j in range(3):
                        texto = textos[j]
                        if texto == '':
                            continue
                        idx = base_idx + j
                        def get_val(lista, idx):
                            if idx < len(lista) and lista[idx] != '':
                                try:
                                    return int(lista[idx])
                                except ValueError:
                                    return None
                            return None
                        consecuencias = {}
                        val = get_val(cons_participacion, idx)
                        if val is not None:
                            consecuencias['Participacion'] = val
                        val = get_val(cons_confianza, idx)
                        if val is not None:
                            consecuencias['Confianza'] = val
                        val = get_val(cons_educacion, idx)
                        if val is not None:
                            consecuencias['Educacion'] = val
                        val = get_val(cons_seguridad, idx)
                        if val is not None:
                            consecuencias['Seguridad'] = val
                        val = get_val(cons_economia, idx)
                        if val is not None:
                            consecuencias['Economia'] = val
                        opcion = {'texto': texto}
                        if consecuencias:
                            opcion['consecuencias'] = consecuencias
                        opciones.append(opcion)
                    if not opciones:
                        opciones = [{'texto': 'Opción por defecto'}]
                    escena['opciones'] = opciones
                nuevas_escenas.append(escena)
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("UPDATE campanas_simulacion SET escenas = %s WHERE id = %s", (json.dumps(nuevas_escenas, ensure_ascii=False), id))
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Situaciones actualizadas exitosamente!', 'success')
            return redirect(url_for('admin_simulaciones'))
        return render_template('admin/simulacion_escenas.html', simulacion=simulacion, escenas=escenas)
    except Exception as e:
        flash('Error al editar las situaciones', 'danger')
        return redirect(url_for('admin_simulaciones'))

# --- ADMIN: CARTAS DE EVENTO ---

@app.route('/admin/cartas_evento')
@login_required
@admin_required
def admin_cartas_evento():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT c.*, CASE WHEN c.activa = 1 THEN 'Activa' ELSE 'Inactiva' END as estado_texto FROM cartas_evento c ORDER BY c.id DESC")
        cartas = cur.fetchall()
        cur.close()
        conn.close()
        for carta in cartas:
            if carta.get('efectos'):
                if isinstance(carta['efectos'], str):
                    try:
                        carta['efectos'] = json.loads(carta['efectos'])
                    except:
                        carta['efectos'] = {}
                elif not isinstance(carta['efectos'], dict):
                    carta['efectos'] = {}
            else:
                carta['efectos'] = {}
    except:
        cartas = []
    return render_template('admin/cartas_evento.html', cartas=cartas)

@app.route('/admin/carta_evento/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_carta_evento_nueva():
    if request.method == 'POST':
        try:
            titulo = request.form.get('titulo')
            descripcion = request.form.get('descripcion')
            icono = request.form.get('icono', 'bolt')
            tipo = request.form.get('tipo', 'sorpresa')
            mensaje_visible = request.form.get('mensaje_visible')
            probabilidad = float(request.form.get('probabilidad', 15)) / 100
            activa = 1 if request.form.get('activa') else 0
            campana_id = request.form.get('campana_id')
            if campana_id == '':
                campana_id = None
            escenas_validas = request.form.get('escenas_validas')
            if escenas_validas:
                try:
                    if escenas_validas.startswith('['):
                        escenas_validas = json.loads(escenas_validas)
                    else:
                        escenas_validas = [int(x.strip()) for x in escenas_validas.split(',') if x.strip()]
                    escenas_validas = json.dumps(escenas_validas)
                except:
                    escenas_validas = None
            else:
                escenas_validas = None
            efectos = {}
            if request.form.get('efecto_participacion'):
                efectos['Participacion'] = int(request.form.get('efecto_participacion'))
            if request.form.get('efecto_confianza'):
                efectos['Confianza'] = int(request.form.get('efecto_confianza'))
            if request.form.get('efecto_educacion'):
                efectos['Educacion'] = int(request.form.get('efecto_educacion'))
            if request.form.get('efecto_seguridad'):
                efectos['Seguridad'] = int(request.form.get('efecto_seguridad'))
            if request.form.get('efecto_economia'):
                efectos['Economia'] = int(request.form.get('efecto_economia'))
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO cartas_evento 
                (titulo, descripcion, icono, tipo, efectos, mensaje_visible, 
                 probabilidad, activa, creado_por, campana_id, escenas_validas)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (titulo, descripcion, icono, tipo, json.dumps(efectos), mensaje_visible, 
                  probabilidad, activa, current_user.id, campana_id, escenas_validas))
            conn.commit()
            cur.close()
            conn.close()
            flash('✅ Carta de evento creada', 'success')
            return redirect(url_for('admin_cartas_evento'))
        except Exception as e:
            flash('Error al crear la carta', 'danger')
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, titulo FROM campanas_simulacion WHERE activa = TRUE ORDER BY titulo")
        simulaciones = cur.fetchall()
        cur.close()
        conn.close()
    except:
        simulaciones = []
    return render_template('admin/carta_evento_form.html', carta={'efectos': {}}, simulaciones=simulaciones)

@app.route('/admin/carta_evento/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_carta_evento_editar(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if request.method == 'POST':
            titulo = request.form.get('titulo')
            descripcion = request.form.get('descripcion')
            icono = request.form.get('icono', 'bolt')
            tipo = request.form.get('tipo', 'sorpresa')
            mensaje_visible = request.form.get('mensaje_visible')
            probabilidad = float(request.form.get('probabilidad', 15)) / 100
            activa = 1 if request.form.get('activa') else 0
            campana_id = request.form.get('campana_id')
            if campana_id == '':
                campana_id = None
            escenas_validas = request.form.get('escenas_validas')
            if escenas_validas:
                try:
                    if escenas_validas.startswith('['):
                        escenas_validas = json.loads(escenas_validas)
                    else:
                        escenas_validas = [int(x.strip()) for x in escenas_validas.split(',') if x.strip()]
                    escenas_validas = json.dumps(escenas_validas)
                except:
                    escenas_validas = None
            else:
                escenas_validas = None
            efectos = {}
            if request.form.get('efecto_participacion'):
                efectos['Participacion'] = int(request.form.get('efecto_participacion'))
            if request.form.get('efecto_confianza'):
                efectos['Confianza'] = int(request.form.get('efecto_confianza'))
            if request.form.get('efecto_educacion'):
                efectos['Educacion'] = int(request.form.get('efecto_educacion'))
            if request.form.get('efecto_seguridad'):
                efectos['Seguridad'] = int(request.form.get('efecto_seguridad'))
            if request.form.get('efecto_economia'):
                efectos['Economia'] = int(request.form.get('efecto_economia'))
            cur.execute("""
                UPDATE cartas_evento 
                SET titulo = %s, descripcion = %s, icono = %s, tipo = %s, 
                    efectos = %s, mensaje_visible = %s, probabilidad = %s, 
                    activa = %s, campana_id = %s, escenas_validas = %s
                WHERE id = %s
            """, (titulo, descripcion, icono, tipo, json.dumps(efectos), mensaje_visible, 
                  probabilidad, activa, campana_id, escenas_validas, id))
            conn.commit()
            cur.close()
            conn.close()
            flash('✅ Carta actualizada', 'success')
            return redirect(url_for('admin_cartas_evento'))
        cur.execute("SELECT * FROM cartas_evento WHERE id = %s", (id,))
        carta = cur.fetchone()
        cur.execute("SELECT id, titulo FROM campanas_simulacion WHERE activa = TRUE ORDER BY titulo")
        simulaciones = cur.fetchall()
        cur.close()
        conn.close()
        if carta:
            if carta.get('efectos'):
                if isinstance(carta['efectos'], str):
                    try:
                        carta['efectos'] = json.loads(carta['efectos'])
                    except:
                        carta['efectos'] = {}
                elif not isinstance(carta['efectos'], dict):
                    carta['efectos'] = {}
            else:
                carta['efectos'] = {}
            if carta.get('escenas_validas'):
                if isinstance(carta['escenas_validas'], str):
                    try:
                        carta['escenas_validas'] = json.loads(carta['escenas_validas'])
                    except:
                        carta['escenas_validas'] = []
                elif not isinstance(carta['escenas_validas'], list):
                    carta['escenas_validas'] = []
            else:
                carta['escenas_validas'] = []
        return render_template('admin/carta_evento_form.html', carta=carta, simulaciones=simulaciones)
    except Exception as e:
        flash('Error al editar la carta', 'danger')
        return redirect(url_for('admin_cartas_evento'))

@app.route('/admin/carta_evento/eliminar/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_carta_evento_eliminar(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM cartas_evento WHERE id = %s", (id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- ADMIN: RUTAS ALTERNATIVAS ---

@app.route('/admin/rutas_alternativas')
@login_required
@admin_required
def admin_rutas_alternativas():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT r.*, c.titulo as carta_titulo, c.icono as carta_icono
            FROM rutas_alternativas r
            LEFT JOIN cartas_evento c ON r.carta_id = c.id
            ORDER BY r.id DESC
        """)
        rutas = cur.fetchall()
        cur.close()
        conn.close()
    except:
        rutas = []
    return render_template('admin/rutas_alternativas.html', rutas=rutas)

@app.route('/admin/ruta_alternativa/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_ruta_alternativa_nueva():
    if request.method == 'POST':
        try:
            carta_id = request.form.get('carta_id')
            escena_id = request.form.get('escena_id')
            nuevo_contexto = request.form.get('nuevo_contexto')
            nuevo_problema = request.form.get('nuevo_problema')
            siguiente_escena = request.form.get('siguiente_escena')
            opciones = []
            opcion1_texto = request.form.get('opcion1_texto')
            if opcion1_texto:
                opcion = {'texto': opcion1_texto}
                consecuencias = {}
                if request.form.get('opcion1_participacion'):
                    consecuencias['Participacion'] = int(request.form.get('opcion1_participacion'))
                if request.form.get('opcion1_confianza'):
                    consecuencias['Confianza'] = int(request.form.get('opcion1_confianza'))
                if request.form.get('opcion1_educacion'):
                    consecuencias['Educacion'] = int(request.form.get('opcion1_educacion'))
                if request.form.get('opcion1_seguridad'):
                    consecuencias['Seguridad'] = int(request.form.get('opcion1_seguridad'))
                if request.form.get('opcion1_economia'):
                    consecuencias['Economia'] = int(request.form.get('opcion1_economia'))
                if consecuencias:
                    opcion['consecuencias'] = consecuencias
                opciones.append(opcion)
            opcion2_texto = request.form.get('opcion2_texto')
            if opcion2_texto:
                opcion = {'texto': opcion2_texto}
                consecuencias = {}
                if request.form.get('opcion2_participacion'):
                    consecuencias['Participacion'] = int(request.form.get('opcion2_participacion'))
                if request.form.get('opcion2_confianza'):
                    consecuencias['Confianza'] = int(request.form.get('opcion2_confianza'))
                if request.form.get('opcion2_educacion'):
                    consecuencias['Educacion'] = int(request.form.get('opcion2_educacion'))
                if request.form.get('opcion2_seguridad'):
                    consecuencias['Seguridad'] = int(request.form.get('opcion2_seguridad'))
                if request.form.get('opcion2_economia'):
                    consecuencias['Economia'] = int(request.form.get('opcion2_economia'))
                if consecuencias:
                    opcion['consecuencias'] = consecuencias
                opciones.append(opcion)
            opcion3_texto = request.form.get('opcion3_texto')
            if opcion3_texto:
                opcion = {'texto': opcion3_texto}
                consecuencias = {}
                if request.form.get('opcion3_participacion'):
                    consecuencias['Participacion'] = int(request.form.get('opcion3_participacion'))
                if request.form.get('opcion3_confianza'):
                    consecuencias['Confianza'] = int(request.form.get('opcion3_confianza'))
                if request.form.get('opcion3_educacion'):
                    consecuencias['Educacion'] = int(request.form.get('opcion3_educacion'))
                if request.form.get('opcion3_seguridad'):
                    consecuencias['Seguridad'] = int(request.form.get('opcion3_seguridad'))
                if request.form.get('opcion3_economia'):
                    consecuencias['Economia'] = int(request.form.get('opcion3_economia'))
                if consecuencias:
                    opcion['consecuencias'] = consecuencias
                opciones.append(opcion)
            if not opciones:
                flash('Debes agregar al menos una opción', 'danger')
                return render_template('admin/ruta_alternativa_form.html')
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO rutas_alternativas 
                (carta_id, escena_id, nuevo_contexto, nuevo_problema, opciones, siguiente_escena)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (carta_id, escena_id, nuevo_contexto, nuevo_problema, json.dumps(opciones), siguiente_escena))
            conn.commit()
            cur.close()
            conn.close()
            flash('✅ Ruta alternativa creada', 'success')
            return redirect(url_for('admin_rutas_alternativas'))
        except Exception as e:
            flash('Error al crear la ruta', 'danger')
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, titulo, icono FROM cartas_evento WHERE activa = TRUE")
        cartas = cur.fetchall()
        cur.close()
        conn.close()
    except:
        cartas = []
    return render_template('admin/ruta_alternativa_form.html', cartas=cartas, ruta=None)

@app.route('/admin/ruta_alternativa/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_ruta_alternativa_editar(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if request.method == 'POST':
            carta_id = request.form.get('carta_id')
            escena_id = request.form.get('escena_id')
            nuevo_contexto = request.form.get('nuevo_contexto')
            nuevo_problema = request.form.get('nuevo_problema')
            siguiente_escena = request.form.get('siguiente_escena')
            opciones = []
            opcion1_texto = request.form.get('opcion1_texto')
            if opcion1_texto:
                opcion = {'texto': opcion1_texto}
                consecuencias = {}
                if request.form.get('opcion1_participacion'):
                    consecuencias['Participacion'] = int(request.form.get('opcion1_participacion'))
                if request.form.get('opcion1_confianza'):
                    consecuencias['Confianza'] = int(request.form.get('opcion1_confianza'))
                if request.form.get('opcion1_educacion'):
                    consecuencias['Educacion'] = int(request.form.get('opcion1_educacion'))
                if request.form.get('opcion1_seguridad'):
                    consecuencias['Seguridad'] = int(request.form.get('opcion1_seguridad'))
                if request.form.get('opcion1_economia'):
                    consecuencias['Economia'] = int(request.form.get('opcion1_economia'))
                if consecuencias:
                    opcion['consecuencias'] = consecuencias
                opciones.append(opcion)
            opcion2_texto = request.form.get('opcion2_texto')
            if opcion2_texto:
                opcion = {'texto': opcion2_texto}
                consecuencias = {}
                if request.form.get('opcion2_participacion'):
                    consecuencias['Participacion'] = int(request.form.get('opcion2_participacion'))
                if request.form.get('opcion2_confianza'):
                    consecuencias['Confianza'] = int(request.form.get('opcion2_confianza'))
                if request.form.get('opcion2_educacion'):
                    consecuencias['Educacion'] = int(request.form.get('opcion2_educacion'))
                if request.form.get('opcion2_seguridad'):
                    consecuencias['Seguridad'] = int(request.form.get('opcion2_seguridad'))
                if request.form.get('opcion2_economia'):
                    consecuencias['Economia'] = int(request.form.get('opcion2_economia'))
                if consecuencias:
                    opcion['consecuencias'] = consecuencias
                opciones.append(opcion)
            opcion3_texto = request.form.get('opcion3_texto')
            if opcion3_texto:
                opcion = {'texto': opcion3_texto}
                consecuencias = {}
                if request.form.get('opcion3_participacion'):
                    consecuencias['Participacion'] = int(request.form.get('opcion3_participacion'))
                if request.form.get('opcion3_confianza'):
                    consecuencias['Confianza'] = int(request.form.get('opcion3_confianza'))
                if request.form.get('opcion3_educacion'):
                    consecuencias['Educacion'] = int(request.form.get('opcion3_educacion'))
                if request.form.get('opcion3_seguridad'):
                    consecuencias['Seguridad'] = int(request.form.get('opcion3_seguridad'))
                if request.form.get('opcion3_economia'):
                    consecuencias['Economia'] = int(request.form.get('opcion3_economia'))
                if consecuencias:
                    opcion['consecuencias'] = consecuencias
                opciones.append(opcion)
            cur.execute("""
                UPDATE rutas_alternativas 
                SET carta_id = %s, escena_id = %s, nuevo_contexto = %s, 
                    nuevo_problema = %s, opciones = %s, siguiente_escena = %s
                WHERE id = %s
            """, (carta_id, escena_id, nuevo_contexto, nuevo_problema, json.dumps(opciones), siguiente_escena, id))
            conn.commit()
            cur.close()
            conn.close()
            flash('✅ Ruta alternativa actualizada', 'success')
            return redirect(url_for('admin_rutas_alternativas'))
        cur.execute("SELECT * FROM rutas_alternativas WHERE id = %s", (id,))
        ruta = cur.fetchone()
        cur.execute("SELECT id, titulo, icono FROM cartas_evento WHERE activa = TRUE")
        cartas = cur.fetchall()
        cur.close()
        conn.close()
        if ruta and ruta['opciones']:
            ruta['opciones'] = json.loads(ruta['opciones']) if isinstance(ruta['opciones'], str) else ruta['opciones']
        return render_template('admin/ruta_alternativa_form.html', ruta=ruta, cartas=cartas)
    except Exception as e:
        flash('Error al editar la ruta', 'danger')
        return redirect(url_for('admin_rutas_alternativas'))

@app.route('/admin/ruta_alternativa/eliminar/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_ruta_alternativa_eliminar(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM rutas_alternativas WHERE id = %s", (id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- ADMIN: PROPUESTAS ---

@app.route('/admin/propuestas')
@login_required
@admin_required
def admin_propuestas():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT p.*, a.nombre AS autoridad_nombre, a.apellido_paterno AS autoridad_apellido
            FROM propuestas p
            JOIN autoridades a ON p.autoridad_id = a.id
            ORDER BY p.created_at DESC
        """)
        propuestas = cur.fetchall()
        cur.close()
        conn.close()
    except:
        propuestas = []
    return render_template('admin/propuestas.html', propuestas=propuestas)

@app.route('/admin/propuesta/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_propuesta_nueva():
    if request.method == 'POST':
        autoridad_id = request.form.get('autoridad_id')
        titulo = request.form.get('titulo')
        descripcion = request.form.get('descripcion')
        explicacion = request.form.get('explicacion')
        impacto_personal = request.form.get('impacto_personal')
        estado = request.form.get('estado', 'Borrador')
        fecha_publicacion = request.form.get('fecha_publicacion') or None
        fuente_oficial = request.form.get('fuente_oficial')
        if not autoridad_id or not titulo or not descripcion:
            flash('Autoridad, título y descripción son obligatorios', 'danger')
            return redirect(url_for('admin_propuesta_nueva'))
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO propuestas 
                (autoridad_id, titulo, descripcion, explicacion, impacto_personal, estado, fecha_publicacion, fuente_oficial)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (autoridad_id, titulo, descripcion, explicacion, impacto_personal, estado, fecha_publicacion, fuente_oficial))
            conn.commit()
            cur.close()
            conn.close()
            flash('✅ Propuesta creada', 'success')
            return redirect(url_for('admin_propuestas'))
        except Exception as e:
            flash(f'Error: {e}', 'danger')
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, nombre, apellido_paterno, cargo FROM autoridades WHERE activo = 1 ORDER BY nombre")
        autoridades = cur.fetchall()
        cur.close()
        conn.close()
    except:
        autoridades = []
    return render_template('admin/propuesta_form.html', autoridades=autoridades, propuesta=None)

@app.route('/admin/propuesta/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_propuesta_editar(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if request.method == 'POST':
            autoridad_id = request.form.get('autoridad_id')
            titulo = request.form.get('titulo')
            descripcion = request.form.get('descripcion')
            explicacion = request.form.get('explicacion')
            impacto_personal = request.form.get('impacto_personal')
            estado = request.form.get('estado', 'Borrador')
            fecha_publicacion = request.form.get('fecha_publicacion') or None
            fuente_oficial = request.form.get('fuente_oficial')
            cur.execute("""
                UPDATE propuestas 
                SET autoridad_id = %s, titulo = %s, descripcion = %s, explicacion = %s, 
                    impacto_personal = %s, estado = %s, fecha_publicacion = %s, fuente_oficial = %s
                WHERE id = %s
            """, (autoridad_id, titulo, descripcion, explicacion, impacto_personal, estado, fecha_publicacion, fuente_oficial, id))
            conn.commit()
            cur.close()
            conn.close()
            flash('✅ Propuesta actualizada', 'success')
            return redirect(url_for('admin_propuestas'))
        cur.execute("SELECT * FROM propuestas WHERE id = %s", (id,))
        propuesta = cur.fetchone()
        cur.execute("SELECT id, nombre, apellido_paterno, cargo FROM autoridades WHERE activo = 1 ORDER BY nombre")
        autoridades = cur.fetchall()
        cur.close()
        conn.close()
        return render_template('admin/propuesta_form.html', propuesta=propuesta, autoridades=autoridades)
    except Exception as e:
        flash('Error al editar', 'danger')
        return redirect(url_for('admin_propuestas'))

@app.route('/admin/propuesta/eliminar/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_propuesta_eliminar(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM propuestas WHERE id = %s", (id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- ADMIN: NOTICIAS ---

@app.route('/admin/noticias')
@login_required
@admin_required
def admin_noticias():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM noticias ORDER BY fecha_publicacion DESC")
        noticias = cur.fetchall()
        cur.close()
        conn.close()
    except:
        noticias = []
    return render_template('admin/noticias.html', noticias=noticias)

@app.route('/admin/noticia/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_noticia_nueva():
    if request.method == 'POST':
        try:
            titulo = request.form.get('titulo', '').strip()
            descripcion = request.form.get('descripcion', '').strip()
            contenido = request.form.get('contenido', '').strip()
            por_que_importa = request.form.get('por_que_importa', '').strip()
            como_te_afecta = request.form.get('como_te_afecta', '').strip()
            contexto = request.form.get('contexto', '').strip()
            fecha = request.form.get('fecha')
            icono = request.form.get('icono', 'newspaper')
            url = request.form.get('url', '').strip() or None
            categoria = request.form.get('categoria', '').strip() or None
            imagen = None
            activa = 1 if request.form.get('activa') else 0
            destacada = 1 if request.form.get('destacada') else 0

            # Prioridad 1: archivo subido
            if 'imagen_archivo' in request.files:
                file = request.files['imagen_archivo']
                if file and file.filename and allowed_file(file.filename):
                    nombre_seguro = secure_filename(file.filename)
                    nombre_final = f"noticia_{datetime.now().strftime('%Y%m%d%H%M%S')}_{nombre_seguro}"
                    carpeta = os.path.join(app.config['UPLOAD_FOLDER'], 'noticias')
                    os.makedirs(carpeta, exist_ok=True)
                    file.save(os.path.join(carpeta, nombre_final))
                    imagen = f"uploads/noticias/{nombre_final}"

            # Prioridad 2: URL externa
            if not imagen:
                url_img = request.form.get('imagen_url', '').strip()
                if url_img:
                    imagen = url_img

            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO noticias (
                    titulo, descripcion, contenido, por_que_importa, como_te_afecta,
                    contexto, fecha, icono, url, categoria, imagen, activa, destacada
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (titulo, descripcion, contenido, por_que_importa, como_te_afecta,
                  contexto, fecha, icono, url, categoria, imagen, activa, destacada))
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Noticia creada!', 'success')
            return redirect(url_for('admin_noticias'))
        except Exception as e:
            print(f"admin_noticia_nueva: {e}")
            flash(f'Error al crear: {e}', 'danger')
    return render_template('admin/noticia_form.html', noticia=None)

@app.route('/admin/noticia/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_noticia_editar(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if request.method == 'POST':
            titulo = request.form.get('titulo', '').strip()
            descripcion = request.form.get('descripcion', '').strip()
            contenido = request.form.get('contenido', '').strip()
            por_que_importa = request.form.get('por_que_importa', '').strip()
            como_te_afecta = request.form.get('como_te_afecta', '').strip()
            contexto = request.form.get('contexto', '').strip()
            fecha = request.form.get('fecha')
            icono = request.form.get('icono', 'newspaper')
            url = request.form.get('url', '').strip() or None
            categoria = request.form.get('categoria', '').strip() or None
            activa = 1 if request.form.get('activa') else 0
            destacada = 1 if request.form.get('destacada') else 0

            # Obtener imagen actual
            cur.execute("SELECT imagen FROM noticias WHERE id = %s", (id,))
            actual = cur.fetchone()
            imagen = actual['imagen'] if actual else None

            # Prioridad: archivo subido
            if 'imagen_archivo' in request.files:
                file = request.files['imagen_archivo']
                if file and file.filename and allowed_file(file.filename):
                    # Borrar imagen anterior si era local
                    if imagen and not imagen.startswith('http'):
                        ruta_vieja = os.path.join(app.config['UPLOAD_FOLDER'], imagen.replace('uploads/', ''))
                        if os.path.exists(ruta_vieja):
                            os.remove(ruta_vieja)
                    nombre_seguro = secure_filename(file.filename)
                    nombre_final = f"noticia_{datetime.now().strftime('%Y%m%d%H%M%S')}_{nombre_seguro}"
                    carpeta = os.path.join(app.config['UPLOAD_FOLDER'], 'noticias')
                    os.makedirs(carpeta, exist_ok=True)
                    file.save(os.path.join(carpeta, nombre_final))
                    imagen = f"uploads/noticias/{nombre_final}"

            # Si pegaron URL
            url_img = request.form.get('imagen_url', '').strip()
            if url_img:
                imagen = url_img

            # Si marcaron "quitar imagen"
            if request.form.get('quitar_imagen'):
                if imagen and not imagen.startswith('http'):
                    ruta_vieja = os.path.join(app.config['UPLOAD_FOLDER'], imagen.replace('uploads/', ''))
                    if os.path.exists(ruta_vieja):
                        os.remove(ruta_vieja)
                imagen = None

            cur.execute("""
                UPDATE noticias
                SET titulo=%s, descripcion=%s, contenido=%s, por_que_importa=%s,
                    como_te_afecta=%s, contexto=%s, fecha=%s, icono=%s, url=%s,
                    categoria=%s, imagen=%s, activa=%s, destacada=%s
                WHERE id=%s
            """, (titulo, descripcion, contenido, por_que_importa, como_te_afecta,
                  contexto, fecha, icono, url, categoria, imagen, activa, destacada, id))
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Noticia actualizada!', 'success')
            return redirect(url_for('admin_noticias'))

        cur.execute("SELECT * FROM noticias WHERE id = %s", (id,))
        noticia = cur.fetchone()
        cur.close()
        conn.close()
        return render_template('admin/noticia_form.html', noticia=noticia)
    except Exception as e:
        print(f"admin_noticia_editar: {e}")
        flash(f'Error al editar: {e}', 'danger')
        return redirect(url_for('admin_noticias'))

@app.route('/admin/noticia/eliminar/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_noticia_eliminar(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM noticias WHERE id = %s", (id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- ADMIN: AUTORIDADES ---

@app.route('/admin/autoridades')
@login_required
@admin_required
def admin_autoridades():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT a.*, ta.nombre as tipo_autoridad
            FROM autoridades a
            LEFT JOIN tipos_autoridad ta ON a.tipo_autoridad_id = ta.id
            ORDER BY a.prioridad DESC
        """)
        autoridades = cur.fetchall()
        cur.close()
        conn.close()
    except:
        autoridades = []
    return render_template('admin/autoridades.html', autoridades=autoridades)

@app.route('/admin/autoridad/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_autoridad_nueva():
    if request.method == 'POST':
        try:
            nombre = request.form.get('nombre')
            apellido_paterno = request.form.get('apellido_paterno')
            cargo = request.form.get('cargo')
            tipo_autoridad_id = request.form.get('tipo_autoridad_id', 1)
            partido = request.form.get('partido')
            descripcion_cargo = request.form.get('descripcion_cargo')
            biografia = request.form.get('biografia')
            activo = 1 if request.form.get('activo') else 0
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO autoridades (nombre, apellido_paterno, cargo, tipo_autoridad_id, partido, descripcion_cargo, biografia, activo)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (nombre, apellido_paterno, cargo, tipo_autoridad_id, partido, descripcion_cargo, biografia, activo))
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Autoridad creada!', 'success')
            return redirect(url_for('admin_autoridades'))
        except Exception as e:
            flash('Error al crear la autoridad', 'danger')
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM tipos_autoridad")
        tipos = cur.fetchall()
        cur.close()
        conn.close()
    except:
        tipos = []
    return render_template('admin/autoridad_form.html', autoridad=None, tipos=tipos)

@app.route('/admin/autoridad/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_autoridad_editar(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if request.method == 'POST':
            nombre = request.form.get('nombre')
            apellido_paterno = request.form.get('apellido_paterno')
            cargo = request.form.get('cargo')
            tipo_autoridad_id = request.form.get('tipo_autoridad_id', 1)
            partido = request.form.get('partido')
            descripcion_cargo = request.form.get('descripcion_cargo')
            biografia = request.form.get('biografia')
            activo = 1 if request.form.get('activo') else 0
            cur.execute("""
                UPDATE autoridades 
                SET nombre = %s, apellido_paterno = %s, cargo = %s, tipo_autoridad_id = %s, 
                    partido = %s, descripcion_cargo = %s, biografia = %s, activo = %s
                WHERE id = %s
            """, (nombre, apellido_paterno, cargo, tipo_autoridad_id, partido, descripcion_cargo, biografia, activo, id))
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Autoridad actualizada!', 'success')
            return redirect(url_for('admin_autoridades'))
        cur.execute("SELECT * FROM autoridades WHERE id = %s", (id,))
        autoridad = cur.fetchone()
        cur.execute("SELECT * FROM tipos_autoridad")
        tipos = cur.fetchall()
        cur.close()
        conn.close()
        return render_template('admin/autoridad_form.html', autoridad=autoridad, tipos=tipos)
    except Exception as e:
        flash('Error al editar', 'danger')
        return redirect(url_for('admin_autoridades'))

@app.route('/admin/autoridad/eliminar/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_autoridad_eliminar(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM autoridades WHERE id = %s", (id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# === RUTA DE SUBIDA DE FOTOS (ÚNICA, SIN DUPLICAR) ===
@app.route('/admin/autoridad/<int:id>/subir_foto', methods=['POST'])
@login_required
@admin_required
def admin_autoridad_subir_foto(id):
    if 'foto' not in request.files:
        return jsonify({'error': 'No se seleccionó ningún archivo'}), 400
    file = request.files['foto']
    if file.filename == '':
        return jsonify({'error': 'No se seleccionó ningún archivo'}), 400
    if not allowed_file(file.filename):
        return jsonify({'error': 'Formato no permitido'}), 400
    try:
        filename = secure_filename(file.filename)
        extension = filename.rsplit('.', 1)[1].lower()
        nuevo_nombre = f"autoridad_{id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{extension}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'autoridades', nuevo_nombre)
        file.save(file_path)
        ruta_guardada = f"uploads/autoridades/{nuevo_nombre}"
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE autoridades SET foto = %s WHERE id = %s", (ruta_guardada, id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'foto': url_for('static', filename=ruta_guardada)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/autoridad/<int:id>/eliminar_foto', methods=['POST'])
@login_required
@admin_required
def admin_autoridad_eliminar_foto(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT foto FROM autoridades WHERE id = %s", (id,))
        autoridad = cur.fetchone()
        if autoridad and autoridad['foto']:
            ruta_completa = os.path.join(app.config['UPLOAD_FOLDER'], autoridad['foto'].replace('uploads/', ''))
            if os.path.exists(ruta_completa):
                os.remove(ruta_completa)
            cur.execute("UPDATE autoridades SET foto = NULL WHERE id = %s", (id,))
            conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- ADMIN: TAREAS ---

@app.route('/admin/tareas')
@login_required
@admin_required
def admin_tareas():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM tareas ORDER BY fecha_creacion DESC")
        tareas = cur.fetchall()
        cur.close()
        conn.close()
    except:
        tareas = []
    return render_template('admin/tareas.html', tareas=tareas)

@app.route('/admin/tarea/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_tarea_nueva():
    if request.method == 'POST':
        titulo = request.form.get('titulo')
        descripcion = request.form.get('descripcion')
        archivo_url = None
        if 'archivo' in request.files:
            file = request.files['archivo']
            if file and file.filename != '' and allowed_file(file.filename):
                nombre_seguro = secure_filename(file.filename)
                nombre_final = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{nombre_seguro}"
                ruta_guardado = os.path.join(app.config['UPLOAD_FOLDER'], 'tareas', nombre_final)
                file.save(ruta_guardado)
                archivo_url = f'/uploads/tareas/{nombre_final}'
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO tareas (titulo, descripcion, archivo_url, creado_por) VALUES (%s, %s, %s, %s)", (titulo, descripcion, archivo_url, current_user.id))
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Tarea creada!', 'success')
            return redirect(url_for('admin_tareas'))
        except Exception as e:
            flash(f'Error: {e}', 'danger')
    return render_template('admin/tarea_form.html', tarea=None)

@app.route('/admin/tarea/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_tarea_editar(id):
    if request.method == 'POST':
        titulo = request.form.get('titulo')
        descripcion = request.form.get('descripcion')
        archivo_url = None
        if 'archivo' in request.files:
            file = request.files['archivo']
            if file and file.filename != '' and allowed_file(file.filename):
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT archivo_url FROM tareas WHERE id = %s", (id,))
                tarea_old = cur.fetchone()
                if tarea_old and tarea_old['archivo_url']:
                    ruta_old = os.path.join(app.config['UPLOAD_FOLDER'], 'tareas', tarea_old['archivo_url'].split('/')[-1])
                    if os.path.exists(ruta_old):
                        os.remove(ruta_old)
                cur.close()
                conn.close()
                nombre_seguro = secure_filename(file.filename)
                nombre_final = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{nombre_seguro}"
                ruta_guardado = os.path.join(app.config['UPLOAD_FOLDER'], 'tareas', nombre_final)
                file.save(ruta_guardado)
                archivo_url = f'/uploads/tareas/{nombre_final}'
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            if archivo_url:
                cur.execute("UPDATE tareas SET titulo=%s, descripcion=%s, archivo_url=%s WHERE id=%s", (titulo, descripcion, archivo_url, id))
            else:
                cur.execute("UPDATE tareas SET titulo=%s, descripcion=%s WHERE id=%s", (titulo, descripcion, id))
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Tarea actualizada!', 'success')
            return redirect(url_for('admin_tareas'))
        except Exception as e:
            flash(f'Error: {e}', 'danger')
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM tareas WHERE id = %s", (id,))
        tarea = cur.fetchone()
        cur.close()
        conn.close()
        return render_template('admin/tarea_form.html', tarea=tarea)
    except:
        flash('Error al cargar la tarea', 'danger')
        return redirect(url_for('admin_tareas'))

@app.route('/admin/tarea/eliminar/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_tarea_eliminar(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM tareas WHERE id = %s", (id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- ADMIN: USUARIOS ---

@app.route('/admin/usuarios')
@login_required
@super_admin_required
def admin_usuarios():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT u.*, tu.nombre as tipo_usuario
            FROM usuarios u
            LEFT JOIN tipos_usuario tu ON u.tipo_usuario_id = tu.id
            ORDER BY u.id DESC
        """)
        usuarios = cur.fetchall()
        cur.close()
        conn.close()
    except:
        usuarios = []
    return render_template('admin/usuarios.html', usuarios=usuarios)

@app.route('/admin/usuario/cambiar_tipo/<int:id>', methods=['POST'])
@login_required
@super_admin_required
def admin_usuario_cambiar_tipo(id):
    if id == current_user.id:
        return jsonify({'error': 'No puedes cambiar tu propio rol'}), 400
    data = request.json
    tipo_usuario_id = data.get('tipo_usuario_id')
    if not tipo_usuario_id or int(tipo_usuario_id) not in [1, 2, 3, 4, 5]:
        return jsonify({'error': 'Tipo de usuario inválido'}), 400
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM usuarios WHERE id = %s", (id,))
        if not cur.fetchone():
            return jsonify({'error': 'Usuario no encontrado'}), 404
        cur.execute("UPDATE usuarios SET tipo_usuario_id = %s WHERE id = %s", (tipo_usuario_id, id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/usuario/cambiar_rol/<int:id>', methods=['POST'])
@login_required
@super_admin_required
def admin_usuario_cambiar_rol(id):
    return admin_usuario_cambiar_tipo(id)

@app.route('/admin/usuario/bloquear/<int:id>', methods=['POST'])
@login_required
@super_admin_required
def admin_usuario_bloquear(id):
    if id == current_user.id:
        return jsonify({'error': 'No puedes bloquearte a ti mismo'}), 400
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT activo FROM usuarios WHERE id = %s", (id,))
        user = cur.fetchone()
        if not user:
            return jsonify({'error': 'Usuario no encontrado'}), 404
        nuevo_estado = 0 if user['activo'] else 1
        cur.execute("UPDATE usuarios SET activo = %s WHERE id = %s", (nuevo_estado, id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'activo': nuevo_estado})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/usuario/eliminar/<int:id>', methods=['POST'])
@login_required
@super_admin_required
def admin_usuario_eliminar(id):
    if id == current_user.id:
        return jsonify({'error': 'No puedes eliminarte a ti mismo'}), 400
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT tipo_usuario_id FROM usuarios WHERE id = %s", (id,))
        user = cur.fetchone()
        if not user:
            return jsonify({'error': 'Usuario no encontrado'}), 404
        if user['tipo_usuario_id'] == 1:
            return jsonify({'error': 'No puedes eliminar a otro Super Admin'}), 400
        cur.execute("DELETE FROM usuarios WHERE id = %s", (id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ======================== FORO ========================

import re
from markupsafe import Markup, escape

# ---------- Utilidades ----------
def sanitizar_markdown(texto):
    """Convierte un subconjunto seguro de markdown a HTML. Escapa todo lo demás."""
    if not texto:
        return ''
    t = str(escape(texto))
    # Enlaces [texto](url) — solo http/https
    t = re.sub(
        r'\[([^\]]+)\]\((https?://[^\s)]+)\)',
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
        t
    )
    # Negrita **texto**
    t = re.sub(r'\*\*([^\*]+)\*\*', r'<strong>\1</strong>', t)
    # Cursiva *texto*
    t = re.sub(r'(?<!\*)\*([^\*]+)\*(?!\*)', r'<em>\1</em>', t)
    # Imágenes ![alt](url)
    t = re.sub(
        r'!\[([^\]]*)\]\((https?://[^\s)]+)\)',
        r'<img src="\2" alt="\1" class="img-fluid rounded my-2" loading="lazy">',
        t
    )
    # Saltos de línea
    t = t.replace('\n', '<br>')
    return Markup(t)


# ↓↓↓ ESTA LÍNEA VA APARTE, SIN SANGRÍA ↓↓↓
app.jinja_env.globals['sanitizar_markdown'] = sanitizar_markdown


def contar_votos(tema_id=None, respuesta_id=None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if tema_id:
            cur.execute("SELECT COALESCE(SUM(CASE WHEN tipo='up' THEN 1 WHEN tipo='down' THEN -1 END),0) AS total FROM foro_votos WHERE tema_id=%s", (tema_id,))
        else:
            cur.execute("SELECT COALESCE(SUM(CASE WHEN tipo='up' THEN 1 WHEN tipo='down' THEN -1 END),0) AS total FROM foro_votos WHERE respuesta_id=%s", (respuesta_id,))
        r = cur.fetchone()
        cur.close(); conn.close()
        return int(r['total']) if r else 0
    except Exception as e:
        print(f"contar_votos: {e}")
        return 0


def notificar_usuario(usuario_id, tipo, mensaje, enlace=None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO foro_notificaciones (usuario_id, tipo, mensaje, enlace) VALUES (%s,%s,%s,%s)",
            (usuario_id, tipo, mensaje[:250], enlace)
        )
        conn.commit(); cur.close(); conn.close()
        return True
    except Exception as e:
        print(f"notificar_usuario: {e}")
        return False


def _es_admin(user):
    return user.is_authenticated and user.is_admin_or_super


def _puede_editar(user, autor_id, estado='activo'):
    """Autor puede editar mientras no esté oculto. Admin siempre."""
    if not user.is_authenticated:
        return False
    if _es_admin(user):
        return True
    return user.id == autor_id and estado != 'oculto'


# ---------- Listado principal ----------
@app.route('/foro')
def foro_index():
    page       = request.args.get('page', 1, type=int)
    per_page   = 10
    categoria  = request.args.get('categoria', '', type=str)
    buscar     = request.args.get('q', '', type=str).strip()
    orden      = request.args.get('orden', 'recientes', type=str)

    if page < 1:
        page = 1

    orden_sql = {
        'recientes':  't.created_at DESC',
        'comentados': 'total_respuestas DESC, t.created_at DESC',
        'actividad':  'COALESCE(ultima_actividad, t.created_at) DESC',
        'vistos':     't.vistas DESC, t.created_at DESC',
    }.get(orden, 't.created_at DESC')

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Categorías para el sidebar
        cur.execute("SELECT * FROM foro_categorias WHERE activa=1 ORDER BY orden")
        categorias = cur.fetchall()

        # Filtros
        where = ["t.estado = 'activo'"]
        params = []
        if categoria:
            where.append("c.slug = %s")
            params.append(categoria)
        if buscar:
            where.append("(t.titulo LIKE %s OR t.contenido LIKE %s)")
            params.extend([f'%{buscar}%', f'%{buscar}%'])

        where_sql = " AND ".join(where)

        # Consulta de temas
        sql = f"""
            SELECT t.*,
                   u.nombre AS autor_nombre,
                   u.foto_perfil AS autor_foto,
                   c.nombre AS categoria_nombre,
                   c.slug   AS categoria_slug,
                   c.color  AS categoria_color,
                   c.icono  AS categoria_icono,
                   (SELECT COUNT(*) FROM foro_respuestas r
                      WHERE r.tema_id = t.id AND r.estado='activo') AS total_respuestas,
                   (SELECT COALESCE(SUM(CASE WHEN tipo='up' THEN 1 WHEN tipo='down' THEN -1 END),0)
                      FROM foro_votos WHERE tema_id = t.id) AS votos,
                   (SELECT MAX(created_at) FROM foro_respuestas r
                      WHERE r.tema_id = t.id AND r.estado='activo') AS ultima_actividad
            FROM foro_temas t
            JOIN usuarios u       ON t.usuario_id = u.id
            JOIN foro_categorias c ON t.categoria_id = c.id
            WHERE {where_sql}
            ORDER BY t.fijado DESC, {orden_sql}
            LIMIT %s OFFSET %s
        """
        cur.execute(sql, params + [per_page, (page - 1) * per_page])
        temas = cur.fetchall()

        # Total para paginación
        cur.execute(f"""
            SELECT COUNT(*) AS total
            FROM foro_temas t
            JOIN foro_categorias c ON t.categoria_id = c.id
            WHERE {where_sql}
        """, params)
        total = cur.fetchone()['total']

        # Estadísticas laterales
        cur.execute("SELECT COUNT(*) AS c FROM foro_temas WHERE estado='activo'")
        total_temas = cur.fetchone()['c']
        cur.execute("SELECT COUNT(*) AS c FROM foro_respuestas WHERE estado='activo'")
        total_resp = cur.fetchone()['c']
        cur.execute("SELECT COUNT(*) AS c FROM usuarios WHERE activo=1")
        total_users = cur.fetchone()['c']

        # Notificaciones sin leer
        no_leidas = 0
        if current_user.is_authenticated:
            cur.execute(
                "SELECT COUNT(*) AS c FROM foro_notificaciones WHERE usuario_id=%s AND leido=0",
                (current_user.id,)
            )
            no_leidas = cur.fetchone()['c']

        cur.close(); conn.close()

        total_paginas = (total + per_page - 1) // per_page if total else 0

        return render_template(
            'foro/index.html',
            temas=temas,
            categorias=categorias,
            categoria_actual=categoria,
            buscar=buscar,
            orden=orden,
            page=page,
            total_paginas=total_paginas,
            total_temas=total_temas,
            total_respuestas=total_resp,
            total_usuarios=total_users,
            no_leidas=no_leidas,
            sanitizar_markdown=sanitizar_markdown,
        )

    except Exception as e:
        print(f"foro_index: {e}")
        import traceback; traceback.print_exc()
        flash('Error al cargar el foro', 'danger')
        return render_template(
            'foro/index.html',
            temas=[], categorias=[], categoria_actual='', buscar='',
            orden='recientes', page=1, total_paginas=0,
            total_temas=0, total_respuestas=0, total_usuarios=0,
            no_leidas=0, sanitizar_markdown=sanitizar_markdown,
        )


# ---------- Crear tema ----------
@app.route('/foro/nuevo', methods=['GET', 'POST'])
@login_required
def foro_nuevo_tema():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM foro_categorias WHERE activa=1 ORDER BY orden")
        categorias = cur.fetchall()
        cur.close(); conn.close()
    except Exception:
        categorias = []

    if request.method == 'POST':
        titulo = request.form.get('titulo', '').strip()
        contenido = request.form.get('contenido', '').strip()
        categoria_id = request.form.get('categoria_id', type=int)
        noticia_id = request.form.get('noticia_id', type=int)

        # Validaciones servidor
        if not titulo or len(titulo) < 5:
            flash('El título debe tener al menos 5 caracteres', 'danger')
            return render_template('foro/nuevo.html', categorias=categorias, noticias=obtener_noticias_activas())
        if len(titulo) > 150:
            flash('El título no puede superar 150 caracteres', 'danger')
            return render_template('foro/nuevo.html', categorias=categorias, noticias=obtener_noticias_activas())
        if not contenido or len(contenido) < 15:
            flash('El contenido debe tener al menos 15 caracteres', 'danger')
            return render_template('foro/nuevo.html', categorias=categorias, noticias=obtener_noticias_activas())
        if len(contenido) > 8000:
            flash('El contenido es demasiado largo (máx 8000 caracteres)', 'danger')
            return render_template('foro/nuevo.html', categorias=categorias, noticias=obtener_noticias_activas())
        if not categoria_id:
            flash('Debes elegir una categoría', 'danger')
            return render_template('foro/nuevo.html', categorias=categorias, noticias=obtener_noticias_activas())

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT id FROM foro_categorias WHERE id=%s AND activa=1", (categoria_id,))
            if not cur.fetchone():
                flash('Categoría inválida', 'danger')
                cur.close(); conn.close()
                return render_template('foro/nuevo.html', categorias=categorias, noticias=obtener_noticias_activas())

            cur.execute("""
                INSERT INTO foro_temas (titulo, contenido, usuario_id, categoria_id, noticia_id)
                VALUES (%s,%s,%s,%s,%s)
            """, (titulo, contenido, current_user.id, categoria_id, noticia_id or None))
            conn.commit()
            tema_id = cur.lastrowid
            cur.close(); conn.close()
            flash('✅ Tema creado correctamente', 'success')
            return redirect(url_for('foro_ver_tema', tema_id=tema_id))
        except Exception as e:
            print(f"foro_nuevo_tema: {e}")
            flash('Error al crear el tema', 'danger')

    return render_template('foro/nuevo.html', categorias=categorias,
                           noticias=obtener_noticias_activas())


# ---------- Ver tema ----------
@app.route('/foro/tema/<int:tema_id>')
def foro_ver_tema(tema_id):
    page = request.args.get('page', 1, type=int)
    per_page = 20
    if page < 1: page = 1

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("UPDATE foro_temas SET vistas = vistas + 1 WHERE id = %s", (tema_id,))
        conn.commit()

        cur.execute("""
            SELECT t.*, u.nombre AS autor_nombre, u.foto_perfil AS autor_foto,
                   c.nombre AS categoria_nombre, c.slug AS categoria_slug,
                   c.color AS categoria_color, c.icono AS categoria_icono
            FROM foro_temas t
            JOIN usuarios u        ON t.usuario_id = u.id
            JOIN foro_categorias c ON t.categoria_id = c.id
            WHERE t.id = %s
        """, (tema_id,))
        tema = cur.fetchone()

        if not tema:
            flash('Tema no encontrado', 'danger')
            cur.close(); conn.close()
            return redirect(url_for('foro_index'))

        # Visibilidad: oculto solo admin/autor
        if tema['estado'] == 'oculto' and not (
            current_user.is_authenticated and
            (_es_admin(current_user) or current_user.id == tema['usuario_id'])
        ):
            flash('Este tema no está disponible', 'warning')
            cur.close(); conn.close()
            return redirect(url_for('foro_index'))

                # Cargar TODAS las respuestas activas del tema (una sola consulta)
        cur.execute("""
            SELECT r.*, u.nombre AS autor_nombre, u.foto_perfil AS autor_foto,
                   (SELECT COALESCE(SUM(CASE WHEN tipo='up' THEN 1 WHEN tipo='down' THEN -1 END),0)
                      FROM foro_votos WHERE respuesta_id = r.id) AS votos
            FROM foro_respuestas r
            JOIN usuarios u ON r.usuario_id = u.id
            WHERE r.tema_id = %s AND r.estado='activo'
            ORDER BY r.created_at ASC
        """, (tema_id,))
        todas_respuestas = cur.fetchall()

        # Construir árbol en memoria (soporta N niveles)
        respuestas_por_id = {r['id']: r for r in todas_respuestas}
        for r in todas_respuestas:
            r['respuestas_hijas'] = []
        raices = []
        for r in todas_respuestas:
            padre = r.get('respuesta_padre_id')
            if padre and padre in respuestas_por_id:
                respuestas_por_id[padre]['respuestas_hijas'].append(r)
            else:
                raices.append(r)

        # Paginación a nivel de raíces (los hijos van con su padre)
        total_respuestas = len(todas_respuestas)
        total_raices = len(raices)
        inicio = (page - 1) * per_page
        respuestas = raices[inicio:inicio + per_page]
        total_paginas = (total_raices + per_page - 1) // per_page if total_raices else 0

        # Voto del usuario actual
        voto_usuario = {'tema': None, 'respuestas': {}}
        if current_user.is_authenticated:
            cur.execute("SELECT tipo FROM foro_votos WHERE tema_id=%s AND usuario_id=%s",
                        (tema_id, current_user.id))
            v = cur.fetchone()
            voto_usuario['tema'] = v['tipo'] if v else None

            if respuestas:
                ids = [r['id'] for r in respuestas]
                fmt = ','.join(['%s'] * len(ids))
                cur.execute(
                    f"SELECT respuesta_id, tipo FROM foro_votos WHERE usuario_id=%s AND respuesta_id IN ({fmt})",
                    [current_user.id] + ids
                )
                for row in cur.fetchall():
                    voto_usuario['respuestas'][row['respuesta_id']] = row['tipo']

        votos_tema = contar_votos(tema_id=tema_id)
        cur.close(); conn.close()

        return render_template(
            'foro/tema.html',
            tema=tema,
            respuestas=respuestas,
            votos_tema=votos_tema,
            voto_usuario=voto_usuario,
            total_respuestas=total_respuestas,
            page=page,
            total_paginas=total_paginas,
            sanitizar_markdown=sanitizar_markdown,
        )

    except Exception as e:
        print(f"foro_ver_tema: {e}")
        import traceback; traceback.print_exc()
        flash('Error al cargar el tema', 'danger')
        return redirect(url_for('foro_index'))


# ---------- Responder ----------
@app.route('/foro/tema/<int:tema_id>/responder', methods=['POST'])
@login_required
def foro_responder(tema_id):
    contenido = request.form.get('contenido', '').strip()
    padre_id = request.form.get('respuesta_padre_id', type=int)

    if not contenido or len(contenido) < 2:
        flash('La respuesta está vacía', 'danger')
        return redirect(url_for('foro_ver_tema', tema_id=tema_id))
    if len(contenido) > 5000:
        flash('La respuesta es demasiado larga (máx 5000)', 'danger')
        return redirect(url_for('foro_ver_tema', tema_id=tema_id))

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT id, estado, usuario_id, titulo FROM foro_temas WHERE id=%s", (tema_id,))
        tema = cur.fetchone()
        if not tema:
            flash('Tema no encontrado', 'danger')
            cur.close(); conn.close()
            return redirect(url_for('foro_index'))

        if tema['estado'] == 'cerrado' and not _es_admin(current_user):
            flash('Este tema está cerrado', 'warning')
            cur.close(); conn.close()
            return redirect(url_for('foro_ver_tema', tema_id=tema_id))

        if tema['estado'] == 'oculto' and not _es_admin(current_user):
            flash('Tema no disponible', 'warning')
            cur.close(); conn.close()
            return redirect(url_for('foro_index'))

        if padre_id:
            cur.execute("SELECT id FROM foro_respuestas WHERE id=%s AND tema_id=%s AND estado='activo'",
                        (padre_id, tema_id))
            if not cur.fetchone():
                padre_id = None

        cur.execute("""
            INSERT INTO foro_respuestas (tema_id, usuario_id, contenido, respuesta_padre_id)
            VALUES (%s,%s,%s,%s)
        """, (tema_id, current_user.id, contenido, padre_id))
        conn.commit()
        nueva_id = cur.lastrowid

        # Notificar al autor del tema
        if tema['usuario_id'] != current_user.id:
            enlace = url_for('foro_ver_tema', tema_id=tema_id, _external=True) + f"#respuesta-{nueva_id}"
            notificar_usuario(
                tema['usuario_id'],
                'respuesta',
                f"{current_user.nombre} respondió a tu tema: {tema['titulo']}",
                enlace=enlace
            )

        cur.close(); conn.close()
        flash('✅ Respuesta publicada', 'success')
        return redirect(url_for('foro_ver_tema', tema_id=tema_id) + f"#respuesta-{nueva_id}")

    except Exception as e:
        print(f"foro_responder: {e}")
        flash('Error al responder', 'danger')
        return redirect(url_for('foro_ver_tema', tema_id=tema_id))


# ---------- Editar tema ----------
@app.route('/foro/tema/<int:tema_id>/editar', methods=['GET', 'POST'])
@login_required
def foro_editar_tema(tema_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM foro_temas WHERE id=%s", (tema_id,))
        tema = cur.fetchone()

        if not tema:
            flash('Tema no encontrado', 'danger')
            cur.close(); conn.close()
            return redirect(url_for('foro_index'))

        if not _puede_editar(current_user, tema['usuario_id'], tema['estado']):
            flash('No puedes editar este tema', 'danger')
            cur.close(); conn.close()
            return redirect(url_for('foro_ver_tema', tema_id=tema_id))

        if request.method == 'POST':
            titulo = request.form.get('titulo', '').strip()
            contenido = request.form.get('contenido', '').strip()
            categoria_id = request.form.get('categoria_id', type=int)

            if not titulo or len(titulo) < 5 or len(titulo) > 150:
                flash('Título inválido', 'danger')
                return redirect(url_for('foro_editar_tema', tema_id=tema_id))
            if not contenido or len(contenido) < 15 or len(contenido) > 8000:
                flash('Contenido inválido', 'danger')
                return redirect(url_for('foro_editar_tema', tema_id=tema_id))

            cur.execute("""
                UPDATE foro_temas SET titulo=%s, contenido=%s, categoria_id=%s
                WHERE id=%s
            """, (titulo, contenido, categoria_id or tema['categoria_id'], tema_id))
            conn.commit()
            cur.close(); conn.close()
            flash('✅ Tema actualizado', 'success')
            return redirect(url_for('foro_ver_tema', tema_id=tema_id))

        cur.execute("SELECT * FROM foro_categorias WHERE activa=1 ORDER BY orden")
        categorias = cur.fetchall()
        cur.close(); conn.close()
        return render_template('foro/editar.html', tipo='tema', tema=tema, categorias=categorias)

    except Exception as e:
        print(f"foro_editar_tema: {e}")
        flash('Error al editar', 'danger')
        return redirect(url_for('foro_index'))


# ---------- Editar respuesta ----------
@app.route('/foro/respuesta/<int:respuesta_id>/editar', methods=['GET', 'POST'])
@login_required
def foro_editar_respuesta(respuesta_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM foro_respuestas WHERE id=%s", (respuesta_id,))
        resp = cur.fetchone()

        if not resp:
            flash('Respuesta no encontrada', 'danger')
            cur.close(); conn.close()
            return redirect(url_for('foro_index'))

        if not _puede_editar(current_user, resp['usuario_id'], resp['estado']):
            flash('No puedes editar esta respuesta', 'danger')
            cur.close(); conn.close()
            return redirect(url_for('foro_ver_tema', tema_id=resp['tema_id']))

        if request.method == 'POST':
            contenido = request.form.get('contenido', '').strip()
            if not contenido or len(contenido) < 2 or len(contenido) > 5000:
                flash('Contenido inválido', 'danger')
                return redirect(url_for('foro_editar_respuesta', respuesta_id=respuesta_id))

            cur.execute("UPDATE foro_respuestas SET contenido=%s WHERE id=%s",
                        (contenido, respuesta_id))
            conn.commit()
            cur.close(); conn.close()
            flash('✅ Respuesta actualizada', 'success')
            return redirect(url_for('foro_ver_tema', tema_id=resp['tema_id']))

        cur.close(); conn.close()
        return render_template('foro/editar.html', tipo='respuesta', respuesta=resp)
    except Exception as e:
        print(f"foro_editar_respuesta: {e}")
        flash('Error al editar', 'danger')
        return redirect(url_for('foro_index'))


# ---------- Eliminar tema ----------
@app.route('/foro/tema/<int:tema_id>/eliminar', methods=['POST'])
@login_required
def foro_eliminar_tema(tema_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT usuario_id FROM foro_temas WHERE id=%s", (tema_id,))
        row = cur.fetchone()

        if not row:
            cur.close(); conn.close()
            return jsonify({'success': False, 'error': 'No encontrado'}), 404

        if not (_es_admin(current_user) or current_user.id == row['usuario_id']):
            cur.close(); conn.close()
            return jsonify({'success': False, 'error': 'Sin permisos'}), 403

        cur.execute("DELETE FROM foro_temas WHERE id=%s", (tema_id,))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- Eliminar respuesta ----------
@app.route('/foro/respuesta/<int:respuesta_id>/eliminar', methods=['POST'])
@login_required
def foro_eliminar_respuesta(respuesta_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT usuario_id FROM foro_respuestas WHERE id=%s", (respuesta_id,))
        row = cur.fetchone()
        if not row:
            cur.close(); conn.close()
            return jsonify({'success': False, 'error': 'No encontrado'}), 404

        if not (_es_admin(current_user) or current_user.id == row['usuario_id']):
            cur.close(); conn.close()
            return jsonify({'success': False, 'error': 'Sin permisos'}), 403

        cur.execute("DELETE FROM foro_respuestas WHERE id=%s", (respuesta_id,))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- Cerrar / reabrir tema (admin) ----------
@app.route('/admin/foro/tema/<int:tema_id>/cerrar', methods=['POST'])
@login_required
@admin_required
def foro_cerrar_tema(tema_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT estado FROM foro_temas WHERE id=%s", (tema_id,))
        row = cur.fetchone()
        if not row:
            cur.close(); conn.close()
            return jsonify({'success': False}), 404
        nuevo = 'activo' if row['estado'] == 'cerrado' else 'cerrado'
        cur.execute("UPDATE foro_temas SET estado=%s WHERE id=%s", (nuevo, tema_id))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({'success': True, 'estado': nuevo})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- Ocultar tema (admin) ----------
@app.route('/admin/foro/tema/<int:tema_id>/ocultar', methods=['POST'])
@login_required
@admin_required
def foro_ocultar_tema(tema_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT estado FROM foro_temas WHERE id=%s", (tema_id,))
        row = cur.fetchone()
        if not row:
            cur.close(); conn.close()
            return jsonify({'success': False}), 404
        nuevo = 'activo' if row['estado'] == 'oculto' else 'oculto'
        cur.execute("UPDATE foro_temas SET estado=%s WHERE id=%s", (nuevo, tema_id))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({'success': True, 'estado': nuevo})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- Reportar ----------
@app.route('/foro/reportar', methods=['POST'])
@login_required
def foro_reportar():
    data = request.get_json(silent=True) or request.form
    tema_id = data.get('tema_id')
    respuesta_id = data.get('respuesta_id')
    motivo = data.get('motivo', '').strip()
    detalle = (data.get('detalle') or '').strip()[:500]

    motivos_validos = {'spam', 'insultos', 'falso', 'acoso', 'inapropiado', 'otro'}
    if motivo not in motivos_validos:
        return jsonify({'success': False, 'error': 'Motivo inválido'}), 400
    if not tema_id and not respuesta_id:
        return jsonify({'success': False, 'error': 'Falta tema o respuesta'}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Evitar reportes duplicados del mismo usuario al mismo objeto
        if tema_id:
            cur.execute("""SELECT id FROM foro_reportes
                           WHERE reportado_por=%s AND tema_id=%s AND estado='pendiente'""",
                        (current_user.id, tema_id))
        else:
            cur.execute("""SELECT id FROM foro_reportes
                           WHERE reportado_por=%s AND respuesta_id=%s AND estado='pendiente'""",
                        (current_user.id, respuesta_id))
        if cur.fetchone():
            cur.close(); conn.close()
            return jsonify({'success': False, 'error': 'Ya reportaste este contenido'}), 400

        cur.execute("""
            INSERT INTO foro_reportes (reportado_por, tema_id, respuesta_id, motivo, detalle)
            VALUES (%s,%s,%s,%s,%s)
        """, (current_user.id, tema_id, respuesta_id, motivo, detalle))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- Votar ----------
@app.route('/foro/votar', methods=['POST'])
@login_required
def foro_votar():
    data = request.get_json(silent=True) or {}
    tipo = data.get('tipo')
    id_item = data.get('id')
    voto = data.get('voto')

    if tipo not in ('tema', 'respuesta') or not id_item or voto not in ('up', 'down'):
        return jsonify({'success': False, 'error': 'Datos inválidos'}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if tipo == 'tema':
            cur.execute("SELECT id FROM foro_temas WHERE id=%s", (id_item,))
            if not cur.fetchone():
                cur.close(); conn.close()
                return jsonify({'success': False, 'error': 'No existe'}), 404
            cur.execute("SELECT id, tipo FROM foro_votos WHERE tema_id=%s AND usuario_id=%s",
                        (id_item, current_user.id))
        else:
            cur.execute("SELECT id FROM foro_respuestas WHERE id=%s", (id_item,))
            if not cur.fetchone():
                cur.close(); conn.close()
                return jsonify({'success': False, 'error': 'No existe'}), 404
            cur.execute("SELECT id, tipo FROM foro_votos WHERE respuesta_id=%s AND usuario_id=%s",
                        (id_item, current_user.id))

        existente = cur.fetchone()

        if existente:
            if existente['tipo'] == voto:
                cur.execute("DELETE FROM foro_votos WHERE id=%s", (existente['id'],))
                accion = 'eliminado'
            else:
                cur.execute("UPDATE foro_votos SET tipo=%s WHERE id=%s", (voto, existente['id']))
                accion = 'cambiado'
        else:
            if tipo == 'tema':
                cur.execute("INSERT INTO foro_votos (tema_id, usuario_id, tipo) VALUES (%s,%s,%s)",
                            (id_item, current_user.id, voto))
            else:
                cur.execute("INSERT INTO foro_votos (respuesta_id, usuario_id, tipo) VALUES (%s,%s,%s)",
                            (id_item, current_user.id, voto))
            accion = 'agregado'

        conn.commit()
        cur.close(); conn.close()

        total = contar_votos(
            tema_id=id_item if tipo == 'tema' else None,
            respuesta_id=id_item if tipo == 'respuesta' else None
        )
        return jsonify({'success': True, 'total': total, 'accion': accion})

    except Exception as e:
        print(f"foro_votar: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- Búsqueda AJAX (para autocompletado simple) ----------
@app.route('/foro/buscar')
def foro_buscar():
    q = request.args.get('q', '', type=str).strip()
    if len(q) < 2:
        return jsonify({'resultados': []})
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT t.id, t.titulo, c.nombre AS categoria
            FROM foro_temas t
            JOIN foro_categorias c ON t.categoria_id = c.id
            WHERE t.estado='activo' AND (t.titulo LIKE %s OR t.contenido LIKE %s)
            ORDER BY t.created_at DESC
            LIMIT 10
        """, (f'%{q}%', f'%{q}%'))
        resultados = cur.fetchall()
        cur.close(); conn.close()
        return jsonify({'resultados': resultados})
    except Exception:
        return jsonify({'resultados': []})


# ---------- Notificaciones ----------
@app.route('/foro/notificaciones')
@login_required
def foro_notificaciones():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM foro_notificaciones
            WHERE usuario_id=%s AND leido=0
            ORDER BY created_at DESC LIMIT 20
        """, (current_user.id,))
        notifs = cur.fetchall()
        cur.close(); conn.close()
        return jsonify({'notificaciones': notifs})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/foro/notificaciones/count')
@login_required
def foro_notificaciones_count():
    """Devuelve SOLO el número de notificaciones no leídas. Ligero para el badge."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS c FROM foro_notificaciones WHERE usuario_id=%s AND leido=0",
            (current_user.id,)
        )
        n = cur.fetchone()['c']
        cur.close(); conn.close()
        return jsonify({'count': n})
    except Exception as e:
        # Devolvemos 200 con 0 para que el frontend nunca rompa
        return jsonify({'count': 0}), 200

@app.route('/foro/notificaciones/marcar_leidas', methods=['POST'])
@login_required
def foro_marcar_leidas():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE foro_notificaciones SET leido=1 WHERE usuario_id=%s AND leido=0",
                    (current_user.id,))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---------- Admin: reportes ----------
@app.route('/admin/foro/reportes')
@login_required
@admin_required
def admin_foro_reportes():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT r.*,
                   u.nombre AS reportador,
                   t.titulo AS tema_titulo,
                   t.id AS tema_id_real,
                   rt.contenido AS respuesta_contenido
            FROM foro_reportes r
            JOIN usuarios u ON r.reportado_por = u.id
            LEFT JOIN foro_temas t       ON r.tema_id = t.id
            LEFT JOIN foro_respuestas rt ON r.respuesta_id = rt.id
            WHERE r.estado = 'pendiente'
            ORDER BY r.created_at ASC
        """)
        reportes = cur.fetchall()
        cur.close(); conn.close()
        return render_template('admin/foro_reportes.html', reportes=reportes)
    except Exception as e:
        print(f"admin_foro_reportes: {e}")
        flash('Error al cargar reportes', 'danger')
        return redirect(url_for('admin_dashboard'))


@app.route('/admin/foro/reporte/<int:reporte_id>/resolver', methods=['POST'])
@login_required
@admin_required
def admin_foro_reporte_resolver(reporte_id):
    data = request.get_json(silent=True) or {}
    accion = data.get('accion')  # 'descartar' o 'sancionar'
    if accion not in ('descartar', 'sancionar'):
        return jsonify({'success': False, 'error': 'Acción inválida'}), 400
    nuevo_estado = 'descartado' if accion == 'descartar' else 'sancionado'
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE foro_reportes
            SET estado=%s, revisado_por=%s, revisado_en=NOW()
            WHERE id=%s
        """, (nuevo_estado, current_user.id, reporte_id))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- Admin: eliminar tema / respuesta ----------
@app.route('/admin/foro/tema/<int:tema_id>/eliminar', methods=['POST'])
@login_required
@admin_required
def admin_foro_eliminar_tema(tema_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM foro_temas WHERE id=%s", (tema_id,))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/admin/foro/respuesta/<int:respuesta_id>/eliminar', methods=['POST'])
@login_required
@admin_required
def admin_foro_eliminar_respuesta(respuesta_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM foro_respuestas WHERE id=%s", (respuesta_id,))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- Admin: CRUD categorías ----------
@app.route('/admin/foro/categorias')
@login_required
@admin_required
def admin_foro_categorias():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM foro_categorias ORDER BY orden")
        cats = cur.fetchall()
        cur.close(); conn.close()
        return render_template('admin/foro_categorias.html', categorias=cats)
    except Exception as e:
        flash('Error al cargar categorías', 'danger')
        return redirect(url_for('admin_dashboard'))


@app.route('/admin/foro/categoria/nueva', methods=['POST'])
@login_required
@admin_required
def admin_foro_categoria_nueva():
    nombre = request.form.get('nombre', '').strip()
    descripcion = request.form.get('descripcion', '').strip()
    icono = request.form.get('icono', 'comments').strip()
    color = request.form.get('color', '#14B8A6').strip()
    if not nombre:
        flash('El nombre es obligatorio', 'danger')
        return redirect(url_for('admin_foro_categorias'))
    slug = re.sub(r'[^a-z0-9]+', '-', nombre.lower()).strip('-')
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO foro_categorias (nombre, slug, descripcion, icono, color, orden)
            VALUES (%s, %s, %s, %s, %s, (SELECT COALESCE(MAX(orden),0)+1 FROM foro_categorias c))
        """, (nombre, slug, descripcion, icono, color))
        conn.commit()
        cur.close(); conn.close()
        flash('✅ Categoría creada', 'success')
    except Exception as e:
        flash(f'Error: {e}', 'danger')
    return redirect(url_for('admin_foro_categorias'))


@app.route('/admin/foro/categoria/<int:cat_id>/eliminar', methods=['POST'])
@login_required
@admin_required
def admin_foro_categoria_eliminar(cat_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM foro_temas WHERE categoria_id=%s", (cat_id,))
        if cur.fetchone()['c'] > 0:
            cur.close(); conn.close()
            return jsonify({'success': False, 'error': 'Hay temas en esta categoría'}), 400
        cur.execute("DELETE FROM foro_categorias WHERE id=%s", (cat_id,))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- Subir imagen foro ----------
@app.route('/foro/subir_imagen', methods=['POST'])
@login_required
def foro_subir_imagen():
    if 'imagen' not in request.files:
        return jsonify({'error': 'No se envió imagen'}), 400
    file = request.files['imagen']
    if file.filename == '':
        return jsonify({'error': 'Archivo vacío'}), 400
    if not allowed_file(file.filename):
        return jsonify({'error': 'Formato no permitido'}), 400
    try:
        filename = secure_filename(file.filename)
        ext = filename.rsplit('.', 1)[1].lower()
        nuevo = f"foro_{current_user.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}"
        ruta = os.path.join(app.config['UPLOAD_FOLDER'], 'foro', nuevo)
        file.save(ruta)
        return jsonify({'success': True, 'url': f'/uploads/foro/{nuevo}'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---------- Helper noticias ----------
def obtener_noticias_activas():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, titulo FROM noticias WHERE activa=1 ORDER BY fecha_publicacion DESC LIMIT 20")
        noticias = cur.fetchall()
        cur.close(); conn.close()
        return noticias
    except Exception:
        return []

# ======================== ERRORES ========================

@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)