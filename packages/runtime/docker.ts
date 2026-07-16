import { spawnSync, execSync, spawn } from "child_process"

export class DockerUnavailableError extends Error {
  constructor(msg = "Docker is not available") {
    super(msg)
    this.name = "DockerUnavailableError"
  }
}

function dockerCheck(): void {
  try {
    execSync("docker info", { stdio: "ignore", timeout: 5000 })
  } catch {
    throw new DockerUnavailableError("Docker is not available. Install Docker or pass --no-sandbox.")
  }
}

async function dockerCmd(args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    const proc = spawn("docker", args, { timeout: 30000, shell: false, stdio: ["ignore", "pipe", "pipe"] })
    let stdout = ""
    let stderr = ""
    proc.stdout?.on("data", (chunk: Buffer) => { stdout += chunk.toString() })
    proc.stderr?.on("data", (chunk: Buffer) => { stderr += chunk.toString() })
    proc.on("error", (err) => reject(err))
    proc.on("close", (code) => {
      if (code === 0) resolve(stdout.trim())
      else reject(new Error(stderr.trim() || `exit code ${code}`))
    })
  })
}

export async function createSandbox(image: string = "node:20") {
  dockerCheck()
  const id = await dockerCmd(["run", "-d", "--rm", image, "sleep", "3600"])
  return { id: id.slice(0, 12), image, status: "created", ports: [] }
}

export async function executeInSandbox(containerId: string, command: string) {
  dockerCheck()
  const output = await dockerCmd(["exec", containerId, "sh", "-c", command])
  return { containerId, command, exitCode: 0, output }
}

export async function destroySandbox(containerId: string) {
  dockerCheck()
  await dockerCmd(["kill", containerId])
  return { containerId, status: "destroyed" }
}
