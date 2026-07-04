import { plannerAgent } from "./planner"
import { coderAgent } from "./coder"
import { debuggerAgent } from "./debugger"

export async function autonomousLoop(task: string) {
  const memory: string[] = []
  const maxSteps = 25

  for (let step = 0; step < maxSteps; step++) {
    const plan = await plannerAgent(task, memory)
    const actions = await coderAgent(plan.steps)

    for (const action of actions) {
      memory.push(`Executed: ${action.description}`)
    }

    const result = await debuggerAgent(memory)
    if (result.verified) break
  }

  return { completed: result.verified, steps: memory.length }
}
