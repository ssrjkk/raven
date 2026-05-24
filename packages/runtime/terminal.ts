import { spawn } from "child_process"

export function runCommand(cmd: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, { shell: true })
    let out = ""
    let err = ""

    p.stdout.on("data", (d) => (out += d.toString()))
    p.stderr.on("data", (d) => (err += d.toString()))
    p.on("error", (e) => reject(e))
    p.on("close", (code) => {
      if (code === 0) resolve(out)
      else resolve(err || out)
    })
  })
}
