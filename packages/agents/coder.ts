export interface CoderAction {
  type: "edit" | "create" | "delete"
  file: string
  content?: string
  description: string
}

async function callLLM(prompt: string): Promise<string> {
  const apiKey = process.env.OPENROUTER_API_KEY || process.env.OPENAI_API_KEY
  const url = process.env.OPENROUTER_BASE_URL || "https://openrouter.ai/api/v1/chat/completions"
  if (!apiKey) throw new Error("OPENROUTER_API_KEY or OPENAI_API_KEY not set")
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({ model: "openai/gpt-4o-mini", messages: [{ role: "user", content: prompt }], max_tokens: 512 }),
  })
  const data = await res.json() as { choices?: { message?: { content?: string } }[] }
  return data.choices?.[0]?.message?.content?.trim() ?? ""
}

function keywordActions(plan: string[]): CoderAction[] {
  return plan.map((step) => {
    const lower = step.toLowerCase()
    let type: CoderAction["type"] = "edit"
    let file = "src/index.ts"
    if (/create|new|generate/.test(lower)) { type = "create"; file = "src/new.ts" }
    else if (/delete|remove/.test(lower)) { type = "delete"; file = "src/old.ts" }
    else if (/test/.test(lower)) { type = "edit"; file = "src/test.ts" }
    return { type, file, description: step }
  })
}

export async function coderAgent(plan: string[]): Promise<CoderAction[]> {
  const llmPrompt = `You are a code generation agent. Given a plan, produce a list of file actions.
Plan steps:
${plan.map((s, i) => `${i + 1}. ${s}`).join("\n")}

Respond ONLY with JSON array: [{"type":"edit|create|delete","file":"path/to/file","description":"what to do"}]`
  const llmResult = await callLLM(llmPrompt)
  try {
    const parsed = JSON.parse(llmResult) as CoderAction[]
    if (Array.isArray(parsed) && parsed.length > 0) return parsed
  } catch (e) {
    console.error("[coder] LLM parse error, falling back to keywords:", e)
  }
  return keywordActions(plan)
}
