import client from './client'

export interface SourceItem {
  section: string
  values: string[]
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  is_stub?: boolean
  sources?: SourceItem[]
}

export interface AgentChatResponse {
  answer: string
  is_stub: boolean
  sources?: SourceItem[]
}

export async function sendChatMessage(
  question: string,
  reportContext: Record<string, unknown>,
  history: ChatMessage[],
): Promise<AgentChatResponse> {
  const { data } = await client.post<AgentChatResponse>('/agent/chat', {
    question,
    report_context: reportContext,
    history,
  })
  return data
}
