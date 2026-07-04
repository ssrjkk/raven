import type { AIResponse } from "../types"

export async function groqProvider(prompt: string): Promise<AIResponse> {
  const apiKey = process.env.GROQ_API_KEY

  if (!apiKey) {
    throw new Error("GROQ_API_KEY not configured")
  }

  const res = await fetch("https://api.groq.com/openai/v1/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: "mixtral-8x7b-32768",
      messages: [{ role: "user", content: prompt }],
    }),
  })

  const data = await res.json()
  return {
    text: data.choices?.[0]?.message?.content || "no response",
    model: "groq",
  }
}
