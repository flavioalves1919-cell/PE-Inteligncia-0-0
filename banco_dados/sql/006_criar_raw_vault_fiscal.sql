BEGIN;

CREATE SCHEMA IF NOT EXISTS raw_vault;

-- =====================================================
-- 1. HUB CLASSIFICAÇÃO FUNCIONAL
-- Exemplos: 10, 10.301, 10.302, FU10
-- =====================================================

CREATE TABLE IF NOT EXISTS raw_vault.hub_classificacao_funcional (
    classificacao_hk CHAR(64) PRIMARY KEY,
    codigo_classificacao VARCHAR(20) NOT NULL UNIQUE,
    load_dts TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    record_source VARCHAR(150) NOT NULL,

    CONSTRAINT ck_codigo_classificacao
        CHECK (
            codigo_classificacao ~ '^(FU[0-9]{2}|[0-9]{2}(\.[0-9]{3})?)$'
        )
);

-- =====================================================
-- 2. HUB ESTÁGIO DA DESPESA
-- =====================================================

CREATE TABLE IF NOT EXISTS raw_vault.hub_estagio_despesa (
    estagio_hk CHAR(64) PRIMARY KEY,
    codigo_estagio VARCHAR(80) NOT NULL UNIQUE,
    load_dts TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    record_source VARCHAR(150) NOT NULL,

    CONSTRAINT ck_estagio_despesa
        CHECK (
            codigo_estagio IN (
                'Despesas Empenhadas',
                'Despesas Liquidadas',
                'Despesas Pagas',
                'Inscrição de Restos a Pagar Processados',
                'Inscrição de Restos a Pagar Não Processados'
            )
        )
);

-- =====================================================
-- 3. HUB ANEXO
-- =====================================================

CREATE TABLE IF NOT EXISTS raw_vault.hub_anexo (
    anexo_hk CHAR(64) PRIMARY KEY,
    codigo_anexo VARCHAR(100) NOT NULL UNIQUE,
    load_dts TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    record_source VARCHAR(150) NOT NULL
);

-- =====================================================
-- 4. LINK DESPESA FISCAL
-- Município + período + classificação + estágio + anexo
-- =====================================================

CREATE TABLE IF NOT EXISTS raw_vault.link_despesa_fiscal (
    despesa_hk CHAR(64) PRIMARY KEY,

    localidade_hk CHAR(64) NOT NULL,
    periodo_hk CHAR(64) NOT NULL,
    classificacao_hk CHAR(64) NOT NULL,
    estagio_hk CHAR(64) NOT NULL,
    anexo_hk CHAR(64) NOT NULL,

    load_dts TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    record_source VARCHAR(150) NOT NULL,

    CONSTRAINT fk_despesa_localidade
        FOREIGN KEY (localidade_hk)
        REFERENCES raw_vault.hub_localidade(localidade_hk),

    CONSTRAINT fk_despesa_periodo
        FOREIGN KEY (periodo_hk)
        REFERENCES raw_vault.hub_periodo(periodo_hk),

    CONSTRAINT fk_despesa_classificacao
        FOREIGN KEY (classificacao_hk)
        REFERENCES raw_vault.hub_classificacao_funcional(classificacao_hk),

    CONSTRAINT fk_despesa_estagio
        FOREIGN KEY (estagio_hk)
        REFERENCES raw_vault.hub_estagio_despesa(estagio_hk),

    CONSTRAINT fk_despesa_anexo
        FOREIGN KEY (anexo_hk)
        REFERENCES raw_vault.hub_anexo(anexo_hk),

    CONSTRAINT uq_link_despesa_fiscal
        UNIQUE (
            localidade_hk,
            periodo_hk,
            classificacao_hk,
            estagio_hk,
            anexo_hk
        )
);

-- =====================================================
-- 5. SATELLITE DESPESA FISCAL
-- Valores monetários com precisão decimal
-- =====================================================

CREATE TABLE IF NOT EXISTS raw_vault.sat_despesa_fiscal (
    despesa_hk CHAR(64) NOT NULL,
    batch_id CHAR(64) NOT NULL,

    hashdiff CHAR(64) NOT NULL,

    valor NUMERIC(20,2) NOT NULL,

    cod_conta VARCHAR(100),
    conta TEXT NOT NULL,
    rotulo VARCHAR(300) NOT NULL,

    instituicao VARCHAR(300) NOT NULL,
    uf CHAR(2),
    populacao BIGINT,

    data_coleta_utc TIMESTAMPTZ,
    arquivo_origem TEXT,
    url_origem TEXT,

    load_dts TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    record_source VARCHAR(150) NOT NULL,

    PRIMARY KEY (despesa_hk, batch_id),

    CONSTRAINT fk_sat_despesa_fiscal
        FOREIGN KEY (despesa_hk)
        REFERENCES raw_vault.link_despesa_fiscal(despesa_hk),

    CONSTRAINT ck_valor_despesa_fiscal
        CHECK (valor >= 0),

    CONSTRAINT ck_populacao_fiscal
        CHECK (populacao IS NULL OR populacao >= 0)
);

-- =====================================================
-- 6. ÍNDICES
-- =====================================================

CREATE INDEX IF NOT EXISTS idx_link_despesa_localidade
    ON raw_vault.link_despesa_fiscal(localidade_hk);

CREATE INDEX IF NOT EXISTS idx_link_despesa_periodo
    ON raw_vault.link_despesa_fiscal(periodo_hk);

CREATE INDEX IF NOT EXISTS idx_link_despesa_classificacao
    ON raw_vault.link_despesa_fiscal(classificacao_hk);

CREATE INDEX IF NOT EXISTS idx_link_despesa_estagio
    ON raw_vault.link_despesa_fiscal(estagio_hk);

CREATE INDEX IF NOT EXISTS idx_sat_despesa_load_dts
    ON raw_vault.sat_despesa_fiscal(load_dts);

CREATE INDEX IF NOT EXISTS idx_sat_despesa_hashdiff
    ON raw_vault.sat_despesa_fiscal(hashdiff);

COMMIT;
