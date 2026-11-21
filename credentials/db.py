import os
from psycopg2 import pool
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

db_pool = pool.ThreadedConnectionPool(
    minconn=1,
    maxconn=10,
    dsn=os.getenv("POSTGRES_URI"),
    sslmode="require"
)

def get_conn():
    return db_pool.getconn()

def release_conn(conn):
    if conn:
        db_pool.putconn(conn)