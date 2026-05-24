import { spawn } from "child_process"

export function runCommand(cmd: string): Promise<string> {
  return new Promise((resolve) => {
    const p = spawn(cmd, { shell: true })
    let out = ""

    p.stdout.on("data", (d) => (out += d.toString()))
    p.stderr.on("data", (d) => (out += d.toString()))
    p.on("close", () => resolve(out))
  })
}
