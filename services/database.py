import os
import mysql.connector
from mysql.connector import pooling

_pool = None

def _get_pool():
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            host=os.getenv('DB_HOST', 'srv1078.hstgr.io'),
            port=int(os.getenv('DB_PORT', 3306)),
            database=os.getenv('DB_NAME', 'u549746795_kealabs'),
            user=os.getenv('DB_USER', 'u549746795_kealabs'),
            password=os.getenv('DB_PASSWORD', 'Sally2025@!'),
            pool_name='mypool',
            pool_size=5
        )
    return _pool

def get_db():
    return _get_pool().get_connection()
