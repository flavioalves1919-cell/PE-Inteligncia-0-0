-- ============================================
-- DATA MART: SAUDE DE PERNAMBUCO
-- Modelo dimensional - Star Schema
-- ============================================

-- 1. DIMENSAO LOCALIDADE
CREATE TABLE IF NOT EXISTS data_marts.dim_localidade (
    codigo_ibge VARCHAR(7) PRIMARY KEY,
    nome_localidade VARCHAR(150) NOT NULL,
    tipo_localidade VARCHAR(30) NOT NULL,
    CONSTRAINT chk_dm_codigo_ibge
        CHECK (codigo_ibge ~ '^26[0-9]{5}$')
);

-- 2. DIMENSAO TEMPO
CREATE TABLE IF NOT EXISTS data_marts.dim_tempo (
    ano SMALLINT PRIMARY KEY,
    CONSTRAINT chk_dm_ano
        CHECK (ano BETWEEN 1900 AND 2100)
);

-- 3. DIMENSAO INDICADOR
CREATE TABLE IF NOT EXISTS data_marts.dim_indicador (
    indicador_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome_indicador VARCHAR(250) NOT NULL UNIQUE,
    unidade VARCHAR(100) NOT NULL,
    periodicidade VARCHAR(30) NOT NULL,
    fonte_original VARCHAR(200) NOT NULL
);

-- 4. TABELA FATO
CREATE TABLE IF NOT EXISTS data_marts.fact_mortalidade_infantil (
    fato_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo_ibge VARCHAR(7) NOT NULL,
    ano SMALLINT NOT NULL,
    indicador_id BIGINT NOT NULL,
    valor NUMERIC(12,4) NOT NULL,
    natureza VARCHAR(30) NOT NULL,
    data_coleta_utc TIMESTAMPTZ,
    data_carga_raw_vault TIMESTAMPTZ NOT NULL,
    arquivo_origem TEXT,
    url_origem TEXT,

    CONSTRAINT fk_fato_localidade
        FOREIGN KEY (codigo_ibge)
        REFERENCES data_marts.dim_localidade(codigo_ibge),

    CONSTRAINT fk_fato_tempo
        FOREIGN KEY (ano)
        REFERENCES data_marts.dim_tempo(ano),

    CONSTRAINT fk_fato_indicador
        FOREIGN KEY (indicador_id)
        REFERENCES data_marts.dim_indicador(indicador_id),

    CONSTRAINT chk_fato_valor
        CHECK (valor >= 0),

    CONSTRAINT uq_fato_mortalidade
        UNIQUE (codigo_ibge, ano, indicador_id)
);

-- 5. INDICES
CREATE INDEX IF NOT EXISTS idx_fato_ano
    ON data_marts.fact_mortalidade_infantil(ano);

CREATE INDEX IF NOT EXISTS idx_fato_indicador
    ON data_marts.fact_mortalidade_infantil(indicador_id);

-- ============================================
-- CARGA DAS DIMENSOES
-- ============================================

INSERT INTO data_marts.dim_localidade (
    codigo_ibge,
    nome_localidade,
    tipo_localidade
)
SELECT DISTINCT
    codigo_ibge,
    nome_localidade,
    tipo_localidade
FROM business_vault.vw_mortalidade_infantil
ON CONFLICT (codigo_ibge)
DO UPDATE SET
    nome_localidade = EXCLUDED.nome_localidade,
    tipo_localidade = EXCLUDED.tipo_localidade;

INSERT INTO data_marts.dim_tempo (ano)
SELECT DISTINCT ano
FROM business_vault.vw_mortalidade_infantil
ON CONFLICT (ano) DO NOTHING;

INSERT INTO data_marts.dim_indicador (
    nome_indicador,
    unidade,
    periodicidade,
    fonte_original
)
SELECT DISTINCT
    nome_indicador,
    unidade,
    periodicidade,
    fonte_original
FROM business_vault.vw_mortalidade_infantil
ON CONFLICT (nome_indicador)
DO UPDATE SET
    unidade = EXCLUDED.unidade,
    periodicidade = EXCLUDED.periodicidade,
    fonte_original = EXCLUDED.fonte_original;

-- ============================================
-- CARGA DA TABELA FATO
-- ============================================

INSERT INTO data_marts.fact_mortalidade_infantil (
    codigo_ibge,
    ano,
    indicador_id,
    valor,
    natureza,
    data_coleta_utc,
    data_carga_raw_vault,
    arquivo_origem,
    url_origem
)
SELECT
    bv.codigo_ibge,
    bv.ano,
    di.indicador_id,
    bv.valor,
    bv.natureza,
    bv.data_coleta_utc,
    bv.data_carga_raw_vault,
    bv.arquivo_origem,
    bv.url_origem
FROM business_vault.vw_mortalidade_infantil bv
JOIN data_marts.dim_indicador di
    ON di.nome_indicador = bv.nome_indicador

ON CONFLICT (codigo_ibge, ano, indicador_id)
DO UPDATE SET
    valor = EXCLUDED.valor,
    natureza = EXCLUDED.natureza,
    data_coleta_utc = EXCLUDED.data_coleta_utc,
    data_carga_raw_vault = EXCLUDED.data_carga_raw_vault,
    arquivo_origem = EXCLUDED.arquivo_origem,
    url_origem = EXCLUDED.url_origem;
