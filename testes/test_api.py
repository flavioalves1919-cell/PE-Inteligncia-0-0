from fastapi.testclient import TestClient

from api.main import app, executar_consulta


client = TestClient(app)


def test_inicio():
    resposta = client.get("/")
    assert resposta.status_code == 200
    assert resposta.json()["plataforma"] == "PE Inteligência"
    assert resposta.json()["status"] == "online"


def test_health(monkeypatch):
    monkeypatch.setattr(
        "api.main.executar_consulta",
        lambda sql, parametros=(): [
            {"banco": "pe_inteligencia", "usuario": "pe_admin"}
        ],
    )

    resposta = client.get("/health")

    assert resposta.status_code == 200
    assert resposta.json()["status"] == "healthy"
    assert resposta.json()["database"] == "pe_inteligencia"


def test_mortalidade_infantil(monkeypatch):
    monkeypatch.setattr(
        "api.main.executar_consulta",
        lambda sql, parametros=(): [
            {"ano": 2024, "codigo_ibge": "2611606", "nome_localidade": "Recife"}
        ],
    )

    resposta = client.get(
        "/saude/mortalidade-infantil",
        params={"ano": 2024, "codigo_ibge": "2611606"},
    )

    assert resposta.status_code == 200
    assert resposta.json()[0]["nome_localidade"] == "Recife"


def test_despesas_fiscais(monkeypatch):
    monkeypatch.setattr(
        "api.main.executar_consulta",
        lambda sql, parametros=(): [
            {
                "ano": 2024,
                "codigo_ibge": "2611606",
                "codigo_estagio": "Despesas Liquidadas",
                "valor_total": "1937953959.80",
            }
        ],
    )

    resposta = client.get(
        "/fiscal/despesas",
        params={"ano": 2024, "codigo_ibge": "2611606"},
    )

    assert resposta.status_code == 200
    assert resposta.json()[0]["valor_total"] == "1937953959.80"


def test_execucao_orcamentaria(monkeypatch):
    monkeypatch.setattr(
        "api.main.executar_consulta",
        lambda sql, parametros=(): [
            {
                "ano": 2024,
                "codigo_ibge": "2611606",
                "despesas_liquidadas": "1937953959.80",
            }
        ],
    )

    resposta = client.get(
        "/fiscal/execucao-orcamentaria",
        params={"ano": 2024, "codigo_ibge": "2611606"},
    )

    assert resposta.status_code == 200
    assert resposta.json()[0]["despesas_liquidadas"] == "1937953959.80"


def test_detalhamento_fiscal(monkeypatch):
    monkeypatch.setattr(
        "api.main.executar_consulta",
        lambda sql, parametros=(): [
            {
                "ano": 2024,
                "codigo_ibge": "2611606",
                "codigo_classificacao": "10.301",
                "descricao_classificacao": "Atenção Básica",
            }
        ],
    )

    resposta = client.get(
        "/fiscal/detalhamento",
        params={"ano": 2024, "codigo_ibge": "2611606"},
    )

    assert resposta.status_code == 200
    assert resposta.json()[0]["codigo_classificacao"] == "10.301"


def test_filtro_ano_invalido():
    resposta = client.get(
        "/fiscal/despesas",
        params={"ano": 1800},
    )

    assert resposta.status_code == 422


def test_codigo_ibge_invalido():
    resposta = client.get(
        "/saude/mortalidade-infantil",
        params={"codigo_ibge": "123"},
    )

    assert resposta.status_code == 422


def test_openapi():
    resposta = client.get("/openapi.json")

    assert resposta.status_code == 200
    assert resposta.json()["info"]["title"] == "PE Inteligência API"
