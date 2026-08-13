import os
import io
import uuid
import re
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for, abort, session, flash
)
from flask_migrate import Migrate, upgrade as migrate_upgrade, stamp as migrate_stamp
from sqlalchemy import inspect as sa_inspect, text
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

# ---------------------------------------------------------------------------
# Armazenamento de imagens (Cloudflare R2 / S3-compatível)
#
# O Render tem sistema de arquivos EFÊMERO: qualquer arquivo salvo em disco
# (como as imagens enviadas pelo painel admin) é apagado sempre que o serviço
# reinicia, hiberna (plano free) ou faz um novo deploy. Por isso as imagens
# "somem depois de um tempo" mesmo com o banco (Aiven) intacto — o banco só
# guarda o caminho, o arquivo em si evaporava.
#
# Se as variáveis R2_* abaixo estiverem configuradas, os uploads vão para um
# bucket do Cloudflare R2 (armazenamento externo, persistente) e o app passa
# a servir a URL pública do bucket. Sem essas variáveis, o app cai de volta
# para salvar em disco local — útil só para rodar o projeto na sua máquina.
# ---------------------------------------------------------------------------
R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME")
R2_PUBLIC_BASE_URL = (os.environ.get("R2_PUBLIC_BASE_URL") or "").rstrip("/")

USE_R2 = all([R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME, R2_PUBLIC_BASE_URL])

_r2_client = None
if USE_R2:
    import boto3
    from botocore.config import Config as BotoConfig

    _r2_client = boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=BotoConfig(signature_version="s3v4"),
        region_name="auto",
    )
else:
    app.logger.warning(
        "R2 não configurado — uploads vão para o disco local, que é apagado "
        "a cada deploy/restart no Render. Configure as variáveis R2_* em produção."
    )

from sqlalchemy.engine import make_url

# ---------------------------------------------------------------------------
# Configuração do Banco de Dados
#
# Suporta tanto MySQL (Aiven, PlanetScale, etc. via PyMySQL) quanto
# PostgreSQL (Neon, Supabase, Render Postgres, etc. via psycopg2) — a escolha
# é automática, baseada no prefixo da própria DATABASE_URL. Isso deixa o app
# livre para trocar de provedor sem mexer em código, só trocando a variável
# de ambiente no Render.
# ---------------------------------------------------------------------------
database_url = os.environ.get("DATABASE_URL")
if database_url:
    # Remove espaços, quebras de linha e aspas que costumam sobrar ao colar
    # a connection string em painéis como o do Render.
    database_url = database_url.strip().strip('"').strip("'")

    if database_url.startswith("postgres://"):
        # Alguns provedores (Neon, Supabase, Heroku-style) ainda devolvem o
        # prefixo antigo "postgres://", que o SQLAlchemy 1.4+ não aceita mais.
        database_url = database_url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    elif database_url.startswith("mysql://"):
        database_url = database_url.replace("mysql://", "mysql+pymysql://", 1)

    base_url, _, query = database_url.partition("?")
    if base_url.startswith("mysql+pymysql://"):
        # A Aiven (e a maioria dos MySQL gerenciados) exige TLS.
        database_url = base_url + "?ssl_disabled=false"
    elif base_url.startswith("postgresql+psycopg2://"):
        # Neon, Supabase e Render Postgres exigem SSL; "require" funciona
        # nos três sem precisar de certificado customizado.
        params = dict(p.split("=", 1) for p in query.split("&") if "=" in p) if query else {}
        params.setdefault("sslmode", "require")
        database_url = base_url + "?" + "&".join(f"{k}={v}" for k, v in params.items())

    try:
        make_url(database_url)
    except Exception as e:
        # Uma DATABASE_URL malformada não pode derrubar o processo inteiro —
        # sem isso, o Gunicorn nunca abre a porta e o Render mata o deploy.
        print(f"[config] AVISO: DATABASE_URL inválida ou malformada ({e}).")
        print("[config] Confira a variável no painel do Render — copie a connection "
              "string direto do provedor, sem aspas nem espaços extras.")
        print("[config] Usando SQLite local temporário para o app conseguir subir.")
        database_url = "sqlite:///portfolio_local.db"
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


try:
    _sincronizar_schema()
except Exception as e:
    # Não deixa uma falha de conexão (banco fora do ar, DNS instável, etc.)
    # impedir o processo de subir — sem isso, o Gunicorn nunca chega a abrir
    # a porta e o Render mata o deploy com "No open ports detected", mesmo
    # que o problema seja só temporário no banco.
    print(f"[schema] AVISO: não foi possível sincronizar o schema na inicialização: {e}")
    print("[schema] A aplicação vai subir mesmo assim. Rotas que dependem do banco "
          "vão falhar até a conexão ser restabelecida (reinicie o serviço depois).")

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

        projetos_raw = conn.exec_driver_sql("""
            SELECT id, titulo, slug, descricao_curta, imagem_capa, video_url, link_github, link_deploy, tipo_download, destaque, criado_em
            FROM projetos
            WHERE destaque = 1
            ORDER BY criado_em DESC
            LIMIT 3
        """).mappings().all()

        habilidades_destaque = conn.exec_driver_sql("SELECT * FROM habilidades WHERE destaque = 1").mappings().all()

    # Trunca a descrição curta em Python (em vez de SQL) para funcionar
    # tanto em MySQL quanto no fallback SQLite, cujas funções de string
    # (IF/CHAR_LENGTH/CONCAT/SUBSTRING) não são as mesmas.
    projetos = []
    for p in projetos_raw:
        p = dict(p)
        desc = p.get("descricao_curta") or ""
        if len(desc) > 110:
            p["descricao_curta"] = desc[:107] + "..."
        projetos.append(p)

    return render_template("index.html", sobre=sobre, projetos=projetos, habilidades_destaque=habilidades_destaque)


@app.route("/projetos")
def todos_projetos():
    with db.engine.connect() as conn:
        sobre = conn.exec_driver_sql("SELECT * FROM sobre_mim LIMIT 1").mappings().fetchone()
        projetos = conn.exec_driver_sql("SELECT * FROM projetos ORDER BY criado_em DESC").mappings().all()

    return render_template("todos_projetos.html", sobre=sobre, projetos=projetos)


@app.route("/habilidades")
def listar_habilidades():
    with db.engine.connect() as conn:
        sobre = conn.exec_driver_sql("SELECT * FROM sobre_mim LIMIT 1").mappings().fetchone()
        habilidades = conn.exec_driver_sql(
            "SELECT * FROM habilidades ORDER BY categoria ASC, nome ASC"
        ).mappings().all()

    return render_template("todas_habilidades.html", sobre=sobre, habilidades=habilidades)


def _normalizar_data(valor):
    """
    Garante que 'criado_em' seja sempre um datetime real antes de ir para o
    template (que chama .strftime nele). Em MySQL o driver já devolve um
    datetime.datetime; no fallback SQLite o valor volta como string, o que
    quebrava a página de detalhe do projeto com 'str object has no
    attribute strftime'.
    """
    if valor is None or isinstance(valor, datetime):
        return valor
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(valor), fmt)
        except ValueError:
            continue
    return valor


@app.route("/projeto/<string:slug>")
def detalhes_projeto(slug):
    with db.engine.connect() as conn:
        projeto = conn.execute(text("SELECT * FROM projetos WHERE slug = :slug"), {"slug": slug}).mappings().fetchone()

        if not projeto:
            abort(404)

        imagens_extras = conn.execute(
            text("SELECT * FROM projeto_imagens WHERE projeto_id = :pid"), {"pid": projeto["id"]}
        ).mappings().all()

    projeto = dict(projeto)
    projeto["criado_em"] = _normalizar_data(projeto.get("criado_em"))

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


_EXT_TO_PIL_FORMAT = {
    "jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP", "gif": "GIF"
}
_PIL_FORMAT_TO_CONTENT_TYPE = {
    "JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "GIF": "image/gif"
}


def _salvar_upload(file_storage):
    if not (file_storage and file_storage.filename != "" and arquivo_permitido(file_storage.filename)):
        return None

    filename = nome_arquivo_seguro(file_storage.filename)
    ext = filename.rsplit(".", 1)[1].lower()
    pil_format = _EXT_TO_PIL_FORMAT.get(ext, "JPEG")

    # Processa/otimiza a imagem em memória (funciona igual para R2 ou disco local)
    buffer = io.BytesIO()
    try:
        img = Image.open(file_storage)
        if pil_format == "JPEG" and img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
        save_kwargs = {"optimize": True}
        if pil_format == "JPEG":
            save_kwargs["quality"] = 85
        img.save(buffer, format=pil_format, **save_kwargs)
        content_type = _PIL_FORMAT_TO_CONTENT_TYPE.get(pil_format, "application/octet-stream")
    except Exception:
        file_storage.seek(0)
        buffer.write(file_storage.read())
        content_type = file_storage.mimetype or "application/octet-stream"
    buffer.seek(0)

    if USE_R2:
        _r2_client.upload_fileobj(
            buffer, R2_BUCKET_NAME, filename,
            ExtraArgs={"ContentType": content_type, "CacheControl": "public, max-age=31536000, immutable"}
        )
        return f"{R2_PUBLIC_BASE_URL}/{filename}"

    # Fallback: disco local (só persiste em ambiente de desenvolvimento)
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    with open(filepath, "wb") as f:
        f.write(buffer.getbuffer())
    return f"/static/uploads/{filename}"


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
            res = conn.execute(text("SELECT COUNT(*) as total FROM projetos WHERE destaque = 1")).fetchone()
            if res[0] >= 3:
                return redirect(url_for(
                    "admin",
                    erro_destaque="Limite de 3 projetos em destaque atingido! Retire o destaque de algum projeto existente."
                ))

        imagem_capa_path = _salvar_upload(request.files.get("imagem_capa"))

        query = text("""
            INSERT INTO projetos (titulo, slug, descricao_curta, descricao_longa, imagem_capa, video_url, link_github, link_deploy, tipo_download, destaque)
            VALUES (:titulo, :slug, :descricao_curta, :descricao_longa, :imagem_capa, :video_url, :link_github, :link_deploy, :tipo_download, :destaque)
        """)
        cursor = conn.execute(query, {
            "titulo": titulo, "slug": slug, "descricao_curta": descricao_curta,
            "descricao_longa": descricao_longa, "imagem_capa": imagem_capa_path,
            "video_url": video_url, "link_github": link_github, "link_deploy": link_deploy,
            "tipo_download": tipo_download, "destaque": destaque
        })
        projeto_id = cursor.lastrowid

        if "imagens_extras" in request.files:
            files = request.files.getlist("imagens_extras")
            for file in files:
                img_url = _salvar_upload(file)
                if img_url:
                    conn.execute(
                        text("INSERT INTO projeto_imagens (projeto_id, imagem_url) VALUES (:pid, :url)"),
                        {"pid": projeto_id, "url": img_url}
                    )

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
                res = conn.execute(
                    text("SELECT COUNT(*) as total FROM projetos WHERE destaque = 1 AND id != :id"), {"id": id}
                ).fetchone()
                if res[0] >= 3:
                    return redirect(url_for("admin", erro_destaque="Limite de 3 projetos em destaque atingido!"))

            imagem_capa_path = _salvar_upload(request.files.get("imagem_capa"))

            params = {
                "titulo": titulo, "slug": slug, "descricao_curta": descricao_curta,
                "descricao_longa": descricao_longa, "video_url": video_url,
                "link_github": link_github, "link_deploy": link_deploy,
                "tipo_download": tipo_download, "destaque": destaque, "id": id
            }

            if imagem_capa_path:
                query = text("""
                    UPDATE projetos
                    SET titulo = :titulo, slug = :slug, descricao_curta = :descricao_curta, descricao_longa = :descricao_longa, video_url = :video_url, link_github = :link_github, link_deploy = :link_deploy, tipo_download = :tipo_download, destaque = :destaque, imagem_capa = :imagem_capa
                    WHERE id = :id
                """)
                params["imagem_capa"] = imagem_capa_path
                conn.execute(query, params)
            else:
                query = text("""
                    UPDATE projetos
                    SET titulo = :titulo, slug = :slug, descricao_curta = :descricao_curta, descricao_longa = :descricao_longa, video_url = :video_url, link_github = :link_github, link_deploy = :link_deploy, tipo_download = :tipo_download, destaque = :destaque
                    WHERE id = :id
                """)
                conn.execute(query, params)

            if "imagens_extras" in request.files:
                files = request.files.getlist("imagens_extras")
                for file in files:
                    img_url = _salvar_upload(file)
                    if img_url:
                        conn.execute(
                            text("INSERT INTO projeto_imagens (projeto_id, imagem_url) VALUES (:pid, :url)"),
                            {"pid": id, "url": img_url}
                        )

        return redirect(url_for("admin", msg="Projeto atualizado com sucesso!"))

    with db.engine.connect() as conn:
        projeto = conn.execute(text("SELECT * FROM projetos WHERE id = :id"), {"id": id}).mappings().fetchone()

    if not projeto:
        abort(404)

    return render_template("editar_projeto.html", projeto=projeto)


@app.route("/admin/projeto/deletar/<int:id>", methods=["POST"])
@login_required
def deletar_projeto(id):
    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM projetos WHERE id = :id"), {"id": id})
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
        conn.execute(
            text("INSERT INTO habilidades (nome, categoria, cor, cor_fundo, cor_texto, destaque) VALUES (:nome, :categoria, :cor, :cor_fundo, :cor_texto, :destaque)"),
            {"nome": nome, "categoria": categoria, "cor": cor, "cor_fundo": cor_fundo, "cor_texto": cor_texto, "destaque": destaque}
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
            conn.execute(
                text("UPDATE habilidades SET nome = :nome, categoria = :categoria, cor = :cor, cor_fundo = :cor_fundo, cor_texto = :cor_texto, destaque = :destaque WHERE id = :id"),
                {"nome": nome, "categoria": categoria, "cor": cor, "cor_fundo": cor_fundo, "cor_texto": cor_texto, "destaque": destaque, "id": id}
            )
        return redirect(url_for("admin", msg="Habilidade atualizada com sucesso!"))
    
    return redirect(url_for("admin"))


@app.route("/admin/habilidade/deletar/<int:id>", methods=["POST"])
@login_required
def deletar_habilidade(id):
    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM habilidades WHERE id = :id"), {"id": id})
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
        resultado = conn.execute(text("SELECT id FROM sobre_mim LIMIT 1")).fetchone()
        avatar_path = _salvar_upload(request.files.get("avatar"))

        params = {
            "titulo_principal": titulo_principal, "subtitulo": subtitulo, "texto_home": texto_home,
            "biografia": biografia, "localizacao": localizacao, "email_contato": email_contato,
            "link_github": link_github, "link_linkedin": link_linkedin
        }

        if resultado:
            sobre_id = resultado[0]
            params["id"] = sobre_id
            if avatar_path:
                params["avatar_url"] = avatar_path
                conn.execute(
                    text("""UPDATE sobre_mim SET titulo_principal = :titulo_principal, subtitulo = :subtitulo, texto_home = :texto_home, biografia = :biografia,
                       localizacao = :localizacao, email_contato = :email_contato, link_github = :link_github, link_linkedin = :link_linkedin, avatar_url = :avatar_url WHERE id = :id"""),
                    params
                )
            else:
                conn.execute(
                    text("""UPDATE sobre_mim SET titulo_principal = :titulo_principal, subtitulo = :subtitulo, texto_home = :texto_home, biografia = :biografia,
                       localizacao = :localizacao, email_contato = :email_contato, link_github = :link_github, link_linkedin = :link_linkedin WHERE id = :id"""),
                    params
                )
        else:
            params["avatar_url"] = avatar_path
            conn.execute(
                text("""INSERT INTO sobre_mim (titulo_principal, subtitulo, texto_home, biografia, localizacao, email_contato, link_github, link_linkedin, avatar_url)
                   VALUES (:titulo_principal, :subtitulo, :texto_home, :biografia, :localizacao, :email_contato, :link_github, :link_linkedin, :avatar_url)"""),
                params
            )

    return redirect(url_for("admin", msg="Informações do perfil atualizadas com sucesso!"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)