export type TaskType = "code" | "fast" | "architecture" | "debug" | "refactor" | "deploy"

export interface Task {
  id: string
  type: TaskType
  prompt: string
  context?: string[]
  createdAt: Date
}

export interface Project {
  id: string
  name: string
  path: string
  repoUrl?: string
}

export interface AgentConfig {
  name: string
  model: string
  mode: "primary" | "subagent"
  permission?: Record<string, any>
}
