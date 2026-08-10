DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "mysql-203b7745-nathannmr.d.aivencloud.com"),
    "port": int(os.environ.get("DB_PORT", 20110)),
    "user": os.environ.get("DB_USER", "avnadmin"),
    "password": os.environ.get("DB_PASSWORD"),
    "database": os.environ.get("DB_NAME", "defaultdb"),
}

if DB_CONFIG["host"] != "localhost":
    DB_CONFIG["ssl_disabled"] = False

if not DB_CONFIG["password"]:
    raise RuntimeError(
        "DB_PASSWORD não definida. Configure-a no arquivo .env ou no Render."
    )

connection_pool = pooling.MySQLConnectionPool(
    pool_name="portfolio_pool",
    pool_size=5,
    **DB_CONFIG
)
