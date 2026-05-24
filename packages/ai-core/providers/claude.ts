import type { AIResponse } from "../types"

export async function claudeProvider(prompt: string): Promise<AIResponse> {
  const apiKey = process.env.ANTHROPIC_API_KEY

  if (!apiKey) {
    return { text: "ANTHROPIC_API_KEY not configured", model: "claude-4" }
  }

  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: "claude-sonnet-4-6",
      max_tokens: 4096,
      messages: [{ role: "user", content: prompt }],
    }),
  })

  const data = await res.json()
  return {
    text: data.content?.[0]?.text || "no response",
    model: "claude-4",
  }
}
