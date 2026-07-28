# config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-12345')
    DEBUG = os.getenv('DEBUG', True)
    
    # Base de datos
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_USER = os.getenv('DB_USER', 'root')
    DB_PASSWORD = os.getenv('DB_PASSWORD', 'root')
    DB_NAME = os.getenv('DB_NAME', 'politicore')
    
    # IA - Ollama
    OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://localhost:11434')
    OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'gemma3:4b')  # ← Cambia aquí el modelo
    OLLAMA_TIMEOUT = int(os.getenv('OLLAMA_TIMEOUT', 120))
    OLLAMA_KEEP_ALIVE = os.getenv('OLLAMA_KEEP_ALIVE', '5m')
    
    # IA - Rendimiento
    AI_TEMPERATURE = float(os.getenv('AI_TEMPERATURE', 0.6))
    AI_MAX_TOKENS = int(os.getenv('AI_MAX_TOKENS', 2000))
    AI_MAX_RETRIES = int(os.getenv('AI_MAX_RETRIES', 2))
    AI_CACHE_ENABLED = os.getenv('AI_CACHE_ENABLED', 'true').lower() == 'true'