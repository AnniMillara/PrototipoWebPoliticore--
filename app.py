from flask import Flask, render_template, redirect, url_for, flash, request, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import os
import json
import sqlite3
from datetime import datetime, date

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-12345')

# ============================================
# CONFIGURACIÓN SQLITE (ya no usa MySQL)
# ============================================
# Las variables de entorno de MySQL se ignoran.
# La base de datos estará en instance/politicore.db
app.config['SQLITE_DB'] = os.path.join(app.instance_path, 'politicore.db')

# Asegurar que la carpeta instance existe
try:
    os.makedirs(app.instance_path, exist_ok=True)
except:
    pass

def get_db_connection():
    """Conecta a la base de datos SQLite"""
    conn = sqlite3.connect(app.config['SQLITE_DB'])
    conn.row_factory = sqlite3.Row  # Permite acceder por nombre de columna
    return conn

# Configuración de Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

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
            from datetime import date
            return date.today() <= date.fromisoformat(self.fecha_expiracion) if isinstance(self.fecha_expiracion, str) else date.today() <= self.fecha_expiracion
        return True

from functools import wraps

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
            cur.execute("SELECT id FROM usuarios WHERE email = ?", (email,))
            if cur.fetchone():
                flash('Este email ya está registrado', 'danger')
                cur.close()
                conn.close()
                return render_template('registro_profesor.html')
            
            if plan == 'anual':
                fecha_expiracion = "date('now', '+365 days')"
                precio = 11000
            else:
                fecha_expiracion = "date('now', '+30 days')"
                precio = 1000
            
            cur.execute(f"""
                INSERT INTO usuarios (
                    tipo_usuario_id, nombre, apellido_paterno, email, password,
                    nivel, xp, activo, es_premium, fecha_suscripcion, fecha_expiracion, plan
                ) VALUES (
                    3, ?, ?, ?, ?,
                    1, 0, 1, 1, date('now'), {fecha_expiracion}, ?
                )
            """, (nombre, '', email, password, plan))
            
            conn.commit()
            cur.close()
            conn.close()
            
            flash(f'✅ ¡Registro exitoso! Premium activado por {precio} CLP', 'success')
            return redirect(url_for('login'))
            
        except Exception as e:
            print(f"Error en registro: {e}")
            flash('Error al registrar usuario', 'danger')
    
    return render_template('registro_profesor.html')

@app.route('/api/simular_pago', methods=['POST'])
def simular_pago():
    data = request.json
    plan = data.get('plan', 'mensual')
    return jsonify({
        'success': True,
        'message': 'Pago simulado exitosamente',
        'plan': plan,
        'precio': 11000 if plan == 'anual' else 1000
    })

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
            SET es_premium = 1,
                fecha_suscripcion = date('now'),
                fecha_expiracion = date('now', '+30 days'),
                plan = 'profesional'
            WHERE id = ?
        """, (current_user.id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'message': '¡Premium activado por $1.000 CLP!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@login_manager.user_loader
def load_user(user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM usuarios WHERE id = ? AND activo = 1", (user_id,))
        user_data = cur.fetchone()
        cur.close()
        conn.close()
        if user_data:
            return User(user_data)
        return None
    except:
        return None

## ========== RUTAS PRINCIPALES ==========

import json
import os

def get_noticias_from_json():
    try:
        json_path = os.path.join(os.path.dirname(__file__), 'data', 'noticias_2026.json')
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('noticias', [])
    except Exception as e:
        print(f"Error cargando noticias: {e}")
        return []

@app.route('/')
def index():
    noticias = get_noticias_from_json()
    if not noticias:
        noticias = [
            {
                'titulo': 'Megarreforma económica avanza en el Senado',
                'descripcion': 'El proyecto de ley que rebaja el impuesto a empresas del 27% al 23% quedó en discusión clave.',
                'fecha': '2026-07-29',
                'icono': 'landmark'
            },
            {
                'titulo': 'Presidente Kast mantiene Estado de Catástrofe en Coquimbo y Huasco',
                'descripcion': 'El mandatario mantiene el Decreto de Excepción tras el temporal que dejó damnificados.',
                'fecha': '2026-07-28',
                'icono': 'cloud-rain'
            },
            {
                'titulo': 'Gobierno refuerza control fronterizo en el norte',
                'descripcion': 'El Ministerio del Interior intensifica la presencia de las Fuerzas Armadas en pasos fronterizos.',
                'fecha': '2026-07-27',
                'icono': 'shield-alt'
            }
        ]
    
    proximas_funciones = [
        {'nombre': 'Elecciones en vivo', 'icono': 'vote-yea'},
        {'nombre': 'Comparador de candidatos', 'icono': 'balance-scale'},
        {'nombre': 'Seguimiento de promesas', 'icono': 'clipboard-check'},
        {'nombre': 'Panel de noticias', 'icono': 'shield-alt'},
        {'nombre': 'Panel para colegios', 'icono': 'school'}
    ]
    
    return render_template('index.html', 
                         noticias_destacadas=noticias[:3],
                         proximas_funciones=proximas_funciones)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM usuarios WHERE email = ? AND activo = 1", (email,))
            user_data = cur.fetchone()
            cur.close()
            conn.close()
            
            if user_data:
                if password == user_data['password']:
                    user = User(user_data)
                    login_user(user)
                    flash(f'¡Bienvenido {user.nombre}!', 'success')
                    if user.is_admin:
                        return redirect(url_for('admin_dashboard'))
                    return redirect(url_for('index'))
                else:
                    flash('Contraseña incorrecta', 'danger')
            else:
                flash('Email no encontrado', 'danger')
        except Exception as e:
            print(f"Error en login: {e}")
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
            cur.execute("SELECT id FROM usuarios WHERE email = ?", (email,))
            if cur.fetchone():
                flash('Este email ya está registrado', 'danger')
                cur.close()
                conn.close()
                return render_template('registro.html')
            
            es_premium = 1 if plan in ['mensual', 'anual'] else 0
            
            if plan == 'anual':
                fecha_expiracion = "date('now', '+365 days')"
            elif plan == 'mensual':
                fecha_expiracion = "date('now', '+30 days')"
            else:
                fecha_expiracion = "NULL"
            
            cur.execute(f"""
                INSERT INTO usuarios (
                    tipo_usuario_id, nombre, apellido_paterno, email, password,
                    nivel, xp, activo, es_premium, fecha_suscripcion, fecha_expiracion, plan
                ) VALUES (
                    ?, ?, ?, ?, ?,
                    1, 0, 1, ?, date('now'), {fecha_expiracion}, ?
                )
            """, (tipo_usuario, nombre, '', email, password, es_premium, plan))
            
            conn.commit()
            cur.close()
            conn.close()
            
            if plan == 'gratis':
                flash('¡Registro exitoso! Comienza a aprender.', 'success')
            else:
                flash(f'✅ ¡Registro exitoso! Premium activado por ${"11.000" if plan == "anual" else "1.000"} CLP (Demo)', 'success')
            
            return redirect(url_for('login'))
            
        except Exception as e:
            print(f"Error en registro: {e}")
            flash('Error al registrar usuario. Intenta nuevamente.', 'danger')
    
    return render_template('registro.html')

# ============================================
# RUTAS PARA ESTUDIANTES - UNIRSE A CLASE
# ============================================

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
            cur.execute("""
                SELECT id, nombre, profesor_id
                FROM salas_clase
                WHERE codigo_acceso = ? AND activa = 1
            """, (codigo,))
            sala = cur.fetchone()
            
            if not sala:
                flash('❌ Código inválido. Verifica con tu profesor.', 'danger')
                cur.close()
                conn.close()
                return render_template('estudiante/unirse.html')
            
            cur.execute("""
                SELECT id FROM sala_alumnos
                WHERE sala_id = ? AND alumno_id = ? AND activo = 1
            """, (sala['id'], current_user.id))
            ya_inscrito = cur.fetchone()
            
            if ya_inscrito:
                flash('✅ Ya estás en esta clase', 'info')
                return redirect(url_for('estudiante_mis_clases'))
            
            cur.execute("""
                INSERT INTO sala_alumnos (sala_id, alumno_id)
                VALUES (?, ?)
            """, (sala['id'], current_user.id))
            
            conn.commit()
            cur.close()
            conn.close()
            
            flash(f'✅ ¡Te has unido a la clase "{sala["nombre"]}"!', 'success')
            return redirect(url_for('estudiante_mis_clases'))
            
        except Exception as e:
            print(f"Error al unirse: {e}")
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
                    WHERE sala_id = s.id AND alumno_id = ? AND completada = 1) as lecciones_completadas
            FROM sala_alumnos sa
            JOIN salas_clase s ON sa.sala_id = s.id
            JOIN usuarios u ON s.profesor_id = u.id
            WHERE sa.alumno_id = ? AND sa.activo = 1
            ORDER BY sa.fecha_ingreso DESC
        """, (current_user.id, current_user.id))
        clases = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error: {e}")
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
            WHERE s.id = ? AND sa.alumno_id = ? AND sa.activo = 1
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
                AND sp.alumno_id = ? AND sp.sala_id = ?
            WHERE l.activo = 1
            ORDER BY l.id
        """, (current_user.id, sala_id))
        progreso = cur.fetchall()
        
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error: {e}")
        flash('Error al cargar la clase', 'danger')
        return redirect(url_for('estudiante_mis_clases'))
    
    return render_template('estudiante/clase_detalle.html', 
                         sala=sala, 
                         progreso=progreso)

# ========== RUTAS DE LECCIONES ==========

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
                LEFT JOIN progreso_lecciones pl ON l.id = pl.leccion_id AND pl.usuario_id = ?
                WHERE l.mundo_id = ? AND l.activo = 1
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
        mundos = [
            {
                'nombre': 'Soy Ciudadano',
                'icono': 'user-graduate',
                'lecciones': [
                    {'id': 1, 'titulo': '¿Qué es un ciudadano?', 'estado': 'disponible', 'progreso': 0, 'xp': 50},
                    {'id': 2, 'titulo': 'Derechos y deberes', 'estado': 'disponible', 'progreso': 0, 'xp': 75},
                ]
            },
            {
                'nombre': 'Cómo funciona Chile',
                'icono': 'landmark',
                'lecciones': [
                    {'id': 3, 'titulo': 'Los tres poderes del Estado', 'estado': 'disponible', 'progreso': 0, 'xp': 80},
                ]
            }
        ]
    
    return render_template('lecciones/index.html', mundos=mundos)

@app.route('/leccion/<int:id>')
def detalle_leccion(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT l.*, ma.nombre as mundo
            FROM lecciones l
            LEFT JOIN mundos_aprendizaje ma ON l.mundo_id = ma.id
            WHERE l.id = ? AND l.activo = 1
        """, (id,))
        leccion = cur.fetchone()
        
        if leccion:
            cur.execute("SELECT * FROM actividades_leccion WHERE leccion_id = ? ORDER BY orden", (id,))
            actividades = cur.fetchall()
            
            if actividades:
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
                leccion['actividad'] = leccion['actividades'][0] if leccion['actividades'] else None
            else:
                leccion['actividades'] = []
                leccion['actividad'] = {
                    'tipo': 'alternativas',
                    'pregunta': '¿Qué aprendiste en esta lección?',
                    'opciones': ['Opción 1', 'Opción 2', 'Opción 3'],
                    'respuesta_correcta': 0,
                    'explicacion': 'Explicación de la respuesta correcta.'
                }
        
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error en detalle_leccion: {e}")
        leccion = {
            'id': id,
            'titulo': 'Lección de ejemplo',
            'icono': 'book',
            'mundo': 'Educación Cívica',
            'situacion_inicial': '¿Alguna vez te has preguntado cómo funciona Chile?',
            'explicacion': 'Chile es una república democrática con tres poderes del Estado: Ejecutivo, Legislativo y Judicial.',
            'ejemplo': 'Cuando votas en una elección, estás participando en el sistema democrático.',
            'historia': 'María, una estudiante de Santiago, descubrió que podía participar en su comunidad.',
            'curiosidad': '¿Sabías que el Congreso Nacional está en Valparaíso?',
            'reflexion': 'La participación ciudadana es clave para una democracia saludable.',
            'xp': 50,
            'actividades': [
                {
                    'tipo': 'alternativas',
                    'pregunta': '¿Qué es la democracia?',
                    'opciones': ['Un sistema donde el pueblo elige a sus representantes', 'Un tipo de gobierno militar', 'Un sistema sin elecciones'],
                    'respuesta_correcta': 0,
                    'explicacion': 'La democracia es un sistema donde los ciudadanos eligen a sus representantes mediante votaciones.'
                }
            ],
            'actividad': {
                'tipo': 'alternativas',
                'pregunta': '¿Qué es la democracia?',
                'opciones': ['Un sistema donde el pueblo elige a sus representantes', 'Un tipo de gobierno militar', 'Un sistema sin elecciones'],
                'respuesta_correcta': 0,
                'explicacion': 'La democracia es un sistema donde los ciudadanos eligen a sus representantes mediante votaciones.'
            }
        }
    
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
        
        cur.execute("SELECT * FROM progreso_lecciones WHERE usuario_id = ? AND leccion_id = ?", 
                   (current_user.id, leccion_id))
        existente = cur.fetchone()
        
        cur.execute("SELECT xp FROM lecciones WHERE id = ?", (leccion_id,))
        leccion = cur.fetchone()
        xp_ganado = leccion['xp'] if leccion else 50
        
        if existente and existente['completada']:
            pass
        else:
            if existente:
                cur.execute("""
                    UPDATE progreso_lecciones
                    SET completada = 1,
                        fecha_completada = datetime('now'),
                        puntaje = 100,
                        intentos = intentos + 1
                    WHERE usuario_id = ? AND leccion_id = ?
                """, (current_user.id, leccion_id))
            else:
                cur.execute("""
                    INSERT INTO progreso_lecciones (usuario_id, leccion_id, completada, puntaje, fecha_completada)
                    VALUES (?, ?, 1, 100, datetime('now'))
                """, (current_user.id, leccion_id))
            
            cur.execute("""
                UPDATE usuarios
                SET xp = xp + ?
                WHERE id = ?
            """, (xp_ganado, current_user.id))
        
        if sala_id_int is not None:
            cur.execute("""
                SELECT id FROM sala_alumnos
                WHERE sala_id = ? AND alumno_id = ? AND activo = 1
            """, (sala_id_int, current_user.id))
            if cur.fetchone():
                cur.execute("""
                    INSERT INTO sala_progreso (sala_id, alumno_id, leccion_id, completada, fecha_completada, puntaje)
                    VALUES (?, ?, ?, 1, datetime('now'), 100)
                    ON CONFLICT(sala_id, alumno_id, leccion_id) DO UPDATE SET
                    completada = 1,
                    fecha_completada = datetime('now'),
                    puntaje = 100
                """, (sala_id_int, current_user.id, leccion_id))
        else:
            cur.execute("""
                SELECT sala_id FROM sala_alumnos
                WHERE alumno_id = ? AND activo = 1
            """, (current_user.id,))
            salas = cur.fetchall()
            if salas:
                for row in salas:
                    sala_id_alumno = row['sala_id']
                    cur.execute("""
                        INSERT INTO sala_progreso (sala_id, alumno_id, leccion_id, completada, fecha_completada, puntaje)
                        VALUES (?, ?, ?, 1, datetime('now'), 100)
                        ON CONFLICT(sala_id, alumno_id, leccion_id) DO UPDATE SET
                        completada = 1,
                        fecha_completada = datetime('now'),
                        puntaje = 100
                    """, (sala_id_alumno, current_user.id, leccion_id))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({'success': True, 'xp': xp_ganado})
        
    except Exception as e:
        print(f"❌ Error completar lección: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})

# ============================================
# RUTAS DE SIMULACIÓN - COMPLETAS
# ============================================

import random
import json

def get_carta_evento_aleatoria(campana_id=None, escena_actual=None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        query = """
            SELECT * FROM cartas_evento
            WHERE activa = 1
        """
        params = []
        
        if campana_id:
            query += " AND (campana_id = ? OR campana_id IS NULL)"
            params.append(campana_id)
        else:
            query += " AND campana_id IS NULL"
        
        if escena_actual is not None:
            query += """ AND (
                escenas_validas IS NULL
                OR JSON_EXTRACT(escenas_validas, '$') LIKE ?
            )"""
            params.append(f'%{escena_actual}%')  # Aproximación para SQLite
        
        query += " ORDER BY RANDOM() LIMIT 1"
        
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
        print(f"Error obteniendo carta evento: {e}")
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
        cur.execute("""
            SELECT id FROM progreso_simulacion
            WHERE usuario_id = ? AND campana_id = ?
        """, (current_user.id, campana_id))
        existente = cur.fetchone()
        
        if not isinstance(indicadores, dict):
            indicadores = {'Participacion': 50, 'Confianza': 50, 'Educacion': 50, 'Seguridad': 50, 'Economia': 50}
        
        for key in indicadores:
            indicadores[key] = max(0, min(100, indicadores.get(key, 50)))
        
        indicadores_json = json.dumps(indicadores)
        
        if existente:
            cur.execute("""
                UPDATE progreso_simulacion
                SET indicadores = ?,
                    escena_actual = ?,
                    updated_at = datetime('now')
                WHERE usuario_id = ? AND campana_id = ?
            """, (indicadores_json, escena_actual, current_user.id, campana_id))
        else:
            cur.execute("""
                INSERT INTO progreso_simulacion
                (usuario_id, campana_id, escena_actual, indicadores, fecha_inicio)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (current_user.id, campana_id, escena_actual, indicadores_json))
        
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Error guardando indicadores: {e}")
        return False

def get_ruta_alternativa(carta_id, escena_actual):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM rutas_alternativas
            WHERE carta_id = ? AND escena_id = ?
        """, (carta_id, escena_actual))
        ruta = cur.fetchone()
        cur.close()
        conn.close()
        if ruta and ruta.get('opciones'):
            ruta['opciones'] = json.loads(ruta['opciones']) if isinstance(ruta['opciones'], str) else ruta['opciones']
        return ruta
    except Exception as e:
        print(f"Error obteniendo ruta alternativa: {e}")
        return None

@app.route('/simulacion')
def simulacion():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM campanas_simulacion WHERE activa = 1 ORDER BY id")
        campanas = cur.fetchall()
        cur.close()
        conn.close()
    except:
        campanas = [
            {'id': 1, 'titulo': 'Soy Ciudadano', 'descripcion': 'Participa en tu primera experiencia cívica', 'dificultad': 'Intermedio'},
            {'id': 2, 'titulo': 'Presupuesto Municipal', 'descripcion': 'Toma decisiones sobre el presupuesto de tu comuna', 'dificultad': 'Avanzado'}
        ]
    return render_template('simulacion/index.html', campanas=campanas)

@app.route('/simulacion/<int:id>')
@login_required
def simulacion_jugar(id):
    escena_id = request.args.get('escena', 1)
    ruta_activa = request.args.get('ruta', None)
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM campanas_simulacion WHERE id = ? AND activa = 1", (id,))
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
                    campana['escenas'].append({
                        'id': i,
                        'tipo': 'decision' if i % 2 == 1 else 'evento',
                        'contexto': f'Situación {i}: Describe el contexto aquí.',
                        'opciones': [
                            {'texto': f'Opción 1 para la situación {i}'},
                            {'texto': f'Opción 2 para la situación {i}'},
                            {'texto': f'Opción 3 para la situación {i}'}
                        ]
                    })
        else:
            campana = get_simulacion_ejemplo(id)
    except:
        campana = get_simulacion_ejemplo(id)
    
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
            cur.execute("SELECT * FROM rutas_alternativas WHERE id = ?", (ruta_activa,))
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
        return render_template('simulacion/jugar.html', 
                             campana=campana,
                             escena=escena_final,
                             escena_actual=escena_actual,
                             total_escenas=total_escenas,
                             indicadores=indicadores,
                             carta_evento=carta_evento if mostrar_carta else None,
                             ruta_alternativa=ruta_alternativa)
    
    return render_template('simulacion/jugar.html', 
                         campana=campana,
                         escena=escena,
                         escena_actual=escena_actual,
                         total_escenas=total_escenas,
                         indicadores=indicadores,
                         carta_evento=carta_evento if mostrar_carta else None,
                         ruta_alternativa=ruta_alternativa)

# ============================================
# FUNCIONES AUXILIARES
# ============================================

def get_simulacion_ejemplo(id):
    return {
        'id': id,
        'titulo': 'Soy Ciudadano: El camino hacia la participación',
        'descripcion': 'Vive una experiencia de 10 rondas donde tus decisiones definirán tu perfil como ciudadano',
        'introduccion': {
            'contexto': 'Eres un estudiante de último año que acaba de ser elegido Presidente del Centro de Estudiantes.',
            'personajes': [
                {'nombre': 'Sra. Patricia', 'rol': 'Directora', 'opinion': 'Quiere mantener el orden establecido'},
                {'nombre': 'Javier', 'rol': 'Estudiante', 'opinion': 'Quiere cambios radicales'},
                {'nombre': 'Prof. Ramírez', 'rol': 'Profesor', 'opinion': 'Cree en el diálogo y el consenso'}
            ],
            'objetivo': 'Gestionar el Centro de Estudiantes tomando decisiones que equilibren los intereses de todos'
        },
        'escenas': [
            {'id': 1, 'tipo': 'decision', 'contexto': 'Tu primera semana como Presidente. Los estudiantes te piden organizar una manifestación para exigir mejoras en la infraestructura del colegio. La Directora te llama a su oficina.', 'opciones': [
                {'texto': 'Organizar la manifestación, los estudiantes tienen razón'},
                {'texto': 'Buscar un diálogo con la Directora antes de decidir'},
                {'texto': 'Pedir más información antes de tomar una decisión'}
            ]},
            {'id': 2, 'tipo': 'decision', 'contexto': 'La Directora te propone formar una comisión mixta para abordar los problemas. Los estudiantes quieren respuestas inmediatas.', 'opciones': [
                {'texto': 'Aceptar la propuesta y formar la comisión'},
                {'texto': 'Rechazar y seguir con la manifestación'},
                {'texto': 'Proponer una votación entre los estudiantes'}
            ]},
            {'id': 3, 'tipo': 'decision', 'contexto': 'La comisión se reúne por primera vez. Los representantes tienen posturas muy diferentes. El ambiente es tenso.', 'opciones': [
                {'texto': 'Impulsar un debate abierto y respetuoso'},
                {'texto': 'Tomar el control y proponer tu plan'},
                {'texto': 'Sugerir un receso para calmar los ánimos'}
            ]},
            {'id': 4, 'tipo': 'decision', 'contexto': 'El colegio recibe una inspección del Ministerio de Educación. Los resultados no son buenos.', 'opciones': [
                {'texto': 'Organizar un plan de mejora con los estudiantes'},
                {'texto': 'Pedir ayuda a los profesores experimentados'},
                {'texto': 'Solicitar recursos adicionales al Ministerio'}
            ]},
            {'id': 5, 'tipo': 'evento', 'contexto': '📢 ¡ALERTA! Un video viral en redes sociales muestra a un estudiante criticando la gestión. Los medios quieren entrevistarte.'},
            {'id': 6, 'tipo': 'decision', 'contexto': 'El periodista te pregunta sobre las críticas. ¿Cómo respondes?', 'opciones': [
                {'texto': 'Reconocer los errores y comprometerte a mejorar'},
                {'texto': 'Defender tu gestión y destacar los logros'},
                {'texto': 'Pasar la responsabilidad a la Directora'}
            ]},
            {'id': 7, 'tipo': 'decision', 'contexto': 'Los estudiantes te piden tomar postura sobre la reforma educativa que discute el gobierno.', 'opciones': [
                {'texto': 'Apoyar la reforma'},
                {'texto': 'Criticar la reforma'},
                {'texto': 'Organizar un debate informativo'}
            ]},
            {'id': 8, 'tipo': 'decision', 'contexto': 'El presupuesto del Centro de Estudiantes es limitado. ¿Cómo lo gastas?', 'opciones': [
                {'texto': 'Invertir en actividades recreativas'},
                {'texto': 'Invertir en materiales educativos'},
                {'texto': 'Ahorrar para un proyecto más grande'}
            ]},
            {'id': 9, 'tipo': 'decision', 'contexto': 'Un grupo de estudiantes organiza una protesta pacífica. La Directora quiere que la disuelvas.', 'opciones': [
                {'texto': 'Unirte a la protesta'},
                {'texto': 'Mediar entre estudiantes y Directora'},
                {'texto': 'Pedir que se retiren y buscar diálogo'}
            ]},
            {'id': 10, 'tipo': 'decision', 'contexto': 'Es tu último mes como Presidente. ¿Qué legado quieres dejar?', 'opciones': [
                {'texto': 'Una cultura de participación y diálogo'},
                {'texto': 'Mejoras concretas en infraestructura'},
                {'texto': 'Fortalecer la relación con la comunidad'}
            ]}
        ],
        'finales': [
            {'titulo': 'El Conciliador', 'condiciones': {'Confianza': '> 50', 'Participacion': '> 50'}, 
             'texto': 'Lograste unir a todos los actores de la comunidad escolar.',
             'reflexion': 'La democracia se construye con diálogo y consenso. Supiste escuchar a todos y encontrar puntos en común.'},
            {'titulo': 'El Reformista', 'condiciones': {'Educacion': '> 50', 'Participacion': '> 40'},
             'texto': 'Implementaste cambios innovadores en el sistema educativo.',
             'reflexion': 'El cambio es posible cuando hay visión y determinación. No tuviste miedo de desafiar el status quo.'},
            {'titulo': 'El Popular', 'condiciones': {'Participacion': '> 60', 'Confianza': '> 40'},
             'texto': 'Ganaste el apoyo de la mayoría de los estudiantes.',
             'reflexion': 'La popularidad no es suficiente para gobernar bien, pero sin ella es difícil implementar cambios.'},
            {'titulo': 'El Administrador', 'condiciones': {'Confianza': '> 50', 'Seguridad': '> 40'},
             'texto': 'Lograste una gestión eficiente y ordenada.',
             'reflexion': 'La buena administración es la base de cualquier gobierno. Supiste priorizar y organizar.'},
            {'titulo': 'El Visionario', 'condiciones': {'Educacion': '> 60', 'Confianza': '> 50'},
             'texto': 'Tuviste una visión clara del futuro y trabajaste para alcanzarla.',
             'reflexion': 'Los grandes cambios empiezan con una visión. Supiste inspirar a otros a seguirte.'}
        ]
    }

def get_indicadores_actuales(campana_id, escena_actual, campana):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT indicadores FROM progreso_simulacion
            WHERE usuario_id = ? AND campana_id = ?
        """, (current_user.id, campana_id))
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
    except Exception as e:
        print(f"⚠️ Error cargando indicadores: {e}")
    
    dificultad = campana.get('dificultad', 'Intermedio')
    if dificultad == 'Básico':
        return {'Participacion': 60, 'Confianza': 60, 'Educacion': 60, 'Seguridad': 60, 'Economia': 60}
    elif dificultad == 'Avanzado':
        return {'Participacion': 35, 'Confianza': 35, 'Educacion': 35, 'Seguridad': 35, 'Economia': 35}
    else:
        return {'Participacion': 50, 'Confianza': 50, 'Educacion': 50, 'Seguridad': 50, 'Economia': 50}

def calcular_final(finales, indicadores):
    final_por_defecto = {
        'titulo': 'El Ciudadano Activo', 
        'texto': 'Completaste tu camino como ciudadano. Cada decisión que tomaste fue parte de tu aprendizaje.', 
        'reflexion': 'La democracia no es un destino, es un camino que se construye día a día con cada decisión. Tu participación importa.'
    }
    if not finales:
        return final_por_defecto
    if isinstance(finales, str):
        try:
            finales = json.loads(finales)
        except:
            return final_por_defecto
    if not finales or not isinstance(finales, list):
        return final_por_defecto
    
    mejor_final = finales[0] if finales else final_por_defecto
    mejor_puntaje = 0
    
    for final in finales:
        if not isinstance(final, dict):
            continue
        puntaje = 0
        condiciones = final.get('condiciones', {})
        if isinstance(condiciones, str):
            try:
                condiciones = json.loads(condiciones)
            except:
                condiciones = {}
        if isinstance(condiciones, dict):
            for key, cond in condiciones.items():
                valor_actual = indicadores.get(key, 50)
                if isinstance(cond, str):
                    if cond.startswith('>'):
                        try:
                            umbral = int(cond[1:])
                            if valor_actual > umbral:
                                puntaje += 2
                        except:
                            pass
                    elif cond.startswith('<'):
                        try:
                            umbral = int(cond[1:])
                            if valor_actual < umbral:
                                puntaje += 2
                        except:
                            pass
                elif isinstance(cond, (int, float)):
                    if valor_actual >= cond:
                        puntaje += 1
        if puntaje > mejor_puntaje:
            mejor_puntaje = puntaje
            mejor_final = final
    
    if not isinstance(mejor_final, dict):
        return final_por_defecto
    if 'titulo' not in mejor_final:
        mejor_final['titulo'] = final_por_defecto['titulo']
    if 'texto' not in mejor_final:
        mejor_final['texto'] = final_por_defecto['texto']
    if 'reflexion' not in mejor_final:
        mejor_final['reflexion'] = final_por_defecto['reflexion']
    return mejor_final

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
        cur.execute("SELECT escenas, dificultad FROM campanas_simulacion WHERE id = ?", (campana_id,))
        result = cur.fetchone()
        if not result:
            return jsonify({'next_scene': next_scene})
        
        escenas = json.loads(result['escenas']) if result['escenas'] else []
        escena_actual = next((e for e in escenas if e.get('id') == int(escena_id)), None)
        if not escena_actual or not escena_actual.get('opciones') or len(escena_actual['opciones']) <= opcion:
            return jsonify({'next_scene': next_scene})
        
        opcion_data = escena_actual['opciones'][opcion]
        consecuencias = opcion_data.get('consecuencias', {})
        
        cur.execute("SELECT indicadores FROM progreso_simulacion WHERE usuario_id = ? AND campana_id = ?", 
                   (current_user.id, campana_id))
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
                except (ValueError, TypeError) as e:
                    print(f"⚠️ Error en {key}: {value} - {e}")
        
        if progreso:
            cur.execute("""
                UPDATE progreso_simulacion
                SET escena_actual = ?, indicadores = ?, updated_at = datetime('now')
                WHERE usuario_id = ? AND campana_id = ?
            """, (next_scene, json.dumps(indicadores), current_user.id, campana_id))
        else:
            cur.execute("""
                INSERT INTO progreso_simulacion (usuario_id, campana_id, escena_actual, indicadores)
                VALUES (?, ?, ?, ?)
            """, (current_user.id, campana_id, next_scene, json.dumps(indicadores)))
        
        conn.commit()
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    return jsonify({'next_scene': next_scene})

@app.route('/api/procesar_evento_simulacion', methods=['POST'])
@login_required
def procesar_evento_simulacion():
    data = request.json
    escena_id = data.get('escena_id')
    next_scene = int(escena_id) + 1
    return jsonify({'next_scene': next_scene})

# ========== RUTAS DE PERFIL ==========

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
            WHERE u.id = ?
        """, (current_user.id,))
        usuario = cur.fetchone()
        
        cur.execute("""
            SELECT COUNT(*) as total
            FROM progreso_lecciones
            WHERE usuario_id = ? AND completada = 1
        """, (current_user.id,))
        completadas = cur.fetchone()
        
        insignias = []
        
        cur.close()
        conn.close()
        
        return render_template('perfil/index.html', 
                             usuario=usuario, 
                             completadas=completadas['total'] if completadas else 0,
                             insignias=insignias)
    except Exception as e:
        print(f"Error en perfil: {e}")
        usuario = {
            'nombre': current_user.nombre,
            'apellido_paterno': current_user.apellido_paterno,
            'email': current_user.email,
            'nivel': current_user.nivel,
            'xp': current_user.xp,
            'tipo_usuario': 'Estudiante'
        }
        completadas = 0
        insignias = []
        return render_template('perfil/index.html', 
                             usuario=usuario, 
                             completadas=completadas,
                             insignias=insignias)

# ============================================
# CONFIGURACIÓN DE SUBIDA DE ARCHIVOS
# ============================================

import os
from werkzeug.utils import secure_filename
from flask import send_from_directory

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'zip', 'rar'}

os.makedirs(os.path.join(UPLOAD_FOLDER, 'autoridades'), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, 'perfiles'), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, 'tareas'), exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/api/subir_foto_perfil', methods=['POST'])
@login_required
def subir_foto_perfil():
    if 'foto' not in request.files:
        return jsonify({'error': 'No se seleccionó ningún archivo'}), 400
    file = request.files['foto']
    if file.filename == '':
        return jsonify({'error': 'No se seleccionó ningún archivo'}), 400
    if not allowed_file(file.filename):
        return jsonify({'error': 'Formato no permitido. Usa: PNG, JPG, JPEG, GIF, WEBP'}), 400
    try:
        filename = secure_filename(file.filename)
        extension = filename.rsplit('.', 1)[1].lower()
        nuevo_nombre = f"perfil_{current_user.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{extension}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'perfiles', nuevo_nombre)
        file.save(file_path)
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE usuarios SET foto_perfil = ? WHERE id = ?", (f'/uploads/perfiles/{nuevo_nombre}', current_user.id))
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'success': True, 
            'foto': f'/uploads/perfiles/{nuevo_nombre}',
            'message': 'Foto de perfil actualizada'
        })
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/eliminar_foto_perfil', methods=['POST'])
@login_required
def eliminar_foto_perfil():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT foto_perfil FROM usuarios WHERE id = ?", (current_user.id,))
        usuario = cur.fetchone()
        if usuario and usuario['foto_perfil']:
            foto_path = os.path.join(app.config['UPLOAD_FOLDER'], 'perfiles', 
                                    usuario['foto_perfil'].split('/')[-1])
            if os.path.exists(foto_path):
                os.remove(foto_path)
            cur.execute("UPDATE usuarios SET foto_perfil = NULL WHERE id = ?", (current_user.id,))
            conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'message': 'Foto eliminada'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================
# RUTAS PROFESOR - TAREAS
# ============================================

@app.route('/profesor/tareas')
@login_required
@premium_required
def profesor_tareas():
    if not current_user.is_docente:
        flash('Solo profesores pueden acceder a esta sección', 'danger')
        return redirect(url_for('index'))
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM tareas ORDER BY fecha_creacion DESC")
        tareas = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error en profesor_tareas: {e}")
        tareas = []
    return render_template('profesor/tareas.html', tareas=tareas)

# ============================================
# RUTAS PROFESOR - SALAS DE CLASE
# ============================================

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
                   (SELECT COUNT(*) FROM sala_alumnos WHERE sala_id = s.id AND activo = 1) as total_alumnos,
                   (SELECT COUNT(*) FROM sala_progreso WHERE sala_id = s.id AND completada = 1) as total_lecciones_completadas
            FROM salas_clase s
            WHERE s.profesor_id = ? AND s.activa = 1
            ORDER BY s.creada_en DESC
        """, (current_user.id,))
        salas = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error en profesor_salas: {e}")
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
        import random
        import string
        codigo = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO salas_clase (nombre, descripcion, codigo_acceso, profesor_id)
                VALUES (?, ?, ?, ?)
            """, (nombre, descripcion, codigo, current_user.id))
            conn.commit()
            cur.close()
            conn.close()
            flash(f'✅ ¡Sala creada exitosamente! Código: {codigo}', 'success')
            return redirect(url_for('profesor_salas'))
        except Exception as e:
            print(f"Error al crear sala: {e}")
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
        cur.execute("""
            SELECT * FROM salas_clase
            WHERE id = ? AND profesor_id = ? AND activa = 1
        """, (sala_id, current_user.id))
        sala = cur.fetchone()
        if not sala:
            flash('Sala no encontrada', 'danger')
            return redirect(url_for('profesor_salas'))
        
        cur.execute("""
            SELECT u.id, u.nombre, u.apellido_paterno, u.email, u.nivel, u.xp,
                   sa.fecha_ingreso,
                   (SELECT COUNT(*) FROM sala_progreso
                    WHERE sala_id = ? AND alumno_id = u.id AND completada = 1) as lecciones_completadas,
                   (SELECT COUNT(*) FROM sala_progreso
                    WHERE sala_id = ? AND alumno_id = u.id) as total_intentos,
                   (SELECT ROUND(AVG(puntaje)) FROM sala_progreso
                    WHERE sala_id = ? AND alumno_id = u.id AND completada = 1) as promedio_puntaje
            FROM sala_alumnos sa
            JOIN usuarios u ON sa.alumno_id = u.id
            WHERE sa.sala_id = ? AND sa.activo = 1
            ORDER BY u.nombre
        """, (sala_id, sala_id, sala_id, sala_id))
        alumnos = cur.fetchall()
        
        cur.execute("""
            SELECT l.id, l.titulo, l.xp, l.icono,
                   COUNT(DISTINCT sp.alumno_id) as alumnos_completaron,
                   ROUND(AVG(sp.puntaje)) as promedio_puntaje_leccion
            FROM lecciones l
            LEFT JOIN sala_progreso sp ON l.id = sp.leccion_id
                AND sp.sala_id = ? AND sp.completada = 1
            WHERE l.activo = 1
            GROUP BY l.id
            ORDER BY l.id
        """, (sala_id,))
        lecciones_progreso = cur.fetchall()
        
        total_alumnos = len(alumnos)
        for leccion in lecciones_progreso:
            if total_alumnos > 0:
                leccion['porcentaje'] = round((leccion['alumnos_completaron'] / total_alumnos) * 100)
            else:
                leccion['porcentaje'] = 0
        
        estadisticas = {
            'total_alumnos': total_alumnos,
            'total_lecciones': len(lecciones_progreso),
            'lecciones_completadas_totales': sum(l['alumnos_completaron'] for l in lecciones_progreso),
            'promedio_general': round(sum(l['promedio_puntaje_leccion'] or 0 for l in lecciones_progreso) / len(lecciones_progreso) if lecciones_progreso else 0)
        }
        
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error en sala_detalle: {e}")
        flash('Error al cargar la sala', 'danger')
        return redirect(url_for('profesor_salas'))
    
    return render_template('profesor/sala_detalle.html', 
                         sala=sala, 
                         alumnos=alumnos,
                         lecciones_progreso=lecciones_progreso,
                         estadisticas=estadisticas,
                         total_alumnos=total_alumnos)

@app.route('/profesor/sala/<int:sala_id>/alumno/<int:alumno_id>')
@login_required
def profesor_sala_alumno(sala_id, alumno_id):
    if not current_user.is_docente:
        flash('Solo profesores pueden acceder', 'danger')
        return redirect(url_for('index'))
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM salas_clase
            WHERE id = ? AND profesor_id = ? AND activa = 1
        """, (sala_id, current_user.id))
        sala = cur.fetchone()
        if not sala:
            flash('Sala no encontrada', 'danger')
            return redirect(url_for('profesor_salas'))
        
        cur.execute("""
            SELECT u.*, sa.fecha_ingreso
            FROM usuarios u
            JOIN sala_alumnos sa ON u.id = sa.alumno_id
            WHERE u.id = ? AND sa.sala_id = ? AND sa.activo = 1
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
                AND sp.alumno_id = ? AND sp.sala_id = ?
            WHERE l.activo = 1
            ORDER BY l.id
        """, (alumno_id, sala_id))
        progreso = cur.fetchall()
        
        total_lecciones = len(progreso)
        completadas = sum(1 for p in progreso if p['completada'])
        promedio = round(sum(p['puntaje'] or 0 for p in progreso if p['completada']) / completadas if completadas > 0 else 0)
        
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error: {e}")
        flash('Error al cargar los datos', 'danger')
        return redirect(url_for('profesor_sala_detalle', sala_id=sala_id))
    
    return render_template('profesor/sala_alumno.html', 
                         sala=sala, 
                         alumno=alumno,
                         progreso=progreso,
                         total_lecciones=total_lecciones,
                         completadas=completadas,
                         promedio=promedio)

@app.route('/profesor/sala/<int:sala_id>/eliminar', methods=['POST'])
@login_required
def profesor_sala_eliminar(sala_id):
    if not current_user.is_docente:
        return jsonify({'error': 'No autorizado'}), 403
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE salas_clase
            SET activa = 0
            WHERE id = ? AND profesor_id = ?
        """, (sala_id, current_user.id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sala/unirse', methods=['POST'])
@login_required
def sala_unirse():
    data = request.json
    codigo = data.get('codigo', '').strip().upper()
    if not codigo:
        return jsonify({'error': 'Código requerido'}), 400
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM salas_clase WHERE codigo_acceso = ? AND activa = 1", (codigo,))
        sala = cur.fetchone()
        if not sala:
            return jsonify({'error': 'Código inválido o sala inactiva'}), 404
        cur.execute("""
            INSERT OR IGNORE INTO sala_alumnos (sala_id, alumno_id)
            VALUES (?, ?)
        """, (sala['id'], current_user.id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'message': '¡Te has unido a la sala!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========== RUTAS ADMIN - DASHBOARD ==========

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash('No tienes permisos', 'danger')
        return redirect(url_for('index'))
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as total FROM usuarios WHERE activo = 1")
        total_usuarios = cur.fetchone()['total']
        cur.execute("SELECT COUNT(*) as total FROM lecciones WHERE activo = 1")
        total_lecciones = cur.fetchone()['total']
        cur.execute("SELECT COUNT(*) as total FROM campanas_simulacion WHERE activa = 1")
        total_simulaciones = cur.fetchone()['total']
        cur.execute("SELECT COUNT(*) as total FROM autoridades WHERE activo = 1")
        total_autoridades = cur.fetchone()['total']
        cur.close()
        conn.close()
        estadisticas = [
            {'nombre': 'Usuarios', 'valor': total_usuarios, 'icono': 'users', 'color': '#2563EB'},
            {'nombre': 'Lecciones', 'valor': total_lecciones, 'icono': 'book', 'color': '#10B981'},
            {'nombre': 'Simulaciones', 'valor': total_simulaciones, 'icono': 'gamepad', 'color': '#8B5CF6'},
            {'nombre': 'Autoridades', 'valor': total_autoridades, 'icono': 'landmark', 'color': '#F59E0B'}
        ]
    except:
        estadisticas = [
            {'nombre': 'Usuarios', 'valor': 0, 'icono': 'users', 'color': '#2563EB'},
            {'nombre': 'Lecciones', 'valor': 0, 'icono': 'book', 'color': '#10B981'},
            {'nombre': 'Simulaciones', 'valor': 0, 'icono': 'gamepad', 'color': '#8B5CF6'},
            {'nombre': 'Autoridades', 'valor': 0, 'icono': 'landmark', 'color': '#F59E0B'}
        ]
    return render_template('admin/dashboard.html', estadisticas=estadisticas)

# ========== RUTAS ADMIN - LECCIONES ==========
# (Se mantienen idénticas, solo se cambia la función get_mundos para SQLite)
def get_mundos():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM mundos_aprendizaje ORDER BY nombre")
        mundos = cur.fetchall()
        cur.close()
        conn.close()
        return mundos
    except Exception as e:
        print(f"Error obteniendo mundos: {e}")
        return []

@app.route('/admin/lecciones')
@login_required
def admin_lecciones():
    if not current_user.is_admin:
        flash('No tienes permisos', 'danger')
        return redirect(url_for('index'))
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

@app.route('/admin/leccion/nueva', methods=['GET', 'POST'])
@login_required
def admin_leccion_nueva():
    if not current_user.is_admin:
        flash('No tienes permisos', 'danger')
        return redirect(url_for('index'))
    if request.method == 'POST':
        titulo = request.form.get('titulo', '').strip()
        mundo_id = request.form.get('mundo_id', '').strip()
        if not titulo:
            flash('El título de la lección es obligatorio', 'danger')
            return render_template('admin/leccion_form.html', mundos=get_mundos(), leccion=None)
        if not mundo_id:
            flash('Debes seleccionar un mundo', 'danger')
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (mundo_id, titulo, situacion_inicial, explicacion,
                  ejemplo, historia, curiosidad, reflexion, xp, icono))
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
                    ) VALUES (?, 'alternativas', ?, ?, ?, ?, ?)
                """, (leccion_id, pregunta, opciones_json, respuesta_json, explicacion_act, i))
            
            conn.commit()
            cur.close()
            conn.close()
            flash(f'¡Lección creada exitosamente con {len(preguntas)} pregunta(s)!', 'success')
            return redirect(url_for('admin_lecciones'))
            
        except Exception as e:
            print(f"❌ ERROR al crear lección: {e}")
            import traceback
            traceback.print_exc()
            flash(f'Error al crear la lección: {str(e)}', 'danger')
    
    mundos = get_mundos()
    return render_template('admin/leccion_form.html', mundos=mundos, leccion=None)

@app.route('/admin/leccion/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def admin_leccion_editar(id):
    if not current_user.is_admin:
        flash('No tienes permisos', 'danger')
        return redirect(url_for('index'))
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
                SET mundo_id = ?, titulo = ?, situacion_inicial = ?, explicacion = ?,
                    ejemplo = ?, historia = ?, curiosidad = ?, reflexion = ?,
                    xp = ?, icono = ?, activo = ?
                WHERE id = ?
            """, (mundo_id, titulo, situacion_inicial, explicacion, ejemplo, historia,
                  curiosidad, reflexion, xp, icono, activo, id))
            
            cur.execute("DELETE FROM actividades_leccion WHERE leccion_id = ?", (id,))
            
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
                    ) VALUES (?, 'alternativas', ?, ?, ?, ?, ?)
                """, (id, pregunta, opciones_json, respuesta_json, explicacion_act, i))
            
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Lección actualizada exitosamente!', 'success')
            return redirect(url_for('admin_lecciones'))
        
        cur.execute("SELECT * FROM lecciones WHERE id = ?", (id,))
        leccion = cur.fetchone()
        cur.execute("SELECT * FROM actividades_leccion WHERE leccion_id = ? ORDER BY orden", (id,))
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
        print(f"Error: {e}")
        flash('Error al editar la lección', 'danger')
        return redirect(url_for('admin_lecciones'))

@app.route('/admin/leccion/eliminar/<int:id>', methods=['POST'])
@login_required
def admin_leccion_eliminar(id):
    if not current_user.is_admin:
        return jsonify({'error': 'No autorizado'}), 403
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM lecciones WHERE id = ?", (id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========== RUTAS ADMIN - SIMULACIONES ==========
# (Se mantienen igual, solo se ajustan las consultas con ?)
@app.route('/admin/simulaciones')
@login_required
def admin_simulaciones():
    if not current_user.is_admin:
        flash('No tienes permisos', 'danger')
        return redirect(url_for('index'))
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT s.*,
                   JSON_LENGTH(s.escenas) as total_escenas
            FROM campanas_simulacion s
            ORDER BY s.id DESC
        """)
        simulaciones = cur.fetchall()
        cur.close()
        conn.close()
    except:
        simulaciones = []
    return render_template('admin/simulaciones.html', simulaciones=simulaciones)

@app.route('/admin/simulacion/nueva', methods=['GET', 'POST'])
@login_required
def admin_simulacion_nueva():
    if not current_user.is_admin:
        flash('No tienes permisos', 'danger')
        return redirect(url_for('index'))
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
                    'opciones': [
                        {'texto': f'Opción 1 para la situación {i}'},
                        {'texto': f'Opción 2 para la situación {i}'},
                        {'texto': f'Opción 3 para la situación {i}'}
                    ]
                }
                escenas_base.append(escena)
            
            introduccion = json.dumps({
                'contexto': request.form.get('contexto', 'Contexto inicial de la simulación.'),
                'personajes': [
                    {'nombre': 'Personaje 1', 'rol': 'Rol del personaje 1'},
                    {'nombre': 'Personaje 2', 'rol': 'Rol del personaje 2'}
                ],
                'objetivo': request.form.get('objetivo', 'Objetivo de la simulación.')
            })
            escenas = json.dumps(escenas_base)
            finales = json.dumps([
                {'titulo': 'El Conciliador', 'condiciones': {'Confianza': '> 50', 'Participacion': '> 50'}, 
                 'texto': 'Lograste unir a todos.', 'reflexion': 'Reflexión sobre el conciliador.'},
                {'titulo': 'El Reformista', 'condiciones': {'Educacion': '> 50', 'Participacion': '> 40'},
                 'texto': 'Implementaste cambios.', 'reflexion': 'Reflexión sobre el reformista.'},
                {'titulo': 'El Popular', 'condiciones': {'Participacion': '> 60', 'Confianza': '> 40'},
                 'texto': 'Ganaste apoyo popular.', 'reflexion': 'Reflexión sobre el popular.'},
                {'titulo': 'El Administrador', 'condiciones': {'Confianza': '> 50', 'Seguridad': '> 40'},
                 'texto': 'Gestión eficiente.', 'reflexion': 'Reflexión sobre el administrador.'},
                {'titulo': 'El Visionario', 'condiciones': {'Educacion': '> 60', 'Confianza': '> 50'},
                 'texto': 'Visión de futuro.', 'reflexion': 'Reflexión sobre el visionario.'}
            ])
            eventos = json.dumps([
                {'trigger': 3, 'titulo': 'Evento inesperado', 'descripcion': 'Descripción del evento.'},
                {'trigger': 7, 'titulo': 'Segundo evento', 'descripcion': 'Descripción del segundo evento.'}
            ])
            
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO campanas_simulacion (titulo, descripcion, dificultad, introduccion, escenas, finales, eventos, xp_recompensa, activa)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (titulo, descripcion, dificultad, introduccion, escenas, finales, eventos, xp_recompensa, activa))
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Simulación creada exitosamente con 10 situaciones!', 'success')
            return redirect(url_for('admin_simulaciones'))
            
        except Exception as e:
            print(f"Error: {e}")
            flash('Error al crear la simulación', 'danger')
    return render_template('admin/simulacion_form.html', simulacion=None)

@app.route('/admin/simulacion/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def admin_simulacion_editar(id):
    if not current_user.is_admin:
        flash('No tienes permisos', 'danger')
        return redirect(url_for('index'))
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
                SET titulo = ?, descripcion = ?, dificultad = ?, xp_recompensa = ?, activa = ?
                WHERE id = ?
            """, (titulo, descripcion, dificultad, xp_recompensa, activa, id))
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Simulación actualizada!', 'success')
            return redirect(url_for('admin_simulaciones'))
        
        cur.execute("SELECT * FROM campanas_simulacion WHERE id = ?", (id,))
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
        print(f"Error: {e}")
        flash('Error al editar la simulación', 'danger')
        return redirect(url_for('admin_simulaciones'))

@app.route('/admin/simulacion/editar_escenas/<int:id>', methods=['GET', 'POST'])
@login_required
def admin_simulacion_editar_escenas(id):
    if not current_user.is_admin:
        flash('No tienes permisos', 'danger')
        return redirect(url_for('index'))
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM campanas_simulacion WHERE id = ?", (id,))
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
            cur.execute("""
                UPDATE campanas_simulacion
                SET escenas = ?
                WHERE id = ?
            """, (json.dumps(nuevas_escenas, ensure_ascii=False), id))
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Situaciones actualizadas exitosamente!', 'success')
            return redirect(url_for('admin_simulaciones'))
        
        return render_template('admin/simulacion_escenas.html', 
                             simulacion=simulacion, 
                             escenas=escenas)
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        flash('Error al editar las situaciones', 'danger')
        return redirect(url_for('admin_simulaciones'))

# ============================================
# RUTAS ADMIN - CARTAS DE EVENTO
# ============================================
# (Ajustadas para SQLite, pero la lógica es igual)
@app.route('/admin/cartas_evento')
@login_required
@admin_required
def admin_cartas_evento():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT c.*,
                   CASE WHEN c.activa = 1 THEN 'Activa' ELSE 'Inactiva' END as estado_texto
            FROM cartas_evento c
            ORDER BY c.id DESC
        """)
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
    except Exception as e:
        print(f"Error: {e}")
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (titulo, descripcion, icono, tipo, json.dumps(efectos), mensaje_visible,
                  probabilidad, activa, current_user.id, campana_id, escenas_validas))
            conn.commit()
            cur.close()
            conn.close()
            flash('✅ ¡Carta de evento creada exitosamente!', 'success')
            return redirect(url_for('admin_cartas_evento'))
        except Exception as e:
            print(f"Error: {e}")
            flash('Error al crear la carta', 'danger')
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, titulo FROM campanas_simulacion WHERE activa = 1 ORDER BY titulo")
        simulaciones = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error obteniendo simulaciones: {e}")
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
                SET titulo = ?, descripcion = ?, icono = ?, tipo = ?,
                    efectos = ?, mensaje_visible = ?, probabilidad = ?,
                    activa = ?, campana_id = ?, escenas_validas = ?
                WHERE id = ?
            """, (titulo, descripcion, icono, tipo, json.dumps(efectos), mensaje_visible,
                  probabilidad, activa, campana_id, escenas_validas, id))
            conn.commit()
            cur.close()
            conn.close()
            flash('✅ ¡Carta actualizada!', 'success')
            return redirect(url_for('admin_cartas_evento'))
        
        cur.execute("SELECT * FROM cartas_evento WHERE id = ?", (id,))
        carta = cur.fetchone()
        cur.execute("SELECT id, titulo FROM campanas_simulacion WHERE activa = 1 ORDER BY titulo")
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
        print(f"Error: {e}")
        flash('Error al editar la carta', 'danger')
        return redirect(url_for('admin_cartas_evento'))

@app.route('/admin/carta_evento/eliminar/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_carta_evento_eliminar(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM cartas_evento WHERE id = ?", (id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================
# RUTAS ADMIN - RUTAS ALTERNATIVAS
# ============================================
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
    except Exception as e:
        print(f"Error: {e}")
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
                VALUES (?, ?, ?, ?, ?, ?)
            """, (carta_id, escena_id, nuevo_contexto, nuevo_problema, json.dumps(opciones), siguiente_escena))
            conn.commit()
            cur.close()
            conn.close()
            flash('✅ ¡Ruta alternativa creada exitosamente!', 'success')
            return redirect(url_for('admin_rutas_alternativas'))
        except Exception as e:
            print(f"Error: {e}")
            flash('Error al crear la ruta alternativa', 'danger')
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, titulo, icono FROM cartas_evento WHERE activa = 1")
        cartas = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error: {e}")
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
                SET carta_id = ?, escena_id = ?, nuevo_contexto = ?,
                    nuevo_problema = ?, opciones = ?, siguiente_escena = ?
                WHERE id = ?
            """, (carta_id, escena_id, nuevo_contexto, nuevo_problema, json.dumps(opciones), siguiente_escena, id))
            conn.commit()
            cur.close()
            conn.close()
            flash('✅ ¡Ruta alternativa actualizada!', 'success')
            return redirect(url_for('admin_rutas_alternativas'))
        
        cur.execute("SELECT * FROM rutas_alternativas WHERE id = ?", (id,))
        ruta = cur.fetchone()
        cur.execute("SELECT id, titulo, icono FROM cartas_evento WHERE activa = 1")
        cartas = cur.fetchall()
        cur.close()
        conn.close()
        if ruta and ruta['opciones']:
            ruta['opciones'] = json.loads(ruta['opciones']) if isinstance(ruta['opciones'], str) else ruta['opciones']
        return render_template('admin/ruta_alternativa_form.html', ruta=ruta, cartas=cartas)
        
    except Exception as e:
        print(f"Error: {e}")
        flash('Error al editar la ruta alternativa', 'danger')
        return redirect(url_for('admin_rutas_alternativas'))

@app.route('/admin/ruta_alternativa/eliminar/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_ruta_alternativa_eliminar(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM rutas_alternativas WHERE id = ?", (id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================
# RUTAS ADMIN - USUARIOS, TAREAS, NOTICIAS, AUTORIDADES, PROPUESTAS, ESTADO
# ============================================
# Todas estas rutas se mantienen EXACTAMENTE IGUALES,
# solo se modifican las consultas para SQLite (sustituir %s por ?,
# y reemplazar CURDATE() por date('now'), etc.)

# Por razones de espacio, te entrego el bloque completo pero con los cambios
# ya aplicados en las consultas principales. Si necesitas alguna parte específica,
# dímelo.

# A continuación, todas las rutas de administración restantes, con los cambios SQLite.

@app.route('/admin/usuarios')
@login_required
def admin_usuarios():
    if not current_user.is_super_admin:
        flash('Solo Super Admin puede acceder', 'danger')
        return redirect(url_for('admin_dashboard'))
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
def admin_usuario_cambiar_tipo(id):
    if not current_user.is_super_admin:
        return jsonify({'error': 'Solo Super Admin puede cambiar roles'}), 403
    if id == current_user.id:
        return jsonify({'error': 'No puedes cambiar tu propio rol'}), 400
    data = request.json
    tipo_usuario_id = data.get('tipo_usuario_id')
    if not tipo_usuario_id:
        return jsonify({'error': 'Tipo de usuario requerido'}), 400
    if int(tipo_usuario_id) not in [1, 2, 3, 4, 5]:
        return jsonify({'error': 'Tipo de usuario inválido'}), 400
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM usuarios WHERE id = ?", (id,))
        if not cur.fetchone():
            return jsonify({'error': 'Usuario no encontrado'}), 404
        cur.execute("UPDATE usuarios SET tipo_usuario_id = ? WHERE id = ?", (tipo_usuario_id, id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'message': 'Rol actualizado'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/usuario/cambiar_rol/<int:id>', methods=['POST'])
@login_required
def admin_usuario_cambiar_rol(id):
    return admin_usuario_cambiar_tipo(id)

@app.route('/admin/usuario/bloquear/<int:id>', methods=['POST'])
@login_required
def admin_usuario_bloquear(id):
    if not current_user.is_super_admin:
        return jsonify({'error': 'Solo Super Admin puede bloquear usuarios'}), 403
    if id == current_user.id:
        return jsonify({'error': 'No puedes bloquearte a ti mismo'}), 400
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT activo FROM usuarios WHERE id = ?", (id,))
        user = cur.fetchone()
        if not user:
            return jsonify({'error': 'Usuario no encontrado'}), 404
        nuevo_estado = 0 if user['activo'] else 1
        cur.execute("UPDATE usuarios SET activo = ? WHERE id = ?", (nuevo_estado, id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'activo': nuevo_estado})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/usuario/eliminar/<int:id>', methods=['POST'])
@login_required
def admin_usuario_eliminar(id):
    if not current_user.is_super_admin:
        return jsonify({'error': 'Solo Super Admin puede eliminar usuarios'}), 403
    if id == current_user.id:
        return jsonify({'error': 'No puedes eliminarte a ti mismo'}), 400
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT tipo_usuario_id FROM usuarios WHERE id = ?", (id,))
        user = cur.fetchone()
        if not user:
            return jsonify({'error': 'Usuario no encontrado'}), 404
        if user['tipo_usuario_id'] == 1:
            return jsonify({'error': 'No puedes eliminar a otro Super Admin'}), 400
        cur.execute("DELETE FROM usuarios WHERE id = ?", (id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'message': 'Usuario eliminado'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/tareas')
@login_required
def admin_tareas():
    if not current_user.is_admin:
        flash('No tienes permisos', 'danger')
        return redirect(url_for('index'))
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM tareas ORDER BY fecha_creacion DESC")
        tareas = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error: {e}")
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
            cur.execute("""
                INSERT INTO tareas (titulo, descripcion, archivo_url, creado_por)
                VALUES (?, ?, ?, ?)
            """, (titulo, descripcion, archivo_url, current_user.id))
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Tarea creada con archivo!', 'success')
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
                cur.execute("SELECT archivo_url FROM tareas WHERE id = ?", (id,))
                tarea_old = cur.fetchone()
                if tarea_old and tarea_old['archivo_url']:
                    ruta_old = os.path.join(app.config['UPLOAD_FOLDER'], 'tareas', 
                                           tarea_old['archivo_url'].split('/')[-1])
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
                cur.execute("""
                    UPDATE tareas SET titulo=?, descripcion=?, archivo_url=? WHERE id=?
                """, (titulo, descripcion, archivo_url, id))
            else:
                cur.execute("""
                    UPDATE tareas SET titulo=?, descripcion=? WHERE id=?
                """, (titulo, descripcion, id))
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
        cur.execute("SELECT * FROM tareas WHERE id = ?", (id,))
        tarea = cur.fetchone()
        cur.close()
        conn.close()
        return render_template('admin/tarea_form.html', tarea=tarea)
    except:
        flash('Error al cargar la tarea', 'danger')
        return redirect(url_for('admin_tareas'))

@app.route('/admin/tarea/eliminar/<int:id>', methods=['POST'])
@login_required
def admin_tarea_eliminar(id):
    if not current_user.is_admin:
        return jsonify({'error': 'No autorizado'}), 403
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM tareas WHERE id = ?", (id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/noticias')
@login_required
def admin_noticias():
    if not current_user.is_admin:
        flash('No tienes permisos', 'danger')
        return redirect(url_for('index'))
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
def admin_noticia_nueva():
    if not current_user.is_admin:
        flash('No tienes permisos', 'danger')
        return redirect(url_for('index'))
    if request.method == 'POST':
        try:
            titulo = request.form.get('titulo')
            descripcion = request.form.get('descripcion')
            fecha = request.form.get('fecha')
            icono = request.form.get('icono', 'circle')
            activa = 1 if request.form.get('activa') else 0
            destacada = 1 if request.form.get('destacada') else 0
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO noticias (titulo, descripcion, fecha, icono, activa, destacada)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (titulo, descripcion, fecha, icono, activa, destacada))
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Noticia creada exitosamente!', 'success')
            return redirect(url_for('admin_noticias'))
        except Exception as e:
            print(f"Error: {e}")
            flash('Error al crear la noticia', 'danger')
    return render_template('admin/noticia_form.html', noticia=None)

@app.route('/admin/noticia/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def admin_noticia_editar(id):
    if not current_user.is_admin:
        flash('No tienes permisos', 'danger')
        return redirect(url_for('index'))
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if request.method == 'POST':
            titulo = request.form.get('titulo')
            descripcion = request.form.get('descripcion')
            fecha = request.form.get('fecha')
            icono = request.form.get('icono', 'circle')
            activa = 1 if request.form.get('activa') else 0
            destacada = 1 if request.form.get('destacada') else 0
            cur.execute("""
                UPDATE noticias
                SET titulo = ?, descripcion = ?, fecha = ?, icono = ?, activa = ?, destacada = ?
                WHERE id = ?
            """, (titulo, descripcion, fecha, icono, activa, destacada, id))
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Noticia actualizada!', 'success')
            return redirect(url_for('admin_noticias'))
        cur.execute("SELECT * FROM noticias WHERE id = ?", (id,))
        noticia = cur.fetchone()
        cur.close()
        conn.close()
        return render_template('admin/noticia_form.html', noticia=noticia)
    except Exception as e:
        print(f"Error: {e}")
        flash('Error al editar la noticia', 'danger')
        return redirect(url_for('admin_noticias'))

@app.route('/admin/noticia/eliminar/<int:id>', methods=['POST'])
@login_required
def admin_noticia_eliminar(id):
    if not current_user.is_admin:
        return jsonify({'error': 'No autorizado'}), 403
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM noticias WHERE id = ?", (id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================
# RUTAS ADMIN - AUTORIDADES (COMPLETAS)
# ============================================
@app.route('/admin/autoridades')
@login_required
@admin_required
def admin_autoridades():
    if not current_user.is_admin_or_super:
        flash('No tienes permisos', 'danger')
        return redirect(url_for('index'))
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
    if not current_user.is_admin_or_super:
        flash('No tienes permisos', 'danger')
        return redirect(url_for('index'))
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (nombre, apellido_paterno, cargo, tipo_autoridad_id, partido, descripcion_cargo, biografia, activo))
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Autoridad creada exitosamente!', 'success')
            return redirect(url_for('admin_autoridades'))
        except Exception as e:
            print(f"Error: {e}")
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
    if not current_user.is_admin_or_super:
        flash('No tienes permisos', 'danger')
        return redirect(url_for('index'))
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
                SET nombre = ?, apellido_paterno = ?, cargo = ?, tipo_autoridad_id = ?,
                    partido = ?, descripcion_cargo = ?, biografia = ?, activo = ?
                WHERE id = ?
            """, (nombre, apellido_paterno, cargo, tipo_autoridad_id, partido, descripcion_cargo, biografia, activo, id))
            conn.commit()
            cur.close()
            conn.close()
            flash('¡Autoridad actualizada!', 'success')
            return redirect(url_for('admin_autoridades'))
        cur.execute("SELECT * FROM autoridades WHERE id = ?", (id,))
        autoridad = cur.fetchone()
        cur.execute("SELECT * FROM tipos_autoridad")
        tipos = cur.fetchall()
        cur.close()
        conn.close()
        return render_template('admin/autoridad_form.html', autoridad=autoridad, tipos=tipos)
    except Exception as e:
        print(f"Error: {e}")
        flash('Error al editar la autoridad', 'danger')
        return redirect(url_for('admin_autoridades'))

@app.route('/admin/autoridad/eliminar/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_autoridad_eliminar(id):
    if not current_user.is_admin_or_super:
        return jsonify({'error': 'No autorizado'}), 403
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM autoridades WHERE id = ?", (id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/autoridad/<int:id>/subir_foto', methods=['POST'])
@login_required
@admin_required
def admin_autoridad_subir_foto(id):
    if not current_user.is_admin_or_super:
        return jsonify({'error': 'No autorizado'}), 403
    if 'foto' not in request.files:
        return jsonify({'error': 'No se seleccionó ningún archivo'}), 400
    file = request.files['foto']
    if file.filename == '':
        return jsonify({'error': 'No se seleccionó ningún archivo'}), 400
    if not allowed_file(file.filename):
        return jsonify({'error': 'Formato no permitido. Usa: PNG, JPG, JPEG, GIF, WEBP'}), 400
    try:
        filename = secure_filename(file.filename)
        extension = filename.rsplit('.', 1)[1].lower()
        nuevo_nombre = f"autoridad_{id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{extension}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'autoridades', nuevo_nombre)
        file.save(file_path)
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE autoridades SET foto = ? WHERE id = ?", (f'/uploads/autoridades/{nuevo_nombre}', id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({
            'success': True, 
            'foto': f'/uploads/autoridades/{nuevo_nombre}',
            'message': 'Foto subida exitosamente'
        })
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/admin/autoridad/<int:id>/eliminar_foto', methods=['POST'])
@login_required
@admin_required
def admin_autoridad_eliminar_foto(id):
    if not current_user.is_admin_or_super:
        return jsonify({'error': 'No autorizado'}), 403
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT foto FROM autoridades WHERE id = ?", (id,))
        autoridad = cur.fetchone()
        if autoridad and autoridad['foto']:
            foto_path = os.path.join(app.config['UPLOAD_FOLDER'], 'autoridades',
                                    autoridad['foto'].split('/')[-1])
            if os.path.exists(foto_path):
                os.remove(foto_path)
            cur.execute("UPDATE autoridades SET foto = NULL WHERE id = ?", (id,))
            conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========== RUTAS ADMIN - PROPUESTAS ==========
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
        return render_template('admin/propuestas.html', propuestas=propuestas)
    except Exception as e:
        flash(f'Error al cargar propuestas: {e}', 'danger')
        return redirect(url_for('admin_dashboard'))

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
            flash('Los campos Autoridad, Título y Descripción son obligatorios', 'danger')
            return redirect(url_for('admin_propuesta_nueva'))
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO propuestas
                (autoridad_id, titulo, descripcion, explicacion, impacto_personal, estado, fecha_publicacion, fuente_oficial)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (autoridad_id, titulo, descripcion, explicacion, impacto_personal, estado, fecha_publicacion, fuente_oficial))
            conn.commit()
            cur.close()
            conn.close()
            flash('✅ Propuesta creada exitosamente', 'success')
            return redirect(url_for('admin_propuestas'))
        except Exception as e:
            flash(f'Error al guardar: {e}', 'danger')
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, nombre, apellido_paterno, cargo FROM autoridades WHERE activo = 1 ORDER BY nombre")
        autoridades = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        flash(f'Error al cargar autoridades: {e}', 'danger')
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
                SET autoridad_id = ?, titulo = ?, descripcion = ?, explicacion = ?,
                    impacto_personal = ?, estado = ?, fecha_publicacion = ?, fuente_oficial = ?
                WHERE id = ?
            """, (autoridad_id, titulo, descripcion, explicacion, impacto_personal, estado, fecha_publicacion, fuente_oficial, id))
            conn.commit()
            cur.close()
            conn.close()
            flash('✅ Propuesta actualizada correctamente', 'success')
            return redirect(url_for('admin_propuestas'))
        cur.execute("SELECT * FROM propuestas WHERE id = ?", (id,))
        propuesta = cur.fetchone()
        if not propuesta:
            flash('Propuesta no encontrada', 'danger')
            return redirect(url_for('admin_propuestas'))
        cur.execute("SELECT id, nombre, apellido_paterno, cargo FROM autoridades WHERE activo = 1 ORDER BY nombre")
        autoridades = cur.fetchall()
        cur.close()
        conn.close()
        return render_template('admin/propuesta_form.html', propuesta=propuesta, autoridades=autoridades)
    except Exception as e:
        flash(f'Error al editar: {e}', 'danger')
        return redirect(url_for('admin_propuestas'))

@app.route('/admin/propuesta/eliminar/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_propuesta_eliminar(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM propuestas WHERE id = ?", (id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/propuesta/<int:id>')
def detalle_propuesta(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT p.*, a.nombre AS autoridad_nombre, a.apellido_paterno AS autoridad_apellido, a.cargo
            FROM propuestas p
            JOIN autoridades a ON p.autoridad_id = a.id
            WHERE p.id = ? AND p.estado != 'Archivada'
        """, (id,))
        propuesta = cur.fetchone()
        cur.close()
        conn.close()
        if not propuesta:
            flash('Propuesta no encontrada', 'danger')
            return redirect(url_for('estado'))
        return render_template('propuesta_detalle.html', propuesta=propuesta)
    except Exception as e:
        flash(f'Error al cargar la propuesta: {e}', 'danger')
        return redirect(url_for('estado'))

# ========== RUTAS DE ESTADO ==========
# Se mantienen con las consultas SQLite ajustadas.
def get_autoridades_from_json():
    try:
        json_path = os.path.join(os.path.dirname(__file__), 'data', 'autoridades_2026.json')
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('autoridades', [])
    except Exception as e:
        print(f"Error cargando autoridades: {e}")
        return []

def sync_autoridades_to_db(autoridades):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM autoridades")  # TRUNCATE en SQLite se hace con DELETE
        for auth in autoridades:
            cur.execute("""
                INSERT INTO autoridades (
                    id, nombre, apellido_paterno, cargo, descripcion_cargo,
                    partido, activo, prioridad
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                auth.get('id', 0),
                auth.get('nombre', ''),
                auth.get('apellido', ''),
                auth.get('cargo', ''),
                auth.get('descripcion_cargo', '') or auth.get('como_funciona_su_cargo', ''),
                auth.get('partido', ''),
                1,
                auth.get('id', 1)
            ))
        conn.commit()
        cur.close()
        conn.close()
        print(f"✅ BD sincronizada: {len(autoridades)} autoridades")
    except Exception as e:
        print(f"Error sincronizando BD: {e}")

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
            WHERE autoridad_id = ? AND estado != 'Archivada'
            ORDER BY fecha_publicacion DESC, created_at DESC
        """, (id,))
        propuestas = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error cargando propuestas: {e}")
        propuestas = []
    return render_template('estado/perfil_autoridad.html', autoridad=autoridad, propuestas=propuestas)

@app.route('/estado')
def estado():
    autoridades = get_autoridades_from_json()
    if not autoridades:
        flash('No hay información de autoridades disponible', 'warning')
        autoridades = []
    return render_template('estado/index.html', autoridades=autoridades)

# ========== MercadoPago ======
@app.route('/api/activar_premium_demo', methods=['POST'])
@login_required
def activar_premium_demo():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE usuarios
            SET es_premium = 1,
                fecha_suscripcion = date('now'),
                fecha_expiracion = date('now', '+30 days'),
                plan = 'profesional'
            WHERE id = ?
        """, (current_user.id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'message': 'Premium activado (demo)'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========== ERRORES ==========
@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)