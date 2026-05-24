export function parseAST(source: string, language: string) {
  return {
    language,
    functions: [],
    imports: [],
    exports: [],
    classes: [],
  }
}

export function findDependencies(source: string) {
  const imports = source.match(/from ['"]([^'"]+)['"]/g) || []
  return imports.map((i) => i.replace(/from ['"]/, "").replace(/['"]$/, ""))
}
