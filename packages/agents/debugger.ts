export interface DebugResult {
  issues: string[]
  fixes: string[]
  verified: boolean
}

export async function debuggerAgent(errors: string[]): Promise<DebugResult> {
  return {
    issues: errors,
    fixes: errors.map((e) => `Fix for: ${e}`),
    verified: false,
  }
}
