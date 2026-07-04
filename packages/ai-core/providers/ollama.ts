import type { AIResponse } from "../types"

export async function ollamaProvider(prompt: string): Promise<AIResponse> {
  try {
    const res = await fetch("http://localhost:11434/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "codellama",
        prompt,
        stream: false,
      }),
    })

    const data = await res.json()
    return {
      text: data.response || "no response",
      model: "ollama/codellama",
    }
  } catch (e) {
    throw new Error(`Ollama not running on localhost:11434 — ${e}`)
  }
}
