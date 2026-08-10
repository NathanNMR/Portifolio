import os
import uuid
import re
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for, abort, session, flash
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash
import bleach
from bleach.css_sanitizer import CSSSanitizer
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("SECRET_KEY não definida.")

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

database_url = os.environ.get("DATABASE_URL")
if database_url:
    if database_url.startswith("mysql://"):
        database_url = database_url.replace("mysql://", "mysql+pymysql://", 1)
    database_url = database_url.split("?")[0] + "?ssl_disabled=false"
else:
    database_url = "sqlite:///portfolio_local.db"

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

with app.app_context():
    try:
        with db.engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS sobre_mim (id INT AUTO_INCREMENT PRIMARY KEY, titulo_principal VARCHAR(255) NOT NULL, subtitulo VARCHAR(255), texto_home TEXT, biografia TEXT, localizacao VARCHAR(100), email_contato VARCHAR(100), link_github VARCHAR(255), link_linkedin VARCHAR(255), avatar_url VARCHAR(255));")
            conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS projetos (id INT AUTO_INCREMENT PRIMARY KEY, titulo VARCHAR(255) NOT NULL, slug VARCHAR(255) NOT NULL UNIQUE, descricao_curta VARCHAR(255) NOT NULL, descricao_longa TEXT, imagem_capa VARCHAR(255), video_url VARCHAR(255), link_github VARCHAR(255), link_deploy VARCHAR(255), tipo_download VARCHAR(50), destaque TINYINT DEFAULT 0, criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
            conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS projeto_imagens (id INT AUTO_INCREMENT PRIMARY KEY, projeto_id INT, imagem_url VARCHAR(255) NOT NULL, FOREIGN KEY (projeto_id) REFERENCES projetos(id) ON DELETE CASCADE);")
            conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS habilidades (id INT AUTO_INCREMENT PRIMARY KEY, nome VARCHAR(100) NOT NULL, categoria VARCHAR(100), cor VARCHAR(50), cor_fundo VARCHAR(50), cor_texto VARCHAR(50));")
    except Exception as e:
        print(f"Erro ao inicializar tabelas: {e}")

# ... [O restante das funções permanece igual ao que te enviei antes] ...
# (Certifique-se de colar o restante das rotas abaixo aqui)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)