# PE Inteligência

**Plataforma de Inteligência Fiscal e Saúde Pública de Pernambuco**

Plataforma de engenharia de dados desenvolvida para integrar, validar, processar e disponibilizar dados públicos fiscais e de saúde dos municípios pernambucanos.

O projeto utiliza pipelines em Python, armazenamento analítico em Parquet, PostgreSQL e uma API REST para disponibilização de indicadores.

## Objetivo

Construir uma plataforma de dados capaz de transformar dados públicos em informações estruturadas, rastreáveis e consultáveis, apoiando análises sobre a gestão fiscal e a saúde pública de Pernambuco.

## Abrangência

- Estado: Pernambuco.
- Municípios: 184.
- Fernando de Noronha: tratado separadamente como distrito estadual.
- Período inicial dos dados de saúde: 2022–2024.
- Exercício fiscal utilizado como referência inicial: 2024.
- Limite de projeto: até 1 milhão de registros físicos persistidos.

A cobertura estadual é o objetivo da plataforma. A ingestão fiscal é executada por município e exercício, permitindo expansão progressiva.

## Fontes de dados

| Fonte | Domínio | Dados |
|---|---|---|
| CONDEPE/FIDEM | Saúde | Indicador de mortalidade infantil |
| SICONFI / Tesouro Nacional | Fiscal | Declaração de Contas Anuais (DCA), Anexo I-E |

Outras fontes, como IBGE, TCE-PE, SIOPS e CNES/DATASUS, fazem parte do planejamento de expansão.

## Arquitetura

```text
                 FONTES PÚBLICAS
                 /             \
          CONDEPE/FIDEM       SICONFI
                |                |
                v                v
          PYTHON INGESTION PIPELINES
                |                |
                v                v
             LANDING          LANDING
             PARQUET          PARQUET
                |                |
                v                v
          DATA VALIDATION & INTEGRITY
                |                |
                v                v
             CURATED          CURATED
             PARQUET          PARQUET
                |                |
                v                v
             RAW VAULT - POSTGRESQL
                |                |
                v                v
             BUSINESS VAULT / DATA MARTS
                         |
                         v
                    FASTAPI
                         |
                         v
                  ANALYTICAL QUERIES
```

## Pipelines implementados

### 1. Ingestão de dados de saúde

Conector Python para coleta do indicador de mortalidade infantil por meio da API do Observatório de Pernambuco.

Recursos implementados:

- Requisições HTTP com timeout.
- Retentativas automáticas para falhas de conexão e respostas HTTP específicas.
- Verificação da fonte e do ano retornados.
- Rejeição de respostas truncadas ou sem observações.
- Conversão e validação de tipos.
- Registro da origem e horário de coleta em UTC.
- Persistência em Parquet com compressão Zstandard.
- Cálculo de hash SHA-256.

### 2. Ingestão fiscal — SICONFI

Conector para coleta da Declaração de Contas Anuais (DCA), Anexo I-E, disponibilizada pelo Tesouro Nacional.

Recursos implementados:

- Paginação por `limit` e `offset`.
- Controle de intervalo entre requisições.
- Retentativas automáticas.
- Tratamento de respostas JSON.
- Conversão monetária com `Decimal`.
- Validação de valores contábeis.
- Persistência dos dados em Parquet.
- Registro de metadados e integridade dos arquivos.

### 3. Curadoria de dados de saúde

O pipeline de mortalidade infantil realiza:

- Padronização de códigos IBGE e nomes das localidades.
- Validação dos anos e valores.
- Identificação de registros duplicados.
- Verificação da cobertura de 184 municípios e Fernando de Noronha.
- Classificação territorial entre município e distrito estadual.
- Padronização da periodicidade anual.
- Geração de chave de negócio determinística.

### 4. Curadoria fiscal

O pipeline fiscal realiza:

- Seleção da coleta versionada mais recente.
- Validação dos manifestos de ingestão.
- Verificação de integridade por SHA-256.
- Extração e validação da classificação funcional.
- Identificação das despesas relacionadas à saúde.
- Validação dos estágios de execução orçamentária.
- Reconciliação entre o total da função Saúde e suas subfunções.

### 5. Data Vault e auditoria

Foram implementados carregadores independentes para os domínios de saúde e fiscal.

Recursos identificados:

- Geração de hash keys.
- Geração determinística de hashdiff.
- Identificação de lotes de processamento.
- Verificação de duplicidades.
- Carga no PostgreSQL.
- Registro de sucesso e falha das execuções.
- Controle transacional da carga e auditoria.

### 6. API analítica

API REST desenvolvida com FastAPI para consulta dos dados armazenados no PostgreSQL.

| Endpoint | Descrição |
|---|---|
| `GET /` | Informações da plataforma |
| `GET /health` | Verificação da conexão com o banco |
| `GET /saude/mortalidade-infantil` | Consulta de mortalidade infantil |
| `GET /fiscal/despesas` | Resumo de despesas fiscais |
| `GET /fiscal/execucao-orcamentaria` | Consulta da execução orçamentária |
| `GET /fiscal/detalhamento` | Detalhamento das despesas |

Os endpoints de consulta permitem filtros por ano e código IBGE.

## Tecnologias

| Tecnologia | Aplicação |
|---|---|
| Python | Ingestão, processamento e automação |
| Pandas | Manipulação e transformação de dados |
| Requests | Integração com APIs |
| Pandera | Validação de contratos de dados |
| PyArrow / Parquet | Armazenamento colunar |
| PostgreSQL | Persistência analítica |
| Psycopg | Conexão Python com PostgreSQL |
| FastAPI | Disponibilização de dados por API REST |
| Docker Compose | Ambiente do banco de dados |
| Pytest | Testes automatizados |
| Git / GitHub | Versionamento e publicação |

## Estrutura do projeto

```text
PE-Inteligencia/
│
├── api/
│   ├── database.py
│   └── main.py
│
├── banco_dados/
│   └── sql/
│
├── fontes/
│   ├── condepe/
│   │   └── conector.py
│   └── siconfi/
│       └── conector.py
│
├── lakehouse/
│   ├── landing/
│   ├── curado/
│   └── quarentena/
│
├── motor_dados/
│   ├── data_vault/
│   ├── processamento/
│   └── validacao/
│
├── scripts/
├── testes/
├── .env.example
├── .gitignore
├── compose.yaml
├── requirements.txt
└── README.md
```

## Como executar

### 1. Clonar o repositório

```bash
git clone https://github.com/flavioalves1919-cell/PE-Inteligncia-0-0.git

cd PE-Inteligncia-0-0
```

### 2. Criar ambiente virtual

```bash
python -m venv .venv

source .venv/bin/activate
```

### 3. Instalar dependências

```bash
pip install -r requirements.txt
```

### 4. Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Preencha as variáveis de conexão com PostgreSQL no arquivo `.env`, conforme o modelo fornecido.

Não publique o arquivo `.env` nem credenciais no GitHub.

### 5. Iniciar o PostgreSQL

```bash
docker compose up -d postgres
```

Verificar o serviço:

```bash
docker compose ps
```

### 6. Executar os pipelines

**Ingestão de saúde:**

```bash
python -m fontes.condepe.conector --anos 2022 2023 2024
```

**Curadoria de saúde:**

```bash
python -m motor_dados.processamento.curar_mortalidade --anos 2022 2023 2024
```

**Ingestão fiscal — exemplo para Recife, exercício 2024:**

```bash
python -m fontes.siconfi.conector --ano 2024 --municipio 2611606
```

**Curadoria fiscal:**

```bash
python -m motor_dados.processamento.curar_despesas_fiscais --ano 2024 --municipio 2611606
```

**Carga Raw Vault de saúde:**

```bash
python -m motor_dados.data_vault.carregar_raw_vault
```

**Carga Raw Vault fiscal:**

```bash
python -m motor_dados.data_vault.carregar_raw_vault_fiscal
```

As cargas dependem da existência dos arquivos curados e da estrutura SQL necessária no PostgreSQL.

### 7. Executar os testes

```bash
python -m pytest -q
```

## Testes e validação

Última execução registrada no ambiente de desenvolvimento:

| Métrica | Resultado |
|---|---:|
| Testes aprovados | 65 |
| Falhas | 0 |
| Erros | 0 |
| Avisos | 1 |
| Tempo | 6,16 segundos |

O aviso identificado está relacionado à depreciação da integração entre `httpx` e `starlette.testclient`. Não impediu a aprovação dos testes.

## Princípios de engenharia

- Utilização de fontes públicas.
- Rastreabilidade da origem dos dados.
- Registro de períodos de referência e horários de coleta.
- Integridade de arquivos por SHA-256.
- Validação antes da persistência.
- Controle de duplicidades.
- Precisão monetária com Decimal.
- Auditoria de execução dos pipelines.
- Separação entre ingestão, curadoria e armazenamento analítico.
- Controle do volume de dados persistidos.
- Não inferir causalidade sem evidência adequada.

## Roadmap

- [x] Conector de dados de saúde.
- [x] Conector fiscal SICONFI.
- [x] Persistência em Parquet.
- [x] Curadoria de saúde.
- [x] Curadoria fiscal.
- [x] Validação de dados.
- [x] Estruturas Raw Vault para saúde e fiscal.
- [x] Auditoria de cargas.
- [x] Estruturas SQL de Business Vault e Data Marts.
- [x] API analítica com FastAPI.
- [x] Suíte de testes automatizados.
- [ ] Expandir a ingestão fiscal para os demais municípios.
- [ ] Ampliar as fontes de dados.
- [ ] Evoluir a orquestração dos pipelines.
- [ ] Expandir os Data Marts e análises integradas.

---

**Projeto desenvolvido para demonstrar práticas de Engenharia de Dados aplicadas à inteligência fiscal e à saúde pública.**
