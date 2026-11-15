import os

import psycopg
from dotenv import load_dotenv

load_dotenv()


def conectar():
    configuracao = {
        "host": os.getenv("DB_HOST"),
        "port": os.getenv("DB_PORT"),
        "dbname": os.getenv("PE_DB_NAME"),
        "user": os.getenv("PE_DB_USER"),
        "password": os.getenv("PE_DB_PASSWORD"),
        "connect_timeout": 5,
    }

    ausentes = [
        campo
        for campo, valor in configuracao.items()
        if campo != "connect_timeout" and not valor
    ]

    if ausentes:
        raise RuntimeError(
            f"Configurações ausentes no .env: {ausentes}"
        )

    return psycopg.connect(**configuracao)
