import fs from "fs/promises"

export const readFile = (p: string) => fs.readFile(p, "utf-8")
export const writeFile = (p: string, c: string) => fs.writeFile(p, c, "utf-8")
export const deleteFile = (p: string) => fs.unlink(p)
export const listDir = (p: string) => fs.readdir(p)
export const mkdir = (p: string) => fs.mkdir(p, { recursive: true })
export const fileExists = async (p: string) => {
  try {
    await fs.access(p)
    return true
  } catch {
    return false
  }
}
