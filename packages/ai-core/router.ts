import { openAIProvider } from "./providers/openai"
import { claudeProvider } from "./providers/claude"

export async function aiRouter({ prompt, task }: { prompt: string; task: string }) {
  if (task === "fast") return openAIProvider(prompt)
  if (task === "architecture") return claudeProvider(prompt)

  return openAIProvider(prompt)
}
