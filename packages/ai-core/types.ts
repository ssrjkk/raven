export interface AIRequest {
  prompt: string
  task: "code" | "fast" | "architecture" | "debug" | "refactor"
  model?: string
  context?: string[]
}

export interface AIResponse {
  text: string
  model: string
  usage?: {
    promptTokens: number
    completionTokens: number
  }
}

export type AIProvider = (prompt: string, context?: string[]) => Promise<AIResponse>
