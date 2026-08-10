import os
import uuid
import re
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for, abort, session, flash
)
from flask_migrate import Migrate, upgrade as migrate_upgrade, stamp as migrate_stamp
from sqlalchemy import inspect as sa_inspect
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash
import bleach
from bleach.css_sanitizer import CSSSanitizer
from PIL import Image
from dotenv import load_dotenv

from models import db

load_dotenv()

app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError(
        "SECRET_KEY não definida. Configure-a no arquivo .env."
    )

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Configuração do Banco de Dados via SQLAlchemy com suporte a Aiven (PyMySQL + SSL)
database_url = os.environ.get("DATABASE_URL")
if database_url:
    if database_url.startswith("mysql://"):
        database_url = database_url.replace("mysql://", "mysql+pymysql://", 1)
    database_url = database_url.split("?")[0] + "?ssl_disabled=false"
else:
    database_url = "sqlite:///portfolio_local.db"

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
migrate = Migrate(app, db)


def _sincronizar_schema():
    """
    Sincroniza o schema do banco automaticamente na inicialização da app —
    necessário porque o plano gratuito do Render não dá acesso a Shell nem
    a comandos de pre-deploy, então não dá pra rodar `flask db upgrade`
    manualmente.

    Comportamento:
    - Se o banco já tem a tabela de controle do Alembic (`alembic_version`),
      apenas aplica migrações pendentes normalmente (idempotente: não faz
      nada se já estiver tudo em dia).
    - Se não tem (banco criado antes da migração para Flask-Migrate, ou
      banco novo em branco), cria as tabelas/colunas que estiverem
      faltando comparando com os models, e então marca o banco como
      já sincronizado com a migração atual (stamp), sem tentar recriar
      o que já existe.
    """
    with app.app_context():
        inspector = sa_inspect(db.engine)
        tabelas_existentes = inspector.get_table_names()

        if "alembic_version" in tabelas_existentes:
            migrate_upgrade()
            print("[schema] Migrações aplicadas (banco já era gerenciado por Alembic).")
            return

        mudou_algo = False
        for tabela in db.metadata.sorted_tables:
            if tabela.name not in tabelas_existentes:
                tabela.create(bind=db.engine)
                print(f"[schema] Tabela '{tabela.name}' criada.")
                mudou_algo = True
                continue

            colunas_atuais = {c["name"] for c in inspector.get_columns(tabela.name)}
            for coluna in tabela.columns:
                if coluna.name in colunas_atuais:
                    continue
                tipo_sql = coluna.type.compile(dialect=db.engine.dialect)
                with db.engine.begin() as conn:
                    conn.exec_driver_sql(
                        f"ALTER TABLE {tabela.name} ADD COLUMN {coluna.name} {tipo_sql}"
                    )
                print(f"[schema] Coluna '{coluna.name}' adicionada em '{tabela.name}'.")
                mudou_algo = True

        migrate_stamp()
        status = "colunas/tabelas ajustadas" if mudou_algo else "já estava em dia"
        print(f"[schema] Banco sincronizado com a migração atual ({status}).")


_sincronizar_schema()

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
    texto = re.sub(r'<color:(#[0-9a-fA-F]{3,6})>(.*?)</color>', r'<span style="color: \1;">\2</span>', texto)
    
    css_sanitizer = CSSSanitizer(allowed_css_properties=['color'])
    return bleach.clean(
        texto, 
        tags=TAGS_PERMITIDAS, 
        attributes=ATRIBUTOS_PERMITIDOS, 
        css_sanitizer=css_sanitizer,
        strip=True
    )


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
    with db.engine.connect() as conn:
        sobre = conn.exec_driver_sql("SELECT * FROM sobre_mim LIMIT 1").mappings().fetchone()

        projetos = conn.exec_driver_sql("""
            SELECT id, titulo, slug, imagem_capa, video_url, link_github, link_deploy, tipo_download, destaque, criado_em,
                   IF(CHAR_LENGTH(descricao_curta) > 110, CONCAT(SUBSTRING(descricao_curta, 1, 107), '...'), descricao_curta) AS descricao_curta
            FROM projetos 
            WHERE destaque = 1 
            ORDER BY criado_em DESC 
            LIMIT 3
        """).mappings().all()

        habilidades_destaque = conn.exec_driver_sql("SELECT * FROM habilidades WHERE destaque = 1").mappings().all()

    return render_template("index.html", sobre=sobre, projetos=projetos, habilidades_destaque=habilidades_destaque)


@app.route("/projetos")
def todos_projetos():
    with db.engine.connect() as conn:
        sobre = conn.exec_driver_sql("SELECT * FROM sobre_mim LIMIT 1").mappings().fetchone()
        projetos = conn.exec_driver_sql("SELECT * FROM projetos ORDER BY criado_em DESC").mappings().all()

    return render_template("todos_projetos.html", sobre=sobre, projetos=projetos)


@app.route("/habilidades")
def listar_habilidades():
    return redirect(url_for("home") + "#habilidades")


@app.route("/projeto/<string:slug>")
def detalhes_projeto(slug):
    with db.engine.connect() as conn:
        projeto = conn.exec_driver_sql("SELECT * FROM projetos WHERE slug = %s", (slug,)).mappings().fetchone()

        if not projeto:
            abort(404)

        imagens_extras = conn.exec_driver_sql("SELECT * FROM projeto_imagens WHERE projeto_id = %s", (projeto["id"],)).mappings().all()

    return render_template("projeto.html", projeto=projeto, imagens_extras=imagens_extras)


@app.route("/admin", methods=["GET"])
@login_required
def admin():
    with db.engine.connect() as conn:
        sobre = conn.exec_driver_sql("SELECT * FROM sobre_mim LIMIT 1").mappings().fetchone()
        projetos = conn.exec_driver_sql("SELECT * FROM projetos ORDER BY criado_em DESC").mappings().all()
        habilidades = conn.exec_driver_sql("SELECT * FROM habilidades").mappings().all()

    msg = request.args.get("msg")
    erro_destaque = request.args.get("erro_destaque")

    return render_template(
        "admin.html", sobre=sobre, projetos=projetos, habilidades=habilidades,
        msg=msg, erro_destaque=erro_destaque
    )


def _salvar_upload(file_storage):
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

    with db.engine.begin() as conn:
        if destaque == 1:
            res = conn.exec_driver_sql("SELECT COUNT(*) as total FROM projetos WHERE destaque = 1").fetchone()
            if res[0] >= 3:
                return redirect(url_for(
                    "admin",
                    erro_destaque="Limite de 3 projetos em destaque atingido! Retire o destaque de algum projeto existente."
                ))

        imagem_capa_path = _salvar_upload(request.files.get("imagem_capa"))

        query = """
            INSERT INTO projetos (titulo, slug, descricao_curta, descricao_longa, imagem_capa, video_url, link_github, link_deploy, tipo_download, destaque)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor = conn.exec_driver_sql(query, (titulo, slug, descricao_curta, descricao_longa, imagem_capa_path, video_url, link_github, link_deploy, tipo_download, destaque))
        projeto_id = cursor.lastrowid

        if "imagens_extras" in request.files:
            files = request.files.getlist("imagens_extras")
            for file in files:
                img_url = _salvar_upload(file)
                if img_url:
                    conn.exec_driver_sql("INSERT INTO projeto_imagens (projeto_id, imagem_url) VALUES (%s, %s)", (projeto_id, img_url))

    return redirect(url_for("admin", msg="Projeto publicado com sucesso!"))


@app.route("/admin/projeto/editar/<int:id>", methods=["GET", "POST"])
@login_required
def editar_projeto(id):
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

        with db.engine.begin() as conn:
            if destaque == 1:
                res = conn.exec_driver_sql("SELECT COUNT(*) as total FROM projetos WHERE destaque = 1 AND id != %s", (id,)).fetchone()
                if res[0] >= 3:
                    return redirect(url_for("admin", erro_destaque="Limite de 3 projetos em destaque atingido!"))

            imagem_capa_path = _salvar_upload(request.files.get("imagem_capa"))
            
            if imagem_capa_path:
                query = """
                    UPDATE projetos
                    SET titulo = %s, slug = %s, descricao_curta = %s, descricao_longa = %s, video_url = %s, link_github = %s, link_deploy = %s, tipo_download = %s, destaque = %s, imagem_capa = %s
                    WHERE id = %s
                """
                conn.exec_driver_sql(query, (titulo, slug, descricao_curta, descricao_longa, video_url, link_github, link_deploy, tipo_download, destaque, imagem_capa_path, id))
            else:
                query = """
                    UPDATE projetos
                    SET titulo = %s, slug = %s, descricao_curta = %s, descricao_longa = %s, video_url = %s, link_github = %s, link_deploy = %s, tipo_download = %s, destaque = %s
                    WHERE id = %s
                """
                conn.exec_driver_sql(query, (titulo, slug, descricao_curta, descricao_longa, video_url, link_github, link_deploy, tipo_download, destaque, id))

            if "imagens_extras" in request.files:
                files = request.files.getlist("imagens_extras")
                for file in files:
                    img_url = _salvar_upload(file)
                    if img_url:
                        conn.exec_driver_sql("INSERT INTO projeto_imagens (projeto_id, imagem_url) VALUES (%s, %s)", (id, img_url))

        return redirect(url_for("admin", msg="Projeto atualizado com sucesso!"))

    with db.engine.connect() as conn:
        projeto = conn.exec_driver_sql("SELECT * FROM projetos WHERE id = %s", (id,)).mappings().fetchone()

    if not projeto:
        abort(404)

    return render_template("editar_projeto.html", projeto=projeto)


@app.route("/admin/projeto/deletar/<int:id>", methods=["POST"])
@login_required
def deletar_projeto(id):
    with db.engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM projetos WHERE id = %s", (id,))
    return redirect(url_for("admin", msg="Projeto excluído com sucesso!"))


@app.route("/admin/habilidade", methods=["POST"])
@login_required
def adicionar_habilidade():
    nome = request.form["nome"]
    categoria = request.form["categoria"]
    cor = request.form["cor"]
    cor_fundo = request.form["cor_fundo"]
    cor_texto = request.form["cor_texto"]
    destaque = 1 if "destaque" in request.form else 0

    with db.engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO habilidades (nome, categoria, cor, cor_fundo, cor_texto, destaque) VALUES (%s, %s, %s, %s, %s, %s)",
            (nome, categoria, cor, cor_fundo, cor_texto, destaque)
        )
    return redirect(url_for("admin", msg="Habilidade adicionada com sucesso!"))


@app.route("/admin/habilidade/editar/<int:id>", methods=["GET", "POST"])
@login_required
def editar_habilidade(id):
    if request.method == "POST":
        nome = request.form["nome"]
        categoria = request.form["categoria"]
        cor = request.form["cor"]
        cor_fundo = request.form["cor_fundo"]
        cor_texto = request.form["cor_texto"]
        destaque = 1 if "destaque" in request.form else 0

        with db.engine.begin() as conn:
            conn.exec_driver_sql(
                "UPDATE habilidades SET nome = %s, categoria = %s, cor = %s, cor_fundo = %s, cor_texto = %s, destaque = %s WHERE id = %s",
                (nome, categoria, cor, cor_fundo, cor_texto, destaque, id)
            )
        return redirect(url_for("admin", msg="Habilidade atualizada com sucesso!"))
    
    return redirect(url_for("admin"))


@app.route("/admin/habilidade/deletar/<int:id>", methods=["POST"])
@login_required
def deletar_habilidade(id):
    with db.engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM habilidades WHERE id = %s", (id,))
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

    with db.engine.begin() as conn:
        resultado = conn.exec_driver_sql("SELECT id FROM sobre_mim LIMIT 1").fetchone()
        avatar_path = _salvar_upload(request.files.get("avatar"))

        if resultado:
            sobre_id = resultado[0]
            if avatar_path:
                conn.exec_driver_sql(
                    """UPDATE sobre_mim SET titulo_principal = %s, subtitulo = %s, texto_home = %s, biografia = %s, 
                       localizacao = %s, email_contato = %s, link_github = %s, link_linkedin = %s, avatar_url = %s WHERE id = %s""",
                    (titulo_principal, subtitulo, texto_home, biografia, localizacao, email_contato, link_github, link_linkedin, avatar_path, sobre_id)
                )
            else:
                conn.exec_driver_sql(
                    """UPDATE sobre_mim SET titulo_principal = %s, subtitulo = %s, texto_home = %s, biografia = %s, 
                       localizacao = %s, email_contato = %s, link_github = %s, link_linkedin = %s WHERE id = %s""",
                    (titulo_principal, subtitulo, texto_home, biografia, localizacao, email_contato, link_github, link_linkedin, sobre_id)
                )
        else:
            conn.exec_driver_sql(
                """INSERT INTO sobre_mim (titulo_principal, subtitulo, texto_home, biografia, localizacao, email_contato, link_github, link_linkedin, avatar_url)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (titulo_principal, subtitulo, texto_home, biografia, localizacao, email_contato, link_github, link_linkedin, avatar_path)
            )

    return redirect(url_for("admin", msg="Informações do perfil atualizadas com sucesso!"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)