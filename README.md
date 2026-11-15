# PE Inteligência

Plataforma de Inteligência Fiscal e Saúde Pública de Pernambuco.

## Objetivo

Construir uma plataforma de dados para integrar, organizar e analisar
informações públicas fiscais, demográficas e de saúde dos municípios
de Pernambuco.

## Abrangência

- Estado: Pernambuco.
- Municípios: 184.
- Fernando de Noronha: tratado separadamente como distrito estadual.
- Período histórico inicial proposto: 2022–2025.
- Limite máximo: 1.000.000 de registros físicos persistidos no projeto.

## Fontes de dados planejadas

- CONDEPE/FIDEM
- IBGE
- SICONFI
- TCE-PE
- SIOPS
- CNES/DATASUS

## Arquitetura planejada

1. Integração de fontes com Python.
2. Lakehouse com arquivos Parquet.
3. Validação e qualidade de dados.
4. Data Vault 2.0 no PostgreSQL.
5. Business Vault e Data Marts.
6. Transformações com dbt Core.
7. API analítica com FastAPI.
8. Orquestração com Apache Airflow.

## Tecnologias planejadas

- Python
- PostgreSQL
- DuckDB
- Parquet / PyArrow
- dbt Core
- Pandera
- FastAPI
- Apache Airflow
- Docker
- Pytest

## Princípios do projeto

- Utilizar fontes públicas e gratuitas.
- Registrar origem e período de referência dos dados.
- Preservar rastreabilidade e histórico.
- Validar dados antes de carregá-los.
- Evitar duplicidade entre fontes.
- Controlar o volume total persistido.
- Não inferir causalidade sem evidência adequada.

## Status

Em desenvolvimento. Arquitetura e fontes planejadas;
implementação e validação serão registradas conforme forem concluídas.
