from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)

def get_session():
    return Session()

def init_schema():
    """Run schema.sql against the configured Postgres database."""
    with open(__file__.replace("connection.py", "schema.sql")) as f:
        ddl = f.read()
    with engine.begin() as conn:
        for stmt in ddl.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)
