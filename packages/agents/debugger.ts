export interface DebugResult {
  issues: string[]
  fixes: string[]
  verified: boolean
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

function keywordDebug(errors: string[]): DebugResult {
  const issues = errors.map((e) => {
    if (/not found|enoent|no such/i.test(e)) return `Missing file or resource: ${e}`
    if (/syntax|unexpected|parse|typeerror|referenceerror/i.test(e)) return `Code error: ${e}`
    if (/timeout|timed out|etimedout/i.test(e)) return `Timeout error: ${e}`
    if (/permission|denied|eaccess/i.test(e)) return `Permission error: ${e}`
    if (/cannot find module|module.*not found/i.test(e)) return `Missing dependency: ${e}`
    return `Unknown issue: ${e}`
  })
  return { issues, fixes: issues.map((i) => `Investigate and resolve: ${i}`), verified: false }
}

export async function debuggerAgent(errors: string[]): Promise<DebugResult> {
  if (errors.length === 0) return { issues: [], fixes: [], verified: true }
  const llmPrompt = `You are a debugger. Analyze these errors and suggest fixes.
Errors:
${errors.map((e, i) => `${i + 1}. ${e}`).join("\n")}

Respond ONLY with JSON: {"issues":["issue1","issue2",...], "fixes":["fix1","fix2",...], "verified":true|false}
Set verified=true only if all errors are clearly diagnosed with concrete fixes.`
  const llmResult = await callLLM(llmPrompt)
  try {
    const parsed = JSON.parse(llmResult) as DebugResult
    if (parsed.issues?.length) return parsed
  } catch (e) {
    console.error("[debugger] LLM parse error, falling back to keywords:", e)
  }
  return keywordDebug(errors)
}
