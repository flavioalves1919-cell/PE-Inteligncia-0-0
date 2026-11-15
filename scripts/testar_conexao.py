import os

import psycopg
from dotenv import load_dotenv

load_dotenv()

configuracao = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
    "dbname": os.getenv("PE_DB_NAME"),
    "user": os.getenv("PE_DB_USER"),
    "password": os.getenv("PE_DB_PASSWORD"),
    "connect_timeout": 5,
}

obrigatorias = [
    "host", "port", "dbname", "user", "password"
]

ausentes = [
    campo for campo in obrigatorias
    if not configuracao.get(campo)
]

if ausentes:
    raise RuntimeError(
        f"Configurações ausentes: {ausentes}"
    )

try:
    with psycopg.connect(**configuracao) as conexao:
        with conexao.cursor() as cursor:
            cursor.execute("""
                SELECT
                    current_database(),
                    current_user,
                    version()
            """)

            banco, usuario, versao = cursor.fetchone()

            print("CONEXÃO ESTABELECIDA")
            print(f"Banco: {banco}")
            print(f"Usuário: {usuario}")
            print(f"Servidor: {versao.split(',')[0]}")

except psycopg.Error as erro:
    print(f"ERRO DE CONEXÃO: {erro}")
    raise
