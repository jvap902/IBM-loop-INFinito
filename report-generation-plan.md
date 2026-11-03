# Plano: "Novo Relatório" — Geração de Relatório via Prompt no Dashboard

## Visão Geral

Adicionar um botão **"Novo Relatório"** ao final da página Dashboard. Ao ser clicado, um modal
simples é exibido com um campo de prompt livre. O usuário descreve o foco do relatório (ex.:
"priorize as oportunidades P1 no Sudeste") e confirma. O backend busca o contexto da análise
já persistida (pelo `run_id` do dashboard), injeta o prompt do usuário, e invoca o nó
`report_writer` do agente de forma isolada — sem re-executar os eixos de ML. Ao terminar, o
usuário permanece no Dashboard e recebe uma confirmação visual inline.

**Escopo:** Frontend (modal + chamada de API + toast de confirmação) e uma nova rota de backend
que aceita `run_id` + `user_prompt`, busca o contexto em `runs/{run_id}.json`, e chama
`report_writer` diretamente. Dashboard, Zustand store e RunPage não são alterados.

**Não está no escopo:** reprocessar eixos de ML, alterar a análise em si, ou navegar o usuário
para outra página após a geração.

---

## Sub-Task 1 — Novo endpoint de backend `POST /v1/agent/report`

**Status:** [x] done

### Intent
Criar um endpoint FastAPI leve que recebe `run_id` e `user_prompt`, carrega o contexto da
análise de `runs/{run_id}.json`, reconstrói o `AgentState`, e invoca `report_writer(state)`
diretamente — sem recompilar o grafo LangGraph nem re-rodar os eixos de ML. O `.md` gerado é
persistido em `reports/` e retornado ao cliente.

### Expected Outcomes
- `POST /v1/agent/report` aceita `AgentReportRequest` (campos: `run_id`, `user_prompt`,
  `llm_provider`) e retorna `AgentReportResponse` (campos: `filename`, `content`).
- O arquivo é salvo como `reports/{region}_{date}_{run_id[:8]}.md` para não colidir com o
  relatório original da corrida.
- O `user_prompt` é propagado para o `AgentState` e usado pelo `report_writer`.
- O endpoint requer `X-API-Key`.
- Se `runs/{run_id}.json` não existir, retorna HTTP 404.

### Todo List
1. Em `api/schemas.py`, adicionar dois novos modelos Pydantic:
   - `AgentReportRequest`: campos `run_id: str`, `user_prompt: str`,
     `llm_provider: Literal['stub', 'watsonx', 'openai', 'gemini']`.
   - `AgentReportResponse`: campos `filename: str`, `content: str`.
2. Em `agent/state.py`, adicionar o campo `user_prompt: Optional[str]` ao `AgentState`.
3. Criar `api/routes/report_gen.py` com o endpoint `POST /agent/report`:
   - Carregar `runs/{run_id}.json` (retornar 404 se não existir).
   - Deserializar o JSON para reconstruir o `AgentState`, preenchendo:
     `axis1_result`, `axis2_result`, `axis3_result`, `investment_hypotheses`, `cross_matrix`,
     `region_scope`, `run_id`, `axes_selected`.
   - Definir `user_prompt` e sobrescrever `LLM_PROVIDER` para a requisição (padrão de
     `_invoke_agent` em `api/routes/agent.py`).
   - Importar e chamar `report_writer(state)` de `agent.graph` diretamente (não compila o
     grafo completo).
   - Persistir o Markdown resultante em `reports/` com nome
     `{region}_{date}_{run_id[:8]}.md`.
   - Retornar `AgentReportResponse`.
4. Registrar o novo router em `api/main.py`.

### Relevant Context
- `agent/graph.py:485` — função `report_writer(state)`; recebe `AgentState` completo e
  retorna `{"report_markdown": ..., "report_json": ..., "audit_trail": [...]}`.
- `agent/state.py` — `AgentState` TypedDict; `user_prompt` será adicionado aqui.
- `api/schemas.py` — modelos Pydantic existentes; seguir o mesmo padrão de herança e Field.
- `api/routes/agent.py` — padrão de endpoint a replicar: `_invoke_agent`, override de
  `LLM_PROVIDER` via `os.environ`, restore no bloco `finally`.
- `api/main.py` — onde os routers são registrados com `app.include_router`.
- `runs/` — diretório onde `_persist_run` salva `{run_id}.json`; é o contexto que será lido.

---

## Sub-Task 2 — Injetar `user_prompt` no nó `report_writer`

**Status:** [x] done

### Intent
Modificar `report_writer` em `agent/graph.py` para que, quando `user_prompt` estiver presente
no estado, ele seja injetado como instrução extra no system prompt do LLM antes de gerar o
Sumário Executivo e a seção "Próximas Ações". A mudança é totalmente retrocompatível: se
`user_prompt` estiver ausente, o comportamento existente é preservado. Para o provider `stub`,
o prompt é incluído como parágrafo no Sumário Executivo de forma determinística.

### Expected Outcomes
- Quando `user_prompt` está ausente: comportamento atual inalterado (nenhum caminho de código
  trocado).
- Quando `user_prompt` está presente com um provider LLM real: o prompt é prefixado no
  `system_prompt` das chamadas `llm.chat()` relevantes.
- Quando `user_prompt` está presente com provider `stub`: o prompt é adicionado como
  parágrafo descritivo no início do Sumário Executivo.
- `user_prompt` é registrado no evento de auditoria `log_tool_call` (campo `tool_input`).

### Todo List
1. No início de `report_writer` em `agent/graph.py`, extrair:
   `user_prompt = state.get("user_prompt") or None`.
2. Construir `prompt_instruction: str` — quando `user_prompt` não é None, formatar como:
   `"Instrução do usuário para este relatório: {user_prompt}\n\n"`.
   Quando é None, usar string vazia (sem mudança de comportamento).
3. Prefixar `prompt_instruction` no `system_prompt` das chamadas LLM existentes dentro de
   `report_writer` (executive summary e seção 7 — "Próximas Ações").
4. No path do `stub`: concatenar `prompt_instruction` ao início de `exec_summary`.
5. Adicionar `"user_prompt": user_prompt` ao dict `tool_input` na chamada
   `audit.log_tool_call(...)`.

### Relevant Context
- `agent/graph.py:485–801` — nó `report_writer` completo.
- `agent/llm_provider.py` — interface `chat(prompt, *, system_prompt, temperature,
  max_tokens)`; o parâmetro `system_prompt` é onde a instrução será prefixada.
- `agent/state.py` — campo `user_prompt` adicionado na Sub-Task 1.

---

## Sub-Task 3 — Frontend: modal, botão e toast de confirmação

**Status:** [x] done

### Intent
Adicionar o botão **"Novo Relatório"** ao rodapé do Dashboard. Ao clicar, um modal abre com
um `<textarea>` de prompt livre e um seletor de LLM provider. Ao confirmar, o frontend envia
`run_id` (do `AgentRunResponse` no Zustand) + `user_prompt` para o novo endpoint. O modal
fecha e, em vez de navegar, o Dashboard exibe um **toast de confirmação** (verde em sucesso,
vermelho em erro) que desaparece automaticamente após alguns segundos.

### Expected Outcomes
- Botão "Novo Relatório" visível no rodapé da página Dashboard (abaixo dos metadados do run),
  apenas quando há um `report` carregado no store Zustand.
- Modal com: `<textarea>` de prompt, seletor de LLM provider (igual ao RunPage), botões
  "Cancelar" e "Gerar Relatório".
- Durante o processamento: botão "Gerar" desabilitado com spinner; overlay de loading sobre
  o modal (mesmo padrão visual do RunPage).
- Em caso de sucesso: modal fecha; toast verde "Relatório gerado com sucesso" aparece na
  tela por ~4 s e depois desaparece; `queryClient.invalidateQueries(['reports-list'])` é
  chamado (para que a aba Relatórios já mostre o novo arquivo ao ser visitada).
- Em caso de erro: banner de erro inline no modal (não fecha); o usuário pode corrigir e
  tentar novamente.
- O toast é um componente simples posicionado `fixed bottom-6 right-6` com animação de fade.

### Todo List
1. Em `frontend/src/types.ts`, adicionar os tipos:
   - `AgentReportRequest`: `{ run_id: string; user_prompt: string; llm_provider: AgentRunRequest['llm_provider'] }`.
   - `AgentReportResponse`: `{ filename: string; content: string }`.
2. Em `frontend/src/api/reportsApi.ts`, adicionar a função:
   `generateReport(params: AgentReportRequest): Promise<AgentReportResponse>`
   chamando `POST /agent/report`.
3. Criar `frontend/src/components/NovoRelatorioModal.tsx`:
   - Props: `isOpen: boolean`, `runId: string`, `onClose: () => void`,
     `onSuccess: (filename: string) => void`.
   - State local: `prompt: string`, `llm: AgentRunRequest['llm_provider']` (default `'stub'`).
   - `useMutation` chamando `generateReport({ run_id: runId, user_prompt: prompt, llm_provider: llm })`.
   - `onSuccess(data)`: fecha o modal, chama a prop `onSuccess(data.filename)`.
   - Overlay de loading e banner de erro inline, seguindo o padrão visual de `RunPage.tsx`.
4. Criar `frontend/src/components/ReportToast.tsx`:
   - Props: `message: string`, `type: 'success' | 'error'`, `onDismiss: () => void`.
   - Posicionado `fixed bottom-6 right-6 z-50`.
   - Auto-dismiss via `useEffect` com `setTimeout` de 4000 ms.
   - Estilo: verde (`bg-green-900/80 border-green-700 text-green-300`) para sucesso,
     vermelho para erro, com ícone ✓ ou ✕.
5. Em `frontend/src/pages/Dashboard.tsx`:
   - Importar `NovoRelatorioModal` e `ReportToast`.
   - Adicionar estado local: `showModal: boolean`, `toast: { message: string; type: 'success' | 'error' } | null`.
   - Adicionar botão "Novo Relatório" no rodapé da página (abaixo da linha de metadados do
     run, linhas 195–200), estilizado como botão secundário com bordas e ícone de documento.
   - Callback `handleReportSuccess(filename)`: fechar modal, setar toast de sucesso com
     o filename, chamar `queryClient.invalidateQueries({ queryKey: ['reports-list'] })`.
   - Renderizar `<NovoRelatorioModal>` e `<ReportToast>` condicionalmente.

### Relevant Context
- `frontend/src/pages/Dashboard.tsx:195–200` — rodapé atual (metadados do run); o botão
  é adicionado logo abaixo desta seção.
- `frontend/src/pages/RunPage.tsx` — padrão visual a replicar (loading overlay, error banner,
  seletor de LLM).
- `frontend/src/stores/reportStore.ts` — `useReportStore` fornece `report.run_id`.
- `frontend/src/api/reportsApi.ts` — onde `generateReport` será adicionado.
- `frontend/src/types.ts` — onde os novos tipos serão adicionados.
- `frontend/src/api/client.ts` — Axios instance; injeta `X-API-Key` automaticamente.
- O `queryClient` está disponível via `useQueryClient()` do React Query.

---

## Notas de Arquitetura

- **Lookup por `run_id` (não serialização inline):** o frontend envia apenas o `run_id`; o
  backend carrega o contexto completo de `runs/{run_id}.json`. Isso mantém o payload da
  requisição mínimo e evita duplicação de dados no tráfego HTTP.
- **Sem re-processamento de ML:** `report_writer` é invocado diretamente com o estado
  reconstruído; nenhum eixo de ML é re-executado. A operação leva segundos.
- **Retrocompatibilidade total:** `user_prompt` é `Optional` no `AgentState`; execuções
  existentes via RunPage / LangGraph completo não passam por nenhum código novo.
- **Colisão de nome de arquivo:** o nome `{region}_{date}_{run_id[:8]}.md` garante unicidade
  mesmo que o usuário gere múltiplos relatórios a partir da mesma corrida.
- **Permanência no Dashboard:** o usuário não é redirecionado; o toast confirma o sucesso e
  a aba Relatórios é pré-invalidada em background, pronta para quando o usuário navegar até lá.
