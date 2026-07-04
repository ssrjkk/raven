interface ASTResult {
  language: string
  functions: { name: string; params: string[]; startLine: number }[]
  imports: { source: string; names: string[] }[]
  exports: { name: string; type: string }[]
  classes: { name: string; methods: string[]; startLine: number }[]
}

function extractImports(source: string): ASTResult["imports"] {
  const imports: ASTResult["imports"] = []
  const esmRe = /import\s+(?:\{?\s*([^}]+?)\s*\}?\s+from\s+)?['"]([^'"]+)['"]/g
  let m: RegExpExecArray | null
  while ((m = esmRe.exec(source)) !== null) {
    const names = m[1] ? m[1].split(",").map((n) => n.trim().replace(/\s+as\s+\w+/, "")) : []
    imports.push({ source: m[2], names })
  }
  const requireRe = /(?:const|let|var)\s+(\w+)\s*=\s*require\(['"]([^'"]+)['"]\)/g
  while ((m = requireRe.exec(source)) !== null) {
    imports.push({ source: m[2], names: [m[1]] })
  }
  return imports
}

function extractFunctions(source: string): ASTResult["functions"] {
  const functions: ASTResult["functions"] = []
  const lines = source.split("\n")
  const fnRe = /(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)/
  const arrowRe = /(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*(?::\s*\w+)?\s*=>/
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    let match = line.match(fnRe) || line.match(arrowRe)
    if (match) {
      functions.push({
        name: match[1],
        params: match[2].split(",").map((p) => p.trim()).filter(Boolean),
        startLine: i + 1,
      })
    }
  }
  return functions
}

function extractClasses(source: string): ASTResult["classes"] {
  const classes: ASTResult["classes"] = []
  const lines = source.split("\n")
  const classRe = /(?:export\s+)?(?:abstract\s+)?class\s+(\w+)(?:\s+extends\s+\w+)?(?:\s+implements\s+[\w\s,]+)?\s*\{/
  for (let i = 0; i < lines.length; i++) {
    const match = lines[i].match(classRe)
    if (match) {
      const methods: string[] = []
      for (let j = i + 1; j < Math.min(i + 100, lines.length); j++) {
        const methodMatch = lines[j].match(/(?:\w+\s+)?(\w+)\s*\([^)]*\)\s*(?:\{|:)/)
        if (methodMatch && !/^(if|for|while|switch|catch)$/.test(methodMatch[1])) methods.push(methodMatch[1])
        if (lines[j].includes("}") && methods.length > 0) break
      }
      classes.push({ name: match[1], methods: methods.slice(0, 20), startLine: i + 1 })
    }
  }
  return classes
}

function extractExports(source: string): ASTResult["exports"] {
  const exports: ASTResult["exports"] = []
  const exportRe = /export\s+(?:default\s+)?(?:function|const|let|var|class|interface|type)\s+(\w+)/g
  let m: RegExpExecArray | null
  while ((m = exportRe.exec(source)) !== null) {
    exports.push({ name: m[1], type: "named" })
  }
  if (/export\s+default\s+/.test(source)) exports.push({ name: "default", type: "default" })
  return exports
}

export function parseAST(source: string, language: string): ASTResult {
  return {
    language,
    functions: extractFunctions(source),
    imports: extractImports(source),
    exports: extractExports(source),
    classes: extractClasses(source),
  }
}

export function findDependencies(source: string): string[] {
  const imports = source.match(/from\s+['"]([^'"]+)['"]/g) || []
  const requires = source.match(/require\(['"]([^'"]+)['"]\)/g) || []
  return [
    ...imports.map((i) => i.replace(/from\s+['"]/, "").replace(/['"]$/, "")),
    ...requires.map((r) => r.replace(/require\(['"]/, "").replace(/['"]\)$/, "")),
  ]
}
