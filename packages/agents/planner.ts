import { callLLM } from "../ai-core/callLLM"

export interface Plan {
  steps: string[]
  estimatedComplexity: "low" | "medium" | "high"
  tools: string[]
}

function keywordPlan(task: string): Plan {
  const taskLower = task.toLowerCase()
  const hasRead = /(read|find|search|get|show)/.test(taskLower)
  const hasEdit = /(edit|change|update|add|fix|refactor)/.test(taskLower)
  const hasCreate = /(create|new|generate|write|build)/.test(taskLower)
  const hasTest = /(test|verify|check|validate)/.test(taskLower)
  const hasDebug = /(debug|fix|bug|error|issue)/.test(taskLower)
  const steps: string[] = []
  if (hasRead || hasCreate) steps.push(`Understand requirements: ${task}`)
  if (hasRead || hasCreate || hasEdit) steps.push("Search relevant code and context")
  if (hasEdit || hasCreate) steps.push(hasCreate ? "Generate new code" : "Execute changes")
  if (hasTest || hasDebug) steps.push(hasDebug ? "Debug and fix issues" : "Verify results")
  if (steps.length === 0) steps.push(`Analyze task: ${task}`, "Execute changes", "Verify results")
  const complexity: "low" | "medium" | "high" = steps.length <= 2 ? "low" : steps.length >= 4 ? "high" : "medium"
  const tools = ["read_file", "grep", "bash"]
  if (hasEdit || hasCreate) tools.push("edit")
  if (hasTest) tools.push("bash")
  return { steps, estimatedComplexity: complexity, tools }
}

export async function plannerAgent(task: string, memory: string[]): Promise<Plan> {
  const llmPrompt = `You are a software planner. Given a task and recent memory, output a JSON plan.
Task: "${task}"
Recent memory: ${memory.slice(-5).join("; ") || "none"}

Respond ONLY with JSON: {"steps":["step1","step2",...], "estimatedComplexity":"low|medium|high", "tools":["tool1",...]}

Tools available: read_file, grep, edit, bash, search, web_search, list_dir, run_tests`
  const llmResult = await callLLM(llmPrompt)
  try {
    const parsed = JSON.parse(llmResult) as Plan
    if (parsed.steps?.length && parsed.estimatedComplexity && parsed.tools?.length) return parsed
  } catch (e) {
    console.error("[planner] LLM parse error, falling back to keywords:", e)
  }
  return keywordPlan(task)
}
