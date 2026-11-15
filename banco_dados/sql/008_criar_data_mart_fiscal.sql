BEGIN;

-- 1. Resumo da função Saúde por município, ano e estágio.
CREATE OR REPLACE VIEW data_marts.vw_resumo_fiscal_saude AS
SELECT
    ano,
    codigo_ibge,
    codigo_estagio,
    SUM(valor) AS valor_total
FROM business_vault.vw_despesas_fiscais_saude
WHERE codigo_classificacao = '10'
GROUP BY
    ano,
    codigo_ibge,
    codigo_estagio;


-- 2. Detalhamento por classificação funcional.
-- Exclui o total da função para evitar dupla contagem.
CREATE OR REPLACE VIEW data_marts.vw_detalhamento_fiscal_saude AS
SELECT
    ano,
    codigo_ibge,
    codigo_classificacao,
    conta AS descricao_classificacao,
    codigo_estagio,
    valor,
    instituicao,
    populacao
FROM business_vault.vw_despesas_fiscais_saude
WHERE codigo_classificacao <> '10';


-- 3. Comparação da execução orçamentária.
-- Utiliza somente o total da função Saúde.
CREATE OR REPLACE VIEW data_marts.vw_execucao_orcamentaria_saude AS
SELECT
    ano,
    codigo_ibge,
    MAX(instituicao) AS instituicao,

    SUM(valor) FILTER (
        WHERE codigo_estagio = 'Despesas Empenhadas'
    ) AS despesas_empenhadas,

    SUM(valor) FILTER (
        WHERE codigo_estagio = 'Despesas Liquidadas'
    ) AS despesas_liquidadas,

    SUM(valor) FILTER (
        WHERE codigo_estagio = 'Despesas Pagas'
    ) AS despesas_pagas,

    SUM(valor) FILTER (
        WHERE codigo_estagio = 'Inscrição de Restos a Pagar Processados'
    ) AS restos_a_pagar_processados,

    SUM(valor) FILTER (
        WHERE codigo_estagio = 'Despesas Empenhadas'
    )
    -
    SUM(valor) FILTER (
        WHERE codigo_estagio = 'Despesas Pagas'
    ) AS diferenca_empenhado_pago

FROM business_vault.vw_despesas_fiscais_saude
WHERE codigo_classificacao = '10'
GROUP BY ano, codigo_ibge;

COMMIT;
