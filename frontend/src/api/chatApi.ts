import client from './client'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  is_stub?: boolean
}

export interface AgentChatResponse {
  answer: string
  is_stub: boolean
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
