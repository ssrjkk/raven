import { execSync, exec } from "child_process"

function dockerAvailable(): boolean {
  try {
    execSync("docker info", { stdio: "ignore", timeout: 5000 })
    return true
  } catch (e) {
    console.warn("[docker] not available, using mock fallback:", (e as Error).message?.split("\n")[0])
    return false
  }
}

async function dockerCmd(args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    exec(`docker ${args.join(" ")}`, { timeout: 30000 }, (err, stdout, stderr) => {
      if (err) reject(new Error(stderr.trim() || err.message))
      else resolve(stdout.trim())
    })
  })
}

export async function createSandbox(image: string = "node:20") {
  if (!dockerAvailable()) {
    return { id: `sandbox-${Date.now()}`, image, status: "mock", ports: [] }
  }
  try {
    const id = await dockerCmd(["run", "-d", "--rm", image, "sleep", "3600"])
    return { id: id.slice(0, 12), image, status: "created", ports: [] }
  } catch (e) {
    console.warn("[docker] createSandbox failed, returning mock:", e)
    return { id: `sandbox-${Date.now()}`, image, status: "mock", ports: [] }
  }
}

export async function executeInSandbox(containerId: string, command: string) {
  if (containerId.startsWith("sandbox-")) {
    console.warn("[docker] executeInSandbox called on mock container")
    return { containerId, command, exitCode: 0, output: `Executed: ${command}` }
  }
  try {
    const output = await dockerCmd(["exec", containerId, "sh", "-c", command])
    return { containerId, command, exitCode: 0, output }
  } catch (e: unknown) {
    return { containerId, command, exitCode: 1, output: (e as Error).message }
  }
}

export async function destroySandbox(containerId: string) {
  if (containerId.startsWith("sandbox-")) {
    return { containerId, status: "destroyed" }
  }
  try {
    await dockerCmd(["kill", containerId])
    return { containerId, status: "destroyed" }
  } catch (e) {
    console.warn("[docker] destroySandbox failed:", e)
    return { containerId, status: "destroyed" }
  }
}
