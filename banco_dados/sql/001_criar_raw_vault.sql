-- =====================================================
-- PE INTELIGÊNCIA
-- RAW VAULT 2.0
-- PostgreSQL 18
-- =====================================================

CREATE SCHEMA IF NOT EXISTS raw_vault;
CREATE SCHEMA IF NOT EXISTS business_vault;
CREATE SCHEMA IF NOT EXISTS data_marts;


-- =====================================================
-- 1. HUB LOCALIDADE
-- Entidades territoriais identificadas pelo código IBGE
-- =====================================================

CREATE TABLE IF NOT EXISTS raw_vault.hub_localidade (
    localidade_hk CHAR(64) PRIMARY KEY,
    codigo_ibge VARCHAR(7) NOT NULL UNIQUE,
    load_dts TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    record_source VARCHAR(150) NOT NULL,

    CONSTRAINT ck_codigo_ibge_pe
        CHECK (codigo_ibge ~ '^26[0-9]{5}$')
);


-- =====================================================
-- 2. HUB INDICADOR
-- Identifica cada indicador de uma fonte
-- =====================================================

CREATE TABLE IF NOT EXISTS raw_vault.hub_indicador (
    indicador_hk CHAR(64) PRIMARY KEY,
    chave_negocio VARCHAR(500) NOT NULL UNIQUE,
    load_dts TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    record_source VARCHAR(150) NOT NULL
);


-- =====================================================
-- 3. HUB PERIODO
-- Identifica o período de referência
-- =====================================================

CREATE TABLE IF NOT EXISTS raw_vault.hub_periodo (
    periodo_hk CHAR(64) PRIMARY KEY,
    ano SMALLINT NOT NULL UNIQUE,
    load_dts TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    record_source VARCHAR(150) NOT NULL,

    CONSTRAINT ck_ano_periodo
        CHECK (ano BETWEEN 1900 AND 2100)
);


-- =====================================================
-- 4. LINK OBSERVACAO
-- Relaciona localidade, indicador e período
-- =====================================================

CREATE TABLE IF NOT EXISTS raw_vault.link_observacao (
    observacao_hk CHAR(64) PRIMARY KEY,

    localidade_hk CHAR(64) NOT NULL,
    indicador_hk CHAR(64) NOT NULL,
    periodo_hk CHAR(64) NOT NULL,

    load_dts TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    record_source VARCHAR(150) NOT NULL,

    CONSTRAINT fk_link_localidade
        FOREIGN KEY (localidade_hk)
        REFERENCES raw_vault.hub_localidade(localidade_hk),

    CONSTRAINT fk_link_indicador
        FOREIGN KEY (indicador_hk)
        REFERENCES raw_vault.hub_indicador(indicador_hk),

    CONSTRAINT fk_link_periodo
        FOREIGN KEY (periodo_hk)
        REFERENCES raw_vault.hub_periodo(periodo_hk),

    CONSTRAINT uq_link_observacao
        UNIQUE (localidade_hk, indicador_hk, periodo_hk)
);


-- =====================================================
-- 5. SATELLITE LOCALIDADE
-- Histórico dos atributos territoriais
-- =====================================================

CREATE TABLE IF NOT EXISTS raw_vault.sat_localidade (
    localidade_hk CHAR(64) NOT NULL,
    batch_id CHAR(64) NOT NULL,

    hashdiff CHAR(64) NOT NULL,
    nome_localidade VARCHAR(200) NOT NULL,
    tipo_localidade VARCHAR(30) NOT NULL,

    load_dts TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    record_source VARCHAR(150) NOT NULL,

    PRIMARY KEY (localidade_hk, batch_id),

    FOREIGN KEY (localidade_hk)
        REFERENCES raw_vault.hub_localidade(localidade_hk),

    CONSTRAINT ck_tipo_localidade
        CHECK (
            tipo_localidade IN (
                'MUNICIPIO',
                'DISTRITO_ESTADUAL'
            )
        )
);


-- =====================================================
-- 6. SATELLITE INDICADOR
-- Descrição e características do indicador
-- =====================================================

CREATE TABLE IF NOT EXISTS raw_vault.sat_indicador (
    indicador_hk CHAR(64) NOT NULL,
    batch_id CHAR(64) NOT NULL,

    hashdiff CHAR(64) NOT NULL,
    nome_indicador VARCHAR(500) NOT NULL,
    unidade VARCHAR(100),
    periodicidade VARCHAR(30) NOT NULL,
    fonte_original VARCHAR(200),

    load_dts TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    record_source VARCHAR(150) NOT NULL,

    PRIMARY KEY (indicador_hk, batch_id),

    FOREIGN KEY (indicador_hk)
        REFERENCES raw_vault.hub_indicador(indicador_hk)
);


-- =====================================================
-- 7. SATELLITE OBSERVACAO
-- Valor medido e rastreabilidade da fonte
-- =====================================================

CREATE TABLE IF NOT EXISTS raw_vault.sat_observacao (
    observacao_hk CHAR(64) NOT NULL,
    batch_id CHAR(64) NOT NULL,

    hashdiff CHAR(64) NOT NULL,
    valor DOUBLE PRECISION NOT NULL,

    unidade VARCHAR(100),
    natureza VARCHAR(100),
    fonte_original VARCHAR(200),
    arquivo_origem TEXT,

    data_coleta_utc TIMESTAMPTZ,
    url_origem TEXT,

    load_dts TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    record_source VARCHAR(150) NOT NULL,

    PRIMARY KEY (observacao_hk, batch_id),

    FOREIGN KEY (observacao_hk)
        REFERENCES raw_vault.link_observacao(observacao_hk),

    CONSTRAINT ck_valor_observacao
        CHECK (valor >= 0)
);


-- =====================================================
-- ÍNDICES PARA CONSULTAS E RELACIONAMENTOS
-- =====================================================

CREATE INDEX IF NOT EXISTS idx_link_localidade
    ON raw_vault.link_observacao(localidade_hk);

CREATE INDEX IF NOT EXISTS idx_link_indicador
    ON raw_vault.link_observacao(indicador_hk);

CREATE INDEX IF NOT EXISTS idx_link_periodo
    ON raw_vault.link_observacao(periodo_hk);

CREATE INDEX IF NOT EXISTS idx_sat_observacao_load_dts
    ON raw_vault.sat_observacao(load_dts);

CREATE INDEX IF NOT EXISTS idx_sat_observacao_hashdiff
    ON raw_vault.sat_observacao(hashdiff);
