"""
Models SQLAlchemy — fonte única de verdade para o schema do banco.

Antes, as tabelas eram criadas com CREATE TABLE cru dentro de um
try/except no app.py, o que fazia qualquer alteração de schema
(ex: nova coluna) ser silenciosamente ignorada em produção.

Agora o schema vive aqui, e é versionado com Flask-Migrate (Alembic).
Para aplicar mudanças:
    1. Edite os models abaixo
    2. flask db migrate -m "descrição da mudança"
    3. flask db upgrade
"""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class SobreMim(db.Model):
    __tablename__ = "sobre_mim"

    id = db.Column(db.Integer, primary_key=True)
    titulo_principal = db.Column(db.String(255), nullable=False)
    subtitulo = db.Column(db.String(255))
    texto_home = db.Column(db.Text)
    biografia = db.Column(db.Text)
    localizacao = db.Column(db.String(100))
    email_contato = db.Column(db.String(100))
    link_github = db.Column(db.String(255))
    link_linkedin = db.Column(db.String(255))
    avatar_url = db.Column(db.String(255))


class Projeto(db.Model):
    __tablename__ = "projetos"

    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), nullable=False, unique=True)
    descricao_curta = db.Column(db.String(255), nullable=False)
    descricao_longa = db.Column(db.Text)
    imagem_capa = db.Column(db.String(255))
    video_url = db.Column(db.String(255))
    link_github = db.Column(db.String(255))
    link_deploy = db.Column(db.String(255))
    tipo_download = db.Column(db.String(50))
    destaque = db.Column(db.SmallInteger, default=0)
    criado_em = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp())

    imagens = db.relationship(
        "ProjetoImagem", backref="projeto", cascade="all, delete-orphan"
    )


class ProjetoImagem(db.Model):
    __tablename__ = "projeto_imagens"

    id = db.Column(db.Integer, primary_key=True)
    projeto_id = db.Column(db.Integer, db.ForeignKey("projetos.id", ondelete="CASCADE"))
    imagem_url = db.Column(db.String(255), nullable=False)


class Habilidade(db.Model):
    __tablename__ = "habilidades"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    categoria = db.Column(db.String(100))
    cor = db.Column(db.String(50))
    cor_fundo = db.Column(db.String(50))
    cor_texto = db.Column(db.String(50))
    destaque = db.Column(db.SmallInteger, default=0)
