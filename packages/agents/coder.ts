export interface CoderAction {
  type: "edit" | "create" | "delete"
  file: string
  content?: string
  description: string
}

export async function coderAgent(plan: string[]): Promise<CoderAction[]> {
  return plan.map((step) => ({
    type: "edit" as const,
    file: "src/index.ts",
    description: step,
  }))
}
