import os
import mysql.connector
from mysql.connector import pooling

db_config = {
    'host': os.getenv('DB_HOST', 'srv1078.hstgr.io'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'database': os.getenv('DB_NAME', 'u549746795_kealabs'),
    'user': os.getenv('DB_USER', 'u549746795_kealabs'),
    'password': os.getenv('DB_PASSWORD', 'Sally2025@!'),
    'pool_name': 'mypool',
    'pool_size': 5
}

connection_pool = pooling.MySQLConnectionPool(**db_config)

def get_db():
    return connection_pool.get_connection()
