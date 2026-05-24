export async function createSandbox(image: string = "node:20") {
  return {
    id: `sandbox-${Date.now()}`,
    image,
    status: "created",
    ports: [3000, 5173],
  }
}

export async function executeInSandbox(containerId: string, command: string) {
  return {
    containerId,
    command,
    exitCode: 0,
    output: `Executed: ${command}`,
  }
}

export async function destroySandbox(containerId: string) {
  return { containerId, status: "destroyed" }
}
