import os
import uuid
import re
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for, abort, session, flash
)
import mysql.connector
from mysql.connector import pooling
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
    raise RuntimeError(
        "SECRET_KEY não definida. Configure-a no arquivo .env "
        "(veja .env.example)."
    )

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

EXTENSOES_PERMITIDAS = {"png", "jpg", "jpeg", "webp"}

TAGS_PERMITIDAS = [
    "p", "br", "strong", "em", "b", "i", "u", "ul", "ol", "li",
    "h3", "h4", "a", "blockquote", "code", "pre", "span"
]
ATRIBUTOS_PERMITIDOS = {
    "a": ["href", "title", "target", "rel"],
    "span": ["style"]
}


def arquivo_permitido(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in EXTENSOES_PERMITIDAS


def nome_arquivo_seguro(filename):
    nome_base = secure_filename(filename)
    ext = nome_base.rsplit(".", 1)[1].lower()
    return f"{uuid.uuid4().hex}.{ext}"


def sanitizar_html(texto):
    if texto is None:
        return None
    # Converte a tag customizada <color:#HEX>texto</color> para <span style="color: #HEX;">texto</span>
    texto = re.sub(r'<color:(#[0-9a-fA-F]{3,6})>(.*?)</color>', r'<span style="color: \1;">\2</span>', texto)
    
    css_sanitizer = CSSSanitizer(allowed_css_properties=['color'])
    return bleach.clean(
        texto, 
        tags=TAGS_PERMITIDAS, 
        attributes=ATRIBUTOS_PERMITIDOS, 
        css_sanitizer=css_sanitizer,
        strip=True
    )


DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "user": os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_PASSWORD"),
    "database": os.environ.get("DB_NAME", "portfolio_db"),
}

if not DB_CONFIG["password"]:
    raise RuntimeError(
        "DB_PASSWORD não definida. Configure-a no arquivo .env "
        "(veja .env.example)."
    )

connection_pool = pooling.MySQLConnectionPool(
    pool_name="portfolio_pool",
    pool_size=5,
    **DB_CONFIG
)


def get_db_connection():
    return connection_pool.get_connection()


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapped


@app.route("/admin/login", methods=["GET", "POST"])
def login():
    erro = None
    if request.method == "POST":
        usuario = request.form.get("usuario", "")
        senha = request.form.get("senha", "")

        credenciais_ok = (
            ADMIN_USERNAME and ADMIN_PASSWORD_HASH
            and usuario == ADMIN_USERNAME
            and check_password_hash(ADMIN_PASSWORD_HASH, senha)
        )

        if credenciais_ok:
            session.clear()
            session["logged_in"] = True
            session.permanent = True
            destino = request.args.get("next") or url_for("admin")
            return redirect(destino)
        erro = "Usuário ou senha inválidos."

    return render_template("login.html", erro=erro)


@app.route("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def home():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM sobre_mim LIMIT 1")
    sobre = cursor.fetchone()

    cursor.execute("""
        SELECT id, titulo, slug, imagem_capa, video_url, link_github, link_deploy, tipo_download, destaque, criado_em,
               IF(CHAR_LENGTH(descricao_curta) > 110, CONCAT(SUBSTRING(descricao_curta, 1, 107), '...'), descricao_curta) AS descricao_curta
        FROM projetos 
        WHERE destaque = 1 
        ORDER BY criado_em DESC 
        LIMIT 3
    """)
    projetos = cursor.fetchall()

    cursor.execute("SELECT * FROM habilidades")
    habilidades = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("index.html", sobre=sobre, projetos=projetos, habilidades=habilidades)


@app.route("/projetos")
def todos_projetos():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM sobre_mim LIMIT 1")
    sobre = cursor.fetchone()

    cursor.execute("SELECT * FROM projetos ORDER BY criado_em DESC")
    projetos = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("todos_projetos.html", sobre=sobre, projetos=projetos)


@app.route("/projeto/<string:slug>")
def detalhes_projeto(slug):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM projetos WHERE slug = %s", (slug,))
    projeto = cursor.fetchone()

    if not projeto:
        cursor.close()
        conn.close()
        abort(404)

    cursor.execute("SELECT * FROM projeto_imagens WHERE projeto_id = %s", (projeto["id"],))
    imagens_extras = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("projeto.html", projeto=projeto, imagens_extras=imagens_extras)


@app.route("/admin", methods=["GET"])
@login_required
def admin():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM sobre_mim LIMIT 1")
    sobre = cursor.fetchone()

    cursor.execute("SELECT * FROM projetos ORDER BY criado_em DESC")
    projetos = cursor.fetchall()

    cursor.execute("SELECT * FROM habilidades")
    habilidades = cursor.fetchall()

    cursor.close()
    conn.close()

    msg = request.args.get("msg")
    erro_destaque = request.args.get("erro_destaque")

    return render_template(
        "admin.html", sobre=sobre, projetos=projetos, habilidades=habilidades,
        msg=msg, erro_destaque=erro_destaque
    )


def _salvar_upload(file_storage):
    """Salva e redimensiona otimizadamente arquivos enviados usando Pillow."""
    if file_storage and file_storage.filename != "" and arquivo_permitido(file_storage.filename):
        filename = nome_arquivo_seguro(file_storage.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        try:
            img = Image.open(file_storage)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            img.save(filepath, optimize=True, quality=85)
        except Exception:
            file_storage.seek(0)
            file_storage.save(filepath)
        return f"/static/uploads/{filename}"
    return None


@app.route("/admin/projeto", methods=["POST"])
@login_required
def adicionar_projeto():
    titulo = request.form["titulo"]
    slug = request.form.get("slug")
    if not slug:
        slug = titulo.lower().replace(" ", "-").replace("ç", "c").replace("ã", "a").replace("é", "e")

    descricao_curta = request.form["descricao_curta"]
    descricao_longa = sanitizar_html(request.form["descricao_longa"])
    video_url = request.form.get("video_url") or None
    link_github = request.form.get("link_github") or None
    link_deploy = request.form.get("link_deploy") or None
    tipo_download = request.form.get("tipo_download") or None
    destaque = 1 if "destaque" in request.form else 0

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if destaque == 1:
        cursor.execute("SELECT COUNT(*) as total FROM projetos WHERE destaque = 1")
        res = cursor.fetchone()
        if res["total"] >= 3:
            cursor.close()
            conn.close()
            return redirect(url_for(
                "admin",
                erro_destaque="Limite de 3 projetos em destaque atingido! Retire o destaque de algum projeto existente."
            ))

    imagem_capa_path = _salvar_upload(request.files.get("imagem_capa"))

    cursor = conn.cursor()
    query = """
        INSERT INTO projetos (titulo, slug, descricao_curta, descricao_longa, imagem_capa, video_url, link_github, link_deploy, tipo_download, destaque)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    cursor.execute(query, (titulo, slug, descricao_curta, descricao_longa, imagem_capa_path, video_url, link_github, link_deploy, tipo_download, destaque))
    projeto_id = cursor.lastrowid

    if "imagens_extras" in request.files:
        files = request.files.getlist("imagens_extras")
        for file in files:
            img_url = _salvar_upload(file)
            if img_url:
                cursor.execute("INSERT INTO projeto_imagens (projeto_id, imagem_url) VALUES (%s, %s)", (projeto_id, img_url))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for("admin", msg="Projeto publicado com sucesso!"))


@app.route("/admin/projeto/editar/<int:id>", methods=["GET", "POST"])
@login_required
def editar_projeto(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        titulo = request.form["titulo"]
        slug = request.form["slug"]
        descricao_curta = request.form["descricao_curta"]
        descricao_longa = sanitizar_html(request.form["descricao_longa"])
        video_url = request.form.get("video_url") or None
        link_github = request.form.get("link_github") or None
        link_deploy = request.form.get("link_deploy") or None
        tipo_download = request.form.get("tipo_download") or None
        destaque = 1 if "destaque" in request.form else 0

        if destaque == 1:
            cursor.execute("SELECT COUNT(*) as total FROM projetos WHERE destaque = 1 AND id != %s", (id,))
            res = cursor.fetchone()
            if res["total"] >= 3:
                cursor.close()
                conn.close()
                return redirect(url_for("admin", erro_destaque="Limite de 3 projetos em destaque atingido!"))

        imagem_capa_sql = ""
        valores_extras = []
        imagem_capa_path = _salvar_upload(request.files.get("imagem_capa"))
        if imagem_capa_path:
            imagem_capa_sql = ", imagem_capa = %s"
            valores_extras.append(imagem_capa_path)

        cursor = conn.cursor()
        query = f"""
            UPDATE projetos
            SET titulo = %s, slug = %s, descricao_curta = %s, descricao_longa = %s, video_url = %s, link_github = %s, link_deploy = %s, tipo_download = %s, destaque = %s
            {imagem_capa_sql}
            WHERE id = %s
        """
        params = [titulo, slug, descricao_curta, descricao_longa, video_url, link_github, link_deploy, tipo_download, destaque]
        if valores_extras:
            params.extend(valores_extras)
        params.append(id)

        cursor.execute(query, tuple(params))

        if "imagens_extras" in request.files:
            files = request.files.getlist("imagens_extras")
            for file in files:
                img_url = _salvar_upload(file)
                if img_url:
                    cursor.execute("INSERT INTO projeto_imagens (projeto_id, imagem_url) VALUES (%s, %s)", (id, img_url))

        conn.commit()
        cursor.close()
        conn.close()

        return redirect(url_for("admin", msg="Projeto atualizado com sucesso!"))

    cursor.execute("SELECT * FROM projetos WHERE id = %s", (id,))
    projeto = cursor.fetchone()
    cursor.close()
    conn.close()

    if not projeto:
        abort(404)

    return render_template("editar_projeto.html", projeto=projeto)


@app.route("/admin/projeto/deletar/<int:id>", methods=["POST"])
@login_required
def deletar_projeto(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM projetos WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for("admin", msg="Projeto excluído com sucesso!"))


@app.route("/admin/habilidade", methods=["POST"])
@login_required
def adicionar_habilidade():
    nome = request.form["nome"]
    categoria = request.form["categoria"]
    cor = request.form["cor"]
    cor_fundo = request.form["cor_fundo"]
    cor_texto = request.form["cor_texto"]

    conn = get_db_connection()
    cursor = conn.cursor()
    query = "INSERT INTO habilidades (nome, categoria, cor, cor_fundo, cor_texto) VALUES (%s, %s, %s, %s, %s)"
    cursor.execute(query, (nome, categoria, cor, cor_fundo, cor_texto))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for("admin", msg="Habilidade adicionada com sucesso!"))


@app.route("/admin/habilidade/editar/<int:id>", methods=["POST"])
@login_required
def editar_habilidade(id):
    nome = request.form["nome"]
    categoria = request.form["categoria"]
    cor = request.form["cor"]
    cor_fundo = request.form["cor_fundo"]
    cor_texto = request.form["cor_texto"]

    conn = get_db_connection()
    cursor = conn.cursor()
    query = "UPDATE habilidades SET nome = %s, categoria = %s, cor = %s, cor_fundo = %s, cor_texto = %s WHERE id = %s"
    cursor.execute(query, (nome, categoria, cor, cor_fundo, cor_texto, id))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for("admin", msg="Habilidade atualizada com sucesso!"))


@app.route("/admin/habilidade/deletar/<int:id>", methods=["POST"])
@login_required
def deletar_habilidade(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM habilidades WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for("admin", msg="Habilidade excluída com sucesso!"))


@app.route("/admin/sobre", methods=["POST"])
@login_required
def atualizar_sobre():
    titulo_principal = request.form["titulo_principal"]
    subtitulo = request.form.get("subtitulo", "")
    texto_home = request.form["texto_home"]
    biografia = request.form["biografia"]
    localizacao = request.form["localizacao"]
    email_contato = request.form["email_contato"]
    link_github = request.form["link_github"]
    link_linkedin = request.form["link_linkedin"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT id FROM sobre_mim LIMIT 1")
    resultado = cursor.fetchone()

    avatar_path = _salvar_upload(request.files.get("avatar"))
    avatar_sql = ", avatar_url = %s" if avatar_path else ""
    valores_avatar = [avatar_path] if avatar_path else []

    if resultado:
        sobre_id = resultado["id"]
        query = f"""
            UPDATE sobre_mim
            SET titulo_principal = %s, subtitulo = %s, texto_home = %s, biografia = %s, localizacao = %s, email_contato = %s, link_github = %s, link_linkedin = %s
            {avatar_sql}
            WHERE id = %s
        """
        params = [titulo_principal, subtitulo, texto_home, biografia, localizacao, email_contato, link_github, link_linkedin] + valores_avatar + [sobre_id]
        cursor.execute(query, tuple(params))
    else:
        query = """
            INSERT INTO sobre_mim (titulo_principal, subtitulo, texto_home, biografia, localizacao, email_contato, link_github, link_linkedin, avatar_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query, (titulo_principal, subtitulo, texto_home, biografia, localizacao, email_contato, link_github, link_linkedin, avatar_path))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for("admin", msg="Informações de perfil atualizadas com sucesso!"))


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode)