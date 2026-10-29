# Plano: "Novo Relatório" — Geração de Relatório via Prompt no Dashboard

## Visão Geral

Adicionar um botão **"Novo Relatório"** ao final da página Dashboard. Ao ser clicado, um modal
simples é exibido com um campo de prompt livre. O usuário descreve o foco do relatório (ex.:
"priorize as oportunidades P1 no Sudeste") e confirma. O backend passa o prompt **junto com os
dados atualmente exibidos no dashboard** (o `AgentRunResponse` armazenado no Zustand) para o
agente LLM, que sintetiza um relatório Markdown customizado. Ao terminar, o usuário é
redirecionado para a aba **Relatórios** onde o novo arquivo já aparece selecionado.

**Escopo:** Apenas frontend (modal + chamada de API) e uma nova rota de backend que aceita o
prompt e o contexto do dashboard, invocando o `report_writer` do agente de forma isolada (sem
re-rodar os eixos de ML). O dashboard e o store Zustand existentes não são alterados.

**Não está no escopo:** reprocessar eixos de ML, alterar a análise em si, ou modificar RunPage.

---

## Sub-Task 1 — Novo endpoint de backend `POST /v1/agent/report`

**Status:** [ ] pending

### Intent
Criar um endpoint FastAPI leve que recebe um `user_prompt` e um `dashboard_context` (snapshot do
`AgentRunResponse`), e invoca o nó `report_writer` do agente de forma isolada — sem rodar os
eixos de ML novamente. O relatório Markdown gerado é persistido em `reports/` e retornado ao
cliente.

### Expected Outcomes
- `POST /v1/agent/report` aceita `AgentReportRequest` e retorna `AgentReportResponse`.
- O relatório `.md` é salvo em `reports/{region}_{date}_{run_id_short}.md`.
- O `user_prompt` é injetado no contexto passado ao `report_writer` (via `AgentState`).
- O endpoint requer `X-API-Key`.

### Todo List
1. Em `api/schemas.py`, adicionar dois novos modelos Pydantic:
   - `AgentReportRequest`: campos `user_prompt: str`, `llm_provider: LLMProviderEnum`,
     e `dashboard_context: dict` (o JSON do `AgentRunResponse` serializado).
   - `AgentReportResponse`: campos `filename: str` e `content: str` (Markdown gerado).
2. Em `agent/state.py`, adicionar o campo `user_prompt: Optional[str]` ao `AgentState`.
3. Em `agent/graph.py`, no nó `report_writer`, ler `state.get("user_prompt")` e, quando
   presente, incluí-lo no system prompt / preâmbulo do LLM para guiar a síntese do relatório.
4. Criar `api/routes/report_gen.py` com a lógica do novo endpoint:
   - Deserializar `dashboard_context` para reconstruir o `AgentState` (preenchendo
     `axis1_result`, `axis2_result`, `axis3_result`, `investment_hypotheses`, `cross_matrix`,
     `region_scope`, `run_id`, `axes_selected`).
   - Definir `user_prompt` e `llm_provider` no estado.
   - Invocar apenas o nó `report_writer` diretamente (sem compilar o grafo completo):
     chamar `report_writer(state)` importado de `agent.graph`.
   - Persistir o Markdown resultante em `reports/`.
   - Retornar `AgentReportResponse`.
5. Registrar o novo router em `api/main.py`.

### Relevant Context
- `agent/graph.py` — função `report_writer(state)` (linha 485); recebe `AgentState` completo e
  retorna `{"report_markdown": ..., "report_json": ..., "audit_trail": [...]}`.
- `agent/state.py` — `AgentState` TypedDict; adicionar `user_prompt` aqui.
- `api/schemas.py` — modelos Pydantic existentes; seguir o mesmo padrão.
- `api/routes/agent.py` — padrão de endpoint existente para referência (`_invoke_agent`,
  `_persist_run`).
- `api/main.py` — onde os routers são registrados.
- Nome do arquivo de saída: `{region}_{date}_{run_id[:8]}.md` para evitar colisão com o relatório
  original da corrida.

---

## Sub-Task 2 — Adicionar `user_prompt` ao `report_writer` do agente

**Status:** [ ] pending

### Intent
Modificar o nó `report_writer` em `agent/graph.py` para que, quando o campo `user_prompt` estiver
presente no estado, ele seja usado para personalizar o relatório gerado pelo LLM. Isso deve ser
feito de forma retrocompatível: se `user_prompt` estiver ausente (como nas execuções existentes
via `RunPage`), o comportamento atual não muda.

### Expected Outcomes
- Quando `user_prompt` não está presente: comportamento atual inalterado.
- Quando `user_prompt` está presente: o prompt do usuário é adicionado ao preâmbulo do LLM
  (como instrução extra no system prompt, antes de gerar o conteúdo), guiando o foco do relatório.
- Se o `LLM_PROVIDER` for `stub` (sem LLM real), o prompt é incorporado como parágrafo de
  contextualização no início do Sumário Executivo, de forma determinística.

### Todo List
1. No início de `report_writer` em `agent/graph.py`, ler:
   `user_prompt = state.get("user_prompt") or None`.
2. Quando o provider LLM for real (não stub): passar `user_prompt` como instrução adicional
   para o LLM, prefixando-o no system prompt das seções que usam LLM (executive summary e
   "Próximas Ações").
3. Quando o provider for stub ou `user_prompt` não estiver presente: comportamento atual.
4. Registrar `user_prompt` no evento de auditoria `log_tool_call` dentro de `report_writer`
   (campo `tool_input`), para rastreabilidade.

### Relevant Context
- `agent/graph.py` linhas 485–801 — nó `report_writer` completo.
- `agent/llm_provider.py` — interface `chat()` do provider; o `system_prompt` é um argumento
  nomeado.
- `agent/state.py` — onde `user_prompt` será adicionado (feito na Sub-Task 1).

---

## Sub-Task 3 — Frontend: `NovoRelatorioModal` e botão no Dashboard

**Status:** [ ] pending

### Intent
Adicionar o botão **"Novo Relatório"** ao rodapé do Dashboard e implementar o modal de prompt.
O modal expõe um campo de texto livre, o seletor de LLM provider (igual ao do RunPage), e os
botões "Cancelar" / "Gerar Relatório". Ao confirmar, chama o novo endpoint de backend com o
contexto atual do dashboard.

### Expected Outcomes
- Botão "Novo Relatório" visível no rodapé da página Dashboard, apenas quando há um `report` no
  store (caso contrário, a seção vazia já redireciona para `/run`).
- O modal abre com um `<textarea>` para o prompt e o seletor de LLM.
- Durante o processamento: estado de loading com spinner e overlay (mesmo padrão do RunPage).
- Em caso de erro: banner de erro inline no modal (mesmo padrão do RunPage).
- Em caso de sucesso: modal fecha, queryClient invalida `['reports-list']`, e o usuário é
  navegado para `/reports`.

### Todo List
1. Em `frontend/src/api/reportsApi.ts`, adicionar a função `generateReport(params)` que chama
   `POST /v1/agent/report` com `AgentReportRequest` e retorna `AgentReportResponse`.
2. Adicionar os tipos `AgentReportRequest` e `AgentReportResponse` em `frontend/src/types.ts`.
3. Criar `frontend/src/components/NovoRelatorioModal.tsx`:
   - Props: `onClose: () => void`, `isOpen: boolean`.
   - State local: `prompt: string`, `llm: LLMProviderEnum`.
   - Lê `report` do Zustand store para montar o `dashboard_context` (serializa com
     `JSON.parse(JSON.stringify(report))`).
   - Usa `useMutation` do React Query para chamar `generateReport`.
   - `onSuccess`: `queryClient.invalidateQueries({ queryKey: ['reports-list'] })` e
     `navigate('/reports')`.
   - Overlay de loading e banner de erro seguindo o padrão visual do RunPage.
4. Em `frontend/src/pages/Dashboard.tsx`, importar e renderizar `NovoRelatorioModal`.
   Adicionar o estado `showModal: boolean` e o botão no rodapé da página (abaixo da seção de
   metadados do run), estilizado como botão secundário com ícone de documento.

### Relevant Context
- `frontend/src/pages/Dashboard.tsx` — estrutura atual da página; o rodapé fica nas linhas
  195–200 (seção de metadados).
- `frontend/src/pages/RunPage.tsx` — padrão visual do modal/loading/erro a seguir.
- `frontend/src/stores/reportStore.ts` — `useReportStore` fornece o `AgentRunResponse` atual.
- `frontend/src/api/reportsApi.ts` — onde a nova função de API será adicionada.
- `frontend/src/types.ts` — onde os novos tipos serão adicionados.
- `frontend/src/api/client.ts` — cliente Axios; injeta `X-API-Key` automaticamente.

---

## Notas de Arquitetura

- **Nenhum re-processamento de ML:** o novo endpoint não re-executa os eixos de ML. Ele usa os
  resultados já computados e armazenados no `AgentRunResponse` do Zustand/store. Isso mantém a
  operação rápida (segundos, não minutos).
- **Compatibilidade retroativa:** as alterações em `report_writer` e `AgentState` são
  retrocompatíveis. Execuções existentes via RunPage e LangGraph completo não são afetadas.
- **Colisão de nome de arquivo:** o nome do arquivo gerado inclui o `run_id[:8]` para
  distinguir do `.md` original da corrida.
- **Serialização do contexto:** o `dashboard_context` é o `AgentRunResponse` serializado como
  JSON no corpo da requisição. O backend o deserializa de volta para popular o `AgentState`
  antes de chamar `report_writer`.
