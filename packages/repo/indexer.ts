import fs from "fs/promises"
import path from "path"

export async function indexRepository(repoPath: string) {
  const files: string[] = []

  async function walk(dir: string) {
    const entries = await fs.readdir(dir, { withFileTypes: true })
    for (const entry of entries) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory() && !entry.name.startsWith(".") && entry.name !== "node_modules") {
        await walk(full)
      } else if (entry.isFile() && /\.(ts|tsx|js|jsx|rs|json|md)$/.test(entry.name)) {
        files.push(full)
      }
    }
  }

  await walk(repoPath)

  return {
    filesIndexed: files.length,
    files,
  }
}
