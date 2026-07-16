const DEFAULT_MODEL = "openai/gpt-4o-mini"
const DEFAULT_MAX_TOKENS = 512
const OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

export interface CallLLMOptions {
  model?: string
  maxTokens?: number
  temperature?: number
}

export async function callLLM(
  prompt: string,
  options: CallLLMOptions = {},
): Promise<string> {
  const apiKey = process.env.OPENROUTER_API_KEY || process.env.OPENAI_API_KEY
  if (!apiKey) throw new Error("OPENROUTER_API_KEY or OPENAI_API_KEY not set")

  const url = process.env.OPENROUTER_BASE_URL || OPENROUTER_URL
  const model = options.model || DEFAULT_MODEL
  const maxTokens = options.maxTokens ?? DEFAULT_MAX_TOKENS

  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({
      model,
      messages: [{ role: "user", content: prompt }],
      max_tokens: maxTokens,
      temperature: options.temperature,
    }),
  })
  const data = await res.json() as { choices?: { message?: { content?: string } }[] }
  return data.choices?.[0]?.message?.content?.trim() ?? ""
}
