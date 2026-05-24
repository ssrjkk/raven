export interface Plan {
  steps: string[]
  estimatedComplexity: "low" | "medium" | "high"
  tools: string[]
}

export async function plannerAgent(task: string, memory: string[]): Promise<Plan> {
  const steps = [
    `Analyze task: ${task}`,
    "Search relevant code",
    "Execute changes",
    "Verify results",
  ]

  return {
    steps,
    estimatedComplexity: "medium",
    tools: ["read_file", "grep", "edit", "bash"],
  }
}
