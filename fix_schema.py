"""
Script de correção pontual de schema: garante que colunas novas existam
nas tabelas já criadas em produção (Aiven/MySQL).

Uso:
    DATABASE_URL="mysql://usuario:senha@host:porta/banco" python fix_schema.py

Ou, se já tiver o .env configurado com DATABASE_URL, basta:
    python fix_schema.py
"""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, inspect

load_dotenv()

database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError("Defina DATABASE_URL antes de rodar este script.")

if database_url.startswith("mysql://"):
    database_url = database_url.replace("mysql://", "mysql+pymysql://", 1)
database_url = database_url.split("?")[0] + "?ssl_disabled=false"

engine = create_engine(database_url)
inspector = inspect(engine)

# Colunas esperadas por tabela: nome -> definição SQL para ADD COLUMN
COLUNAS_ESPERADAS = {
    "habilidades": {
        "nome": "VARCHAR(100) NOT NULL",
        "categoria": "VARCHAR(100)",
        "cor": "VARCHAR(50)",
        "cor_fundo": "VARCHAR(50)",
        "cor_texto": "VARCHAR(50)",
        "destaque": "TINYINT DEFAULT 0",
    },
    "projetos": {
        "titulo": "VARCHAR(255) NOT NULL",
        "slug": "VARCHAR(255) NOT NULL",
        "descricao_curta": "VARCHAR(255) NOT NULL",
        "descricao_longa": "TEXT",
        "imagem_capa": "VARCHAR(255)",
        "video_url": "VARCHAR(255)",
        "link_github": "VARCHAR(255)",
        "link_deploy": "VARCHAR(255)",
        "tipo_download": "VARCHAR(50)",
        "destaque": "TINYINT DEFAULT 0",
        "criado_em": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    },
    "sobre_mim": {
        "titulo_principal": "VARCHAR(255) NOT NULL",
        "subtitulo": "VARCHAR(255)",
        "texto_home": "TEXT",
        "biografia": "TEXT",
        "localizacao": "VARCHAR(100)",
        "email_contato": "VARCHAR(100)",
        "link_github": "VARCHAR(255)",
        "link_linkedin": "VARCHAR(255)",
        "avatar_url": "VARCHAR(255)",
    },
}

with engine.begin() as conn:
    tabelas_existentes = inspector.get_table_names()

    for tabela, colunas in COLUNAS_ESPERADAS.items():
        if tabela not in tabelas_existentes:
            print(f"[skip] Tabela '{tabela}' não existe ainda (será criada pelo app.py normalmente).")
            continue

        colunas_atuais = {c["name"] for c in inspector.get_columns(tabela)}

        for coluna, definicao in colunas.items():
            if coluna in colunas_atuais:
                continue
            print(f"[fix] Adicionando coluna '{coluna}' em '{tabela}'...")
            # NOT NULL sem default precisa de tratamento especial; simplificamos removendo NOT NULL no ALTER
            definicao_alter = definicao.replace(" NOT NULL", "")
            conn.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao_alter}"))

print("Schema verificado e corrigido com sucesso.")
