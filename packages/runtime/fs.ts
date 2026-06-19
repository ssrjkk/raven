import fs from "fs/promises"
import path from "path"

const ALLOWED_BASE = path.resolve(process.env.RAVEN_ALLOWED_FS || "/tmp/raven")

function guard(p: string): string {
  const resolved = path.resolve(p)
  if (!resolved.startsWith(ALLOWED_BASE)) {
    throw new Error(`Access denied: path must be under ${ALLOWED_BASE}`)
  }
  return resolved
}

export const readFile = (p: string) => fs.readFile(guard(p), "utf-8")
export const writeFile = (p: string, c: string) => fs.writeFile(guard(p), c, "utf-8")
export const deleteFile = (p: string) => fs.unlink(guard(p))
export const listDir = async (p: string) => {
  const dir = guard(p)
  return fs.readdir(dir)
}
export const mkdir = (p: string) => fs.mkdir(guard(p), { recursive: true })
export const fileExists = async (p: string) => {
  try {
    await fs.access(guard(p))
    return true
  } catch {
    return false
  }
}
