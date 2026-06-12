from pathlib import Path
import numpy as np
import pandas as pd
import basedosdados as bd
import matplotlib.pyplot as plt
import statsmodels.formula.api as smf

raw_data = Path("raw_data")

df_raw: pd.DataFrame = pd.read_excel(
    raw_data
    / "sinopses_estatisticas_pesquisa_covid19_censo_escolar_2020"
    / "Sinopse_Estatistica_do_Questionario_Resposta_Educacional_a_Pandemia_de_Covid_19_no Brasil_EducaЗ╞o_Brasica.xlsx",
    sheet_name="1.1 a 1.3",
    skiprows=8,
)

df_raw["CO_MUNICIPIO"] = df_raw["CO_MUNICIPIO"].astype("Int64")

df_raw["TP_LOCALIZACAO"].unique()
df_raw["TP_DEPENDENCIA"].unique()

df = df_raw.loc[
    (df_raw["CO_MUNICIPIO"].notna())
    & (df_raw["TP_LOCALIZACAO"] == "Total")
    & (~df_raw["TP_DEPENDENCIA"].isin(["Total", "Pública"]))
]

# Durante o período de suspensão das atividades presenciais de ensino-aprendizagem, a escola adotou estratégias não presenciais de ensino?
# Não em percentual
counts, bin_edges = np.histogram(df["PERC_QUEST_3_N"].dropna(), bins=10)  # type: ignore
for i in range(len(counts)):
    print(f"({bin_edges[i]}, {bin_edges[i + 1]}]: {counts[i]}")

df["TP_DEPENDENCIA"].unique()

# 90% ou + das escolas não adotaram medida não presencial
# Esse df tem municípios onde 90% ou + das escolas não aplicaram estrategia
# Esses municípios é grupo de controle para encontrar os pares que serão
# o grupo de tratamento
df_municipios_sem_estrategia = df.loc[df["PERC_QUEST_3_N"] >= 90.0]

# Parear os 53 municípios "tratados" (sem estratégias) com municípios "controle"
# (com estratégias) similares em características observáveis pré-pandemia.

# [x] IDEB/SAEB pré-pandemia (2019)
#   - Taxa de aprovação é parte da formula do Ideb
# [x] Nível socioeconômico (INSE)
# [x] Infraestrutura escolar
#   - Internet
# [x] Proporção de alunos na educação infantil
#   - Número de alunos / população
# [x] PIB per capita municipal
# [x] Gasto por aluno
#   - Valor das despesas em educação per capita
# [x] Formação de professores
#   - Percentual de docentes com curso superior
# [ ] Taxa de urbanização?


df_variaveis = bd.read_sql(
    """with
    ideb as (
        select
            ano,
            id_municipio,
            rede,
            -- if(
            --     anos_escolares = "iniciais (1-5)", "anos iniciais", "anos finais"
            -- ) as anos_escolares,
            round(avg(taxa_aprovacao) * avg(ideb), 2) as ideb_media,
            -- nota_saeb_lingua_portuguesa,
            -- nota_saeb_matematica,
            -- nota_saeb_media_padronizada
        from `basedosdados.br_inep_ideb.municipio`
        where
            ano = 2019
            and rede in ("municipal", "estadual", "federal") -- Não tem rede privada
            and anos_escolares in ("iniciais (1-5)", "finais (6-9)")
            group by ano, id_municipio, rede
    ),
    saeb as (
      select
          ano,
          id_municipio,
          rede,
          LP as media_saeb_lp,
          MT as media_saeb_mt
      from (
          select
              ano,
              id_municipio,
              rede,
              round(avg(media), 2) as media, -- Média para o 5 e 9 ano
              disciplina
          from basedosdados.br_inep_saeb.municipio
          where ano = 2019
          and localizacao = "total" and serie in (5, 9) and rede in ("federal", "estadual", "municipal", "privada")
          group by ano, id_municipio, rede, disciplina
      )
      pivot (
          avg(media) for disciplina in ("LP", "MT")
      )
    ),
    censo_escolar as (
        select
            ano,
            id_municipio,
            case
              when rede = "1" then "federal"
              when rede = "2" then "estadual"
              when rede = "3" then "municipal"
              when rede = "4" then "privada"
              else error(rede)
            end as rede,
            -- case
            --     when etapa_ensino in ("1", "2", "3")
            --     then "infantil"
            --     when etapa_ensino in ("14", "15", "16", "17", "18")
            --     then "anos iniciais"
            --     else "anos finais"
            -- end as etapa_ensino,
            raca_cor
        from `basedosdados.br_inep_censo_escolar.matricula`
        where
            ano = 2019
            and etapa_ensino in (
                -- "1",
                -- "2",
                -- "3",
                -- EF de 9 anos (anos iniciais 14 ate 18), (anos fianis > 18)
                "14",
                "15",
                "16",
                "17",
                "18",
                "19",
                "20",
                "21",
                "41"
            )
            and rede in ("1", "2", "3", "4")
    ),
    -- proporcao_brancos as (
    --     select
    --         ano,
    --         id_municipio,
    --         etapa_ensino,
    --         sum(if(raca_cor = '1', 1, 0)) / count(*) as proporcao_brancos
    --     from censo_escolar
    --     where rede in ("2", "3") and etapa_ensino in ("anos iniciais", "anos finais")
    --     group by ano, id_municipio, etapa_ensino
    -- ),
    -- proporcao_municipal as (
    --     select
    --         ano,
    --         id_municipio,
    --         etapa_ensino,
    --         sum(if(rede = '3', 1, 0)) / count(*) as proporcao_municipal
    --     from censo_escolar
    --     where rede in ("2", "3") and etapa_ensino in ("anos iniciais", "anos finais")
    --     group by ano, id_municipio, etapa_ensino
    -- ),
    populacao_faixa as (
        select ano, id_municipio, sum(populacao) as populacao
        from `basedosdados.br_ms_populacao.municipio`
        where ano = 2019 and grupo_idade in ("0-4 anos", "5-9 anos", "10-14 anos")
        group by ano, id_municipio
    ),
    proporcao_ed_infantil as (
        select
            a.ano,
            a.id_municipio,
            a.numero_alunos,
            a.numero_alunos / b.populacao as proporcao_ed_infantil
        from
            (
                select ano, id_municipio, count(*) as numero_alunos
                from censo_escolar
                -- where rede in ("2", "3") and etapa_ensino = "infantil"
                group by ano, id_municipio
            ) as a
        join populacao_faixa as b on a.ano = b.ano and a.id_municipio = b.id_municipio
    ),
    ibge_populacao as (
        select ano, id_municipio, populacao
        from `basedosdados.br_ibge_populacao.municipio`
        where ano = 2019
    ),
    pib as (
        select ano, id_municipio, pib from `basedosdados.br_ibge_pib.municipio` where ano = 2019
    ),
    pib_pc as (
        select a.ano, a.id_municipio, a.pib / b.populacao as pib_pc
        from pib as a
        join ibge_populacao as b on a.ano = b.ano and a.id_municipio = b.id_municipio
    ),
    valor_despesas_educacao_pc as (
        select
            a.ano, a.id_municipio, a.valor / b.populacao as valor_despesas_educacao_pc
        from
            (
                select ano, id_municipio, valor
                from `basedosdados.br_me_siconfi.municipio_despesas_funcao`
                where
                    ano = 2019
                    and estagio_bd = 'Despesas Empenhadas'
                    and id_conta_bd = '3.12.000'
            ) as a
        join ibge_populacao as b on a.ano = b.ano and a.id_municipio = b.id_municipio
    ),
    prop_internet as (
        select
            ano,
            id_municipio,
            case
              when rede = "1" then "federal"
              when rede = "2" then "estadual"
              when rede = "3" then "municipal"
              when rede = "4" then "privada"
              else error(rede)
            end as rede,
            (sum(internet) / count(distinct id_escola)) * 100 as prop_internet,
        from `basedosdados.br_inep_censo_escolar.escola`
        where ano = 2019 and rede in ("1", "2", "3", "4")
        group by ano, id_municipio, rede
    ),
    perc_docente_superior as (
        select
            ano,
            id_municipio,
            rede,
            atu_ef as aluno_turma,
            dsu_ef as perc_docente_superior
        from `basedosdados.br_inep_indicadores_educacionais.municipio`
        where ano = 2019        
        and rede in ('federal', 'estadual', 'municipal', 'privada') and localizacao = 'total'
    ),
    inse as (
      select
        ano,
        id_municipio,
        case
          when rede = "1" then "federal"
          when rede = "2" then "estadual"
          when rede = "3" then "municipal"
          when rede = "4" then "privada"
          else error(rede)
        end as rede,
        inse
      from basedosdados.br_inep_indicador_nivel_socioeconomico.municipio
      where ano = 2019 
      and rede in ("1", "2", "3", "4")
      and tipo_localizacao = "0" -- Total
    ),
    municipios as (
        select id_municipio, sigla_uf from `basedosdados.br_bd_diretorios_brasil.municipio`
    )

select
    *
from
    (
        select
            ideb.ano,
            ideb.id_municipio,
            ideb.rede,
            ideb.ideb_media,
            proporcao_ed_infantil.proporcao_ed_infantil,
            pib_pc.pib_pc,
            valor_despesas_educacao_pc.valor_despesas_educacao_pc,
            prop_internet.prop_internet,
            perc_docente_superior.perc_docente_superior,
            perc_docente_superior.aluno_turma,
            inse.inse,
            saeb.media_saeb_lp,
            saeb.media_saeb_mt
        -- from municipios as municipios
        from ideb
        -- join ideb as ideb on municipios.id_municipio = ideb.id_municipio
        -- join
        --     proporcao_brancos as proporcao_brancos
        --     on ideb.ano = proporcao_brancos.ano
        --     and municipios.id_municipio = proporcao_brancos.id_municipio
        --     and ideb.anos_escolares = proporcao_brancos.etapa_ensino
        -- join
        --     proporcao_municipal as proporcao_municipal
        --     on ideb.ano = proporcao_municipal.ano
        --     and municipios.id_municipio = proporcao_municipal.id_municipio
        --     and ideb.anos_escolares = proporcao_municipal.etapa_ensino
        join
            proporcao_ed_infantil as proporcao_ed_infantil
            on ideb.ano = proporcao_ed_infantil.ano
            and ideb.id_municipio = proporcao_ed_infantil.id_municipio
        join
            ibge_populacao as ibge_populacao
            on ideb.ano = ibge_populacao.ano
            and ideb.id_municipio = ibge_populacao.id_municipio
        join
            pib_pc as pib_pc
            on ideb.ano = pib_pc.ano
            and ideb.id_municipio = pib_pc.id_municipio
        join
            valor_despesas_educacao_pc as valor_despesas_educacao_pc
            on ideb.ano = valor_despesas_educacao_pc.ano
            and ideb.id_municipio = valor_despesas_educacao_pc.id_municipio
            -- and ideb.rede = valor_despesas_educacao_pc.rede 
        join
            prop_internet as prop_internet
            on ideb.ano = prop_internet.ano
            and ideb.id_municipio = prop_internet.id_municipio
            and ideb.rede = prop_internet.rede
        join
            perc_docente_superior as perc_docente_superior
            on ideb.ano = perc_docente_superior.ano
            and ideb.id_municipio = perc_docente_superior.id_municipio
            and ideb.rede = perc_docente_superior.rede
        join inse
          on ideb.ano = inse.ano
          and ideb.id_municipio = inse.id_municipio
          and ideb.rede = inse.rede
        join saeb
          on ideb.ano = saeb.ano
          and ideb.id_municipio = saeb.id_municipio
          and ideb.rede = saeb.rede
    )
""",
    billing_project_id="basedosdados-dev",
)

df_variaveis.to_parquet(raw_data / "indicadores_bd.parquet", index=False)

df_variaveis = pd.read_parquet(raw_data / "indicadores_bd.parquet")
df_variaveis["id_municipio"] = df_variaveis["id_municipio"].astype("Int64")

df_variaveis["rede"].value_counts(dropna=False)
df_variaveis["rede"].unique()
df_variaveis["rede"] = df_variaveis["rede"].replace(
    {"municipal": 0, "estadual": 1, "federal": 2}
)

# A coluna tratamento marca os municipios/rede que não aplicaram
# estrategia. Embora possa parecer contraditório
df_variaveis["tratamento"] = df_variaveis["id_municipio"].apply(
    lambda v: 1
    if v in df_municipios_sem_estrategia["CO_MUNICIPIO"].values.tolist()
    else 0
)

df_saeb_lp = bd.read_sql(
    """
select
    ano,
    id_municipio,
    round(avg(media), 2) as media, -- Média para o 5 e 9 ano
from basedosdados.br_inep_saeb.municipio
where localizacao = "total"
    and serie in (5, 9) 
    and rede in ("total - estadual e municipal") -- ("federal", "estadual", "municipal", "privada")
    and disciplina = "LP"
group by ano, id_municipio""",
    billing_project_id="basedosdados-dev",
)


df_saeb_lp["id_municipio"] = df_saeb_lp["id_municipio"].astype("Int64")

df_saeb_lp["sem_estrategia"] = df_saeb_lp["id_municipio"].apply(
    lambda v: 1
    if v in df_municipios_sem_estrategia["CO_MUNICIPIO"].values.tolist()
    else 0
)

df_saeb_lp["sem_estrategia"].value_counts(dropna=False)

# Criar variáveis necessárias
df_saeb_lp["pos"] = (df_saeb_lp["ano"] == 2021).astype(int)  # Dummy pós-tratamento
df_saeb_lp["did"] = (
    df_saeb_lp["sem_estrategia"] * df_saeb_lp["pos"]
)  # Termo de interação

# Garantir que município seja categórico
df_saeb_lp["id_municipio"] = df_saeb_lp["id_municipio"].astype("category")


def plot_tendencias(df: pd.DataFrame, salvar: bool = False) -> None:
    """
    Plota evolução do SAEB para tratados vs controles
    """
    # Calcular médias por grupo e ano
    medias = df.groupby(["ano", "sem_estrategia"])["media"].mean().reset_index()

    # Criar gráfico
    fig, ax = plt.subplots(figsize=(10, 6))

    for grupo in [0, 1]:
        dados_grupo = medias[medias["sem_estrategia"] == grupo]
        label = "Sem estratégia" if grupo == 1 else "Com estratégia"
        marker = "o" if grupo == 1 else "s"

        ax.plot(
            dados_grupo["ano"],  # type: ignore
            dados_grupo["media"],  # type: ignore
            marker=marker,
            markersize=10,
            linewidth=2.5,
            label=label,
            alpha=0.8,
        )

    # Linha vertical no tratamento
    ax.axvline(
        x=2020,
        color="red",
        linestyle="--",
        linewidth=1.5,
        alpha=0.6,
        label="Início da Pandemia",
    )

    ax.set_xlabel("Ano", fontsize=12, fontweight="bold")
    ax.set_ylabel("SAEB Médio", fontsize=12, fontweight="bold")
    ax.set_title(
        "Evolução do SAEB: Tendências Paralelas\n(Teste Visual)",
        fontsize=14,
        fontweight="bold",
    )
    ax.legend(fontsize=11, loc="best")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()

    if salvar:
        plt.savefig("tendencias_paralelas.png", dpi=300, bbox_inches="tight")

    plt.show()


# Executar
plot_tendencias(df_saeb_lp, salvar=False)

# DiD Simples
# SAEB_it = β₀ + β₁·Tratamento_i + β₂·Pós_t + β₃·(Tratamento_i × Pós_t) + ε_it
# SAEB_it: Nota média do município i no tempo t
# Tratamento_i: Dummy = 1 se município adotou estratégias, 0 caso contrário
# Pós_t: Dummy = 1 se ano é 2021, 0 se é 2019
# Tratamento_i × Pós_t: Termo de interação (o DiD propriamente dito)
# ε_it: Erro aleatório


def modelo_did_basico(df: pd.DataFrame):
    """
    Estima DiD básico via OLS
    """
    print("\n" + "=" * 80)
    print("MODELO 1: DiD BÁSICO (OLS)")
    print("=" * 80 + "\n")

    # Fórmula
    formula = "media ~ sem_estrategia + pos + did"

    # Estimar modelo
    modelo = smf.ols(formula, data=df).fit(
        cov_type="cluster",
        cov_kwds={"groups": df["id_municipio"]},  # type: ignore
    )

    print(modelo.summary())

    # Interpretar coeficiente DiD
    coef_did = modelo.params["did"]
    pvalor = modelo.pvalues["did"]

    print("\n" + "=" * 80)
    print("INTERPRETAÇÃO DO EFEITO DiD:")
    print("=" * 80)
    print(f"Coeficiente DiD: {coef_did:.4f}")
    print(f"P-valor: {pvalor:.4f}")
    print(
        f"Significância: {'***' if pvalor < 0.01 else '**' if pvalor < 0.05 else '*' if pvalor < 0.1 else 'Não significativo'}"
    )

    if coef_did < 0:
        print(
            f"\n➡️  Municípios SEM estratégias tiveram queda ADICIONAL de {abs(coef_did):.2f} pontos no SAEB"
        )
        print("    em relação aos municípios COM estratégias.")
    else:
        print(
            f"\n➡️  Municípios SEM estratégias tiveram ganho ADICIONAL de {coef_did:.2f} pontos no SAEB"
        )
        print("    em relação aos municípios COM estratégias (resultado inesperado!).")

    return modelo


# Executar
modelo1 = modelo_did_basico(df_saeb_lp)


# Resultados
#
# 1. O grupos tratamento e controle são bem diferentes, provavelmente a condição econômica
# foi um determinante para aplicar estratégia na pandemia.
#   - Municípios sem estratégia JÁ eram muito diferentes antes da pandemia
#   - Tinham SAEB 21.4 pontos menor que municípios com estratégia em 2019
# 2. Em média, houve melhora de 1.57 pontos de 2019 para 2021 (pos = +1.57)
#   - Recuperação pós retorno presencial
# 3. Municípios SEM estratégias tiveram queda ADICIONAL de 3.25 pontos no SAEB em relação aos municípios COM estratégias. (did = -3.25)




from linearmodels.panel import PanelOLS


def modelo_did_efeitos_fixos(df: pd.DataFrame):
    """
    Estima DiD com efeitos fixos de município e tempo
    Usando linearmodels (mais robusto)
    """
    print("\n" + "=" * 80)
    print("MODELO 2: DiD COM EFEITOS FIXOS")
    print("=" * 80 + "\n")

    # Preparar dados para painel
    df_painel = df.set_index(["id_municipio", "ano"])

    # Modelo com efeitos fixos de município e tempo
    modelo_fe = PanelOLS(
        dependent=df_painel["media"],
        exog=df_painel[["did"]],
        entity_effects=True,  # Efeito fixo de município
        time_effects=True,  # Efeito fixo de tempo
    ).fit(cov_type="clustered", cluster_entity=True)

    print(modelo_fe)

    # Interpretação
    coef_did = modelo_fe.params["did"]
    pvalor = modelo_fe.pvalues["did"]

    print("\n" + "=" * 80)
    print("INTERPRETAÇÃO (MODELO PREFERENCIAL):")
    print("=" * 80)
    print(f"Efeito DiD (controlando características fixas): {coef_did:.4f}")
    print(f"P-valor: {pvalor:.4f}")

    return modelo_fe


# Executar
modelo2 = modelo_did_efeitos_fixos(df_saeb_lp)
