import { spawn } from "child_process"

const ALLOWED_COMMANDS = new Set([
  "ls", "cat", "head", "tail", "echo", "pwd", "whoami", "date",
  "find", "grep", "wc", "sort", "uniq", "cut", "tr", "diff",
  "curl", "wget", "ping", "nslookup", "dig",
  "df", "du", "free", "ps",
  "git", "make", "npm", "pip", "go", "rustc", "cargo",
  "python", "python3", "node",
])

function validateCommand(cmd: string): { cmd: string; args: string[] } {
  const parts = cmd.split(/\s+/)
  if (!parts[0]) throw new Error("empty command")
  const base = parts[0].includes("/") ? parts[0].split("/").pop()! : parts[0]
  if (!ALLOWED_COMMANDS.has(base)) throw new Error(`command '${base}' not in allowlist`)
  return { cmd: base, args: parts.slice(1) }
}

export function runCommand(cmd: string): Promise<string> {
  let parsed: { cmd: string; args: string[] }
  try {
    parsed = validateCommand(cmd)
  } catch (e: unknown) {
    const msg = `[denied] ${(e as Error).message}`
    console.error("[terminal]", msg)
    return Promise.resolve(msg)
  }
  return new Promise((resolve, reject) => {
    const p = spawn(parsed.cmd, parsed.args, { shell: false, windowsHide: true })
    let out = ""
    let err = ""

    p.stdout.on("data", (d: Buffer) => (out += d.toString()))
    p.stderr.on("data", (d: Buffer) => (err += d.toString()))
    p.on("error", (e: Error) => reject(e))
    p.on("close", (code: number | null) => {
      if (code === 0) resolve(out)
      else resolve(err || out)
    })
  })
}
