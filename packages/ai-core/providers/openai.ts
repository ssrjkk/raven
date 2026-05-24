import type { AIResponse } from "../types"

export async function openAIProvider(prompt: string): Promise<AIResponse> {
  const apiKey = process.env.OPENAI_API_KEY

  if (!apiKey) {
    return { text: "OPENAI_API_KEY not configured", model: "gpt-5" }
  }

  const res = await fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: "gpt-5",
      messages: [{ role: "user", content: prompt }],
    }),
  })

  const data = await res.json()
  return {
    text: data.choices?.[0]?.message?.content || "no response",
    model: "gpt-5",
  }
}
