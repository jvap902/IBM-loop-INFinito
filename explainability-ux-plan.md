# Explainability UX — Plano de Melhoria da Aba Rastreabilidade

## Visão Geral

A aba de Rastreabilidade exibe dados de explicabilidade dos modelos de ML (SHAP values, Z-scores) diretamente para gestores e analistas de negócios. Atualmente dois problemas afetam a legibilidade:

1. **Jargão técnico exposto:** Termos como `SHAP`, `TreeExplainer`, `HDBSCAN`, `KernelExplainer` e os badges de algoritmos não comunicam nada para quem não é ML engineer.
2. **Nomes de variáveis ilegíveis:** Os nomes brutos das features do modelo (`lat`, `d_down`, `vol_reclam`, `n_erb`, `HHI`) aparecem diretamente nos gráficos e nas mensagens de erro, sem tradução para linguagem de negócio.

**Escopo:** Apenas a aba de Rastreabilidade (`RastreabilidadePage.tsx` e `ShapBarChart.tsx`). Outros componentes como `InvestmentTable.tsx` e `HexMap.tsx` ficam fora deste plano.

**Abordagem:** Substituição de linguagem técnica por linguagem de negócio. Sem layer de toggle ou accordion para versão técnica — a simplificação é total.

---

## Sub-Tarefa 1 — Criar mapeamento centralizado de nomes de features

**Intent:** Criar um arquivo de constantes que seja a fonte única de verdade para tradução de nomes de variáveis do modelo para linguagem legível, com unidade incluída. Qualquer componente que precise exibir um nome de feature usa este arquivo.

**Expected Outcomes:**
- Arquivo `frontend/src/constants/featureLabels.ts` existe com mapeamento de todas as 10 features do modelo (`X_HI_COLUMNS`) mais as métricas agregadas usadas no Eixo 2.
- Exporta uma função `getFeatureLabel(feature: string): string` que retorna `"Nome (unidade)"` ou o nome bruto como fallback.
- Nenhuma alteração visual ainda — apenas o arquivo de constantes.

**Todo List:**
1. Criar `frontend/src/constants/featureLabels.ts`
2. Definir o mapeamento `FEATURE_LABELS` com as 10 features de `X_HI_COLUMNS` e as métricas agregadas (`avg_d_down`, `avg_n_dom`, `avg_HHI`)
3. Exportar a função helper `getFeatureLabel(feature: string): string` que retorna o label formatado com unidade entre parênteses

**Mapeamento a implementar:**

| Chave | Label exibido |
|---|---|
| `d_down` | Velocidade de Download (Mbps) |
| `d_up` | Velocidade de Upload (Mbps) |
| `lat` | Latência (ms) |
| `vol_test` | Volume de Testes (testes/dispositivo) |
| `n_dom` | Domicílios |
| `n_com` | Estabelecimentos Comerciais |
| `ren_med` | Renda Média (R$) |
| `n_erb` | Torres de Celular |
| `HHI` | Concentração de Mercado (HHI) |
| `vol_reclam` | Reclamações (por 1k acessos) |
| `avg_d_down` | Vel. Download Média (Mbps) |
| `avg_n_dom` | Domicílios por Hexágono |
| `avg_HHI` | Concentração de Mercado Média (HHI) |

**Relevant Context:**
- Feature list source: `data_ingestion/processing/feature_store.py` lines 33-44
- Aggregated metric names: `frontend/src/pages/RastreabilidadePage.tsx` lines 194-207 (Eixo 2 cluster keys)
- No i18n library exists in the project — arquivo de constantes TypeScript simples é o padrão correto

**Status:** [x] done

---

## Sub-Tarefa 2 — Aplicar tradução de features no ShapBarChart

**Intent:** Fazer o `ShapBarChart` usar o mapeamento criado na Sub-Tarefa 1 para exibir nomes legíveis no eixo Y do gráfico, sem alterar a estrutura do componente ou a lógica de dados.

**Expected Outcomes:**
- O eixo Y do `ShapBarChart` exibe `"Latência (ms)"` em vez de `"lat"`, `"Velocidade de Download (Mbps)"` em vez de `"d_down"`, etc.
- O tooltip do gráfico também exibe o nome traduzido.
- A prop `features` continua recebendo os nomes brutos — a tradução acontece dentro do componente, no `map` que prepara o `data` para o Recharts.
- A mensagem `"Dados SHAP não disponíveis"` é substituída por `"Dados de importância de variáveis não disponíveis"`.

**Todo List:**
1. Importar `getFeatureLabel` de `../constants/featureLabels`
2. No `data` do `BarChart`, substituir `feature: f.feature` por `feature: getFeatureLabel(f.feature)`
3. Atualizar o texto fallback da linha 17 de `"Dados SHAP não disponíveis"` para `"Dados de importância de variáveis não disponíveis"`

**Relevant Context:**
- Arquivo alvo: `frontend/src/components/ShapBarChart.tsx` linhas 20 e 17
- O `dataKey="feature"` no `YAxis` (linha 36) usa o campo `feature` do array `data` — ao traduzir neste `map`, a tradução aparece automaticamente no eixo e no tooltip
- Não alterar a interface `ShapBarChartProps` — a prop continua recebendo o nome bruto do backend

**Status:** [x] done

---

## Sub-Tarefa 3 — Substituir jargão técnico por linguagem de negócio na RastreabilidadePage

**Intent:** Remover ou substituir todos os termos técnicos de ML visíveis na aba de Rastreabilidade por linguagem orientada ao negócio, mantendo a estrutura visual existente.

**Expected Outcomes:**

Após esta sub-tarefa, a aba de Rastreabilidade não exibirá nenhum dos seguintes termos técnicos: `SHAP`, `TreeExplainer`, `KernelExplainer`, `cluster_zscore_proxy`, `IsolationForest`, `LOF`, `HDBSCAN`, `K-Means`.

**Mapeamento de substituições:**

| Elemento | Antes | Depois |
|---|---|---|
| Badge Eixo 1 | `"IsolationForest / LOF"` | `"Detecção Automática"` |
| Badge Eixo 2 | `"HDBSCAN / Z-Score"` | `"Agrupamento Geográfico"` |
| Badge Eixo 3 | `"K-Means / SHAP"` | `"Perfil de Mercado"` |
| Linha de metadados Eixo 1 | `Método: TreeExplainer · Amostras explicadas: 95` | Remover bloco inteiro |
| Linha de metadados Eixo 2 | `Método: cluster_zscore_proxy · Clusters explicados: 3` | Remover bloco inteiro |
| Linha de metadados Eixo 3 | `Método: KernelExplainer · Amostras explicadas: N` | Remover bloco inteiro |
| Mensagem indisponível Eixo 1 | `"Dados SHAP do Eixo 1 não disponíveis nesta execução."` | `"Dados de análise de anomalias não disponíveis nesta execução."` |
| Mensagem indisponível Eixo 2 | `"Dados Z-Score do Eixo 2 não disponíveis nesta execução."` | `"Dados de agrupamento não disponíveis nesta execução."` |
| Mensagem indisponível Eixo 3 | `"Dados SHAP do Eixo 3 não disponíveis nesta execução."` | `"Dados de perfil de mercado não disponíveis nesta execução."` |
| Metadados Eixo 3 por segmento | `(n = {segData.n_samples_explained})` | Remover span |

**Todo List:**
1. Substituir o `badge` e `badgeColor` dos três `SectionCard` pelos valores de negócio
2. Remover o bloco `<div className="flex flex-wrap gap-4 ...">` de metadados do Eixo 1 (linhas 153-156)
3. Remover o bloco `<div className="text-[11px] text-ind-muted mb-2">` de metadados do Eixo 2 (linhas 187-190)
4. Remover o bloco `<div className="text-[11px] text-ind-muted mb-3">` de metadados do Eixo 3 (linhas 229-232)
5. Remover o `<span className="ml-2">(n = {segData.n_samples_explained})</span>` do Eixo 3 (linha 240)
6. Substituir as três mensagens de `UnavailableNote` com texto de negócio correspondente

**Relevant Context:**
- Arquivo alvo: `frontend/src/pages/RastreabilidadePage.tsx`
- Eixo 1 badge: linha 147-148
- Eixo 2 badge: linha 181-182
- Eixo 3 badge: linha 224-225
- Bloco metadados Eixo 1: linhas 153-156
- Bloco metadados Eixo 2: linhas 187-190
- Bloco metadados Eixo 3: linhas 229-232
- Span `n_samples_explained`: linha 240
- Mensagens `UnavailableNote` com texto SHAP: linhas 172-174, 213-215, 261-263

**Status:** [x] done
