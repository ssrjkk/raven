import Editor, { type Monaco } from "@monaco-editor/react"
import { Bot, Bug, ChevronDown, ChevronRight, File as FileIcon, FolderClosed, FolderOpen, Loader2, Mic, MicOff, Search, ShieldAlert, Square, X } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"

import { api } from "../api/client"
import DebugPanel from "../components/DebugPanel"
import { useTheme } from "../design/ThemeContext"
import { type AgentSocketEvent, useAgentSocket } from "../hooks/useAgentSocket"
import { useSpeechInput } from "../hooks/useSpeechInput"

interface TerminalLine {
  input: string
  output: string
}

interface TraceRow {
  id: number
  kind: string
  text: string
}

interface FileTreeNode {
  type: "file" | "directory"
  name: string
  path: string
  children?: FileTreeNode[]
}

interface OpenFile {
  path: string
  name: string
  content: string
  language: string
  dirty: boolean
}

type AgentMode = "build" | "plan" | "general"

const AGENT_MODES: { value: AgentMode; label: string; desc: string }[] = [
  { value: "build",  label: "Build",  desc: "Write & edit code directly" },
  { value: "plan",   label: "Plan",   desc: "Design & architect only (no writes)" },
  { value: "general",label: "General",desc: "Answer questions about code" },
]

const TRUTHFUL_STATUS: Record<string, { label: string; color: string }> = {
  success: { label: "Verified", color: "badge badge-success" },
  corrected: { label: "Self-corrected", color: "badge badge-warning" },
  refused: { label: "Refused (no data)", color: "badge badge-error" },
}

const AGENT_MODE_TOOLS: Record<AgentMode, { maxSteps: number; diffPreview: boolean }> = {
  build:   { maxSteps: 40, diffPreview: true },
  plan:    { maxSteps: 40, diffPreview: true },
  general: { maxSteps: 30, diffPreview: true },
}

const LANG_MAP: Record<string, string> = {
  ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript",
  py: "python", rs: "rust", go: "go", java: "java", kt: "kotlin",
  rb: "ruby", php: "php", cs: "csharp", cpp: "cpp", c: "c", h: "c",
  html: "html", css: "css", scss: "scss", less: "less",
  json: "json", yaml: "yaml", yml: "yaml", toml: "toml", xml: "xml",
  md: "markdown", sql: "sql", sh: "shell", bash: "shell", zsh: "shell",
  dockerfile: "dockerfile", makefile: "makefile",
}

function languageFromPath(filePath: string): string {
  const name = filePath.split("/").pop()?.split("\\").pop() ?? ""
  const lower = name.toLowerCase()
  if (lower === "dockerfile") return "dockerfile"
  if (lower === "makefile") return "makefile"
  const ext = lower.split(".").pop() ?? ""
  return LANG_MAP[ext] ?? "plaintext"
}

function fileName(filePath: string): string {
  return filePath.split("/").pop()?.split("\\").pop() ?? filePath
}

export default function IDEPage() {
  const { theme } = useTheme();
  const [output, setOutput] = useState("")
  const [aiPrompt, setAiPrompt] = useState("")
  const [agentMode, setAgentMode] = useState<AgentMode>("build")
  const [terminalInput, setTerminalInput] = useState("")
  const [terminalHistory, setTerminalHistory] = useState<TerminalLine[]>([])
  const [indexStatus, setIndexStatus] = useState<string>("")
  const [sidebarTab, setSidebarTab] = useState<"ai" | "debug" | "search">("ai")
  const [truthfulMode, setTruthfulMode] = useState(false)
  const [truthfulStatus, setTruthfulStatus] = useState<string>("")
  const [thinkingProcess, setThinkingProcess] = useState("")
  const [traces, setTraces] = useState<TraceRow[]>([])
  const [pendingConfirm, setPendingConfirm] = useState<{ tool: string; arguments: Record<string, unknown>; diff?: string } | null>(null)

  const [fileTree, setFileTree] = useState<FileTreeNode | null>(null)
  const [openFiles, setOpenFiles] = useState<Record<string, OpenFile>>({})
  const [activePath, setActivePath] = useState<string | null>(null)
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set(["."]))
  const [treeRoot, setTreeRoot] = useState<string>("")

  const [searchQuery, setSearchQuery] = useState("")
  const [searchResults, setSearchResults] = useState<{ file: string; line?: number; text: string; range?: string }[]>([])
  const [searchMode, setSearchMode] = useState<"text" | "semantic">("text")
  const [searching, setSearching] = useState(false)

  const [inlineEdit, setInlineEdit] = useState<{
    visible: boolean
    selection: { startLineNumber: number; startColumn: number; endLineNumber: number; endColumn: number } | null
    originalCode: string
    instruction: string
    editedCode: string
    diff: string
    loading: boolean
    top: number
    left: number
  }>({ visible: false, selection: null, originalCode: "", instruction: "", editedCode: "", diff: "", loading: false, top: 0, left: 0 })

  const streamRef = useRef("")
  const traceIdRef = useRef(0)
  const terminalEndRef = useRef<HTMLDivElement>(null)
  const completionTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const completionAbort = useRef<AbortController | null>(null)
  const editorRef = useRef<unknown>(null)
  const editorContainerRef = useRef<HTMLDivElement>(null)

  const activeFile = activePath ? openFiles[activePath] ?? null : null

  const loadTree = useCallback(async () => {
    try {
      const data = await api.workspaceTree(".")
      setTreeRoot(data.root)
      setFileTree(data.tree as FileTreeNode | null)
    } catch (e) {
      console.error("Failed to load file tree:", e)
    }
  }, [])

  useEffect(() => { loadTree() }, [loadTree])

  const openFile = useCallback(async (filePath: string) => {
    if (openFiles[filePath]) {
      setActivePath(filePath)
      return
    }
    try {
      const data = await api.workspaceRead(filePath)
      if (data.error) {
        console.error("Failed to read file:", data.error)
        return
      }
      const name = fileName(filePath)
      setOpenFiles(prev => ({
        ...prev,
        [filePath]: { path: filePath, name, content: data.content, language: languageFromPath(filePath), dirty: false },
      }))
      setActivePath(filePath)
    } catch (e) {
      console.error("Failed to open file:", e)
    }
  }, [openFiles])

  const closeFile = useCallback((filePath: string) => {
    setOpenFiles(prev => {
      const copy = { ...prev }
      delete copy[filePath]
      return copy
    })
    if (activePath === filePath) {
      const remaining = Object.keys(openFiles).filter(p => p !== filePath)
      setActivePath(remaining.length > 0 ? remaining[remaining.length - 1] : null)
    }
  }, [activePath, openFiles])

  const updateFileContent = useCallback((filePath: string, content: string) => {
    setOpenFiles(prev => {
      const existing = prev[filePath]
      if (!existing) return prev
      return { ...prev, [filePath]: { ...existing, content, dirty: true } }
    })
  }, [])

  const saveFile = useCallback(async (filePath: string) => {
    const file = openFiles[filePath]
    if (!file) return
    try {
      const data = await api.workspaceWrite(filePath, file.content)
      if (data.error) {
        console.error("Save failed:", data.error)
        return
      }
      setOpenFiles(prev => ({
        ...prev,
        [filePath]: { ...prev[filePath], dirty: false },
      }))
    } catch (e) {
      console.error("Save failed:", e)
    }
  }, [openFiles])

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault()
        if (activePath && openFiles[activePath]?.dirty) {
          saveFile(activePath)
        }
      }
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [activePath, openFiles, saveFile])

  const toggleDir = useCallback((dirPath: string) => {
    setExpandedDirs(prev => {
      const next = new Set(prev)
      if (next.has(dirPath)) next.delete(dirPath)
      else next.add(dirPath)
      return next
    })
  }, [])

  const handleEditorMount = useCallback((ed: unknown, monaco: Monaco) => {
    editorRef.current = ed
    const editor = ed as {
      getModel: () => { getValue: () => string; getLanguageId?: () => string } | null
      getSelection: () => { startLineNumber: number; startColumn: number; endLineNumber: number; endColumn: number } | null
      getScrolledVisiblePosition: (pos: { lineNumber: number; column: number }) => { top: number; left: number; height: number } | undefined
      addCommand: (keybinding: number, handler: () => void) => void
    }

    monaco.languages.registerInlineCompletionsProvider("*", {
      provideInlineCompletions: async (model: unknown, position: unknown) => {
        if (completionTimer.current) clearTimeout(completionTimer.current)
        if (completionAbort.current) completionAbort.current.abort()

        const m = model as { getValue: () => string; getOffsetAt: (pos: unknown) => number; getLanguageId?: () => string }
        const pos = position as { lineNumber: number; column: number }
        const text = m.getValue()
        const offset = m.getOffsetAt(position)
        const prefix = text.slice(0, offset)
        const suffix = text.slice(offset)

        if (prefix.trim().length < 3) return { items: [] }

        const lang = m.getLanguageId?.() ?? activeFile?.language ?? ""

        await new Promise<void>(resolve => {
          completionTimer.current = setTimeout(resolve, 300)
        })

        const ctrl = new AbortController()
        completionAbort.current = ctrl

        try {
          const res = await api.completion(prefix, suffix, lang)
          if (ctrl.signal.aborted) return { items: [] }
          const completion = res.completion
          if (!completion) return { items: [] }
          return {
            items: [{ insertText: completion, range: { startLineNumber: pos.lineNumber, startColumn: pos.column, endLineNumber: pos.lineNumber, endColumn: pos.column } }],
          }
        } catch {
          return { items: [] }
        }
      },
      freeInlineCompletions() {},
    })

    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyK, () => {
      const sel = editor.getSelection()
      if (!sel || (sel.startLineNumber === sel.endLineNumber && sel.startColumn === sel.endColumn)) return
      const model = editor.getModel()
      if (!model) return
      const code = model.getValue().split("\n").slice(sel.startLineNumber - 1, sel.endLineNumber).join("\n")
      const pos = editor.getScrolledVisiblePosition({ lineNumber: sel.startLineNumber, column: sel.startColumn })
      const top = pos ? pos.top + pos.height + 4 : 60
      const left = pos ? pos.left : 60
      setInlineEdit({ visible: true, selection: sel, originalCode: code, instruction: "", editedCode: "", diff: "", loading: false, top, left })
    })
  }, [activeFile?.language])

  const submitInlineEdit = useCallback(async () => {
    if (!inlineEdit.instruction.trim() || !activeFile) return
    setInlineEdit(prev => ({ ...prev, loading: true }))
    try {
      const res = await api.inlineEdit(inlineEdit.originalCode, inlineEdit.instruction, activeFile.language)
      setInlineEdit(prev => ({ ...prev, editedCode: res.edited_code, diff: res.diff, loading: false }))
    } catch {
      setInlineEdit(prev => ({ ...prev, loading: false }))
    }
  }, [inlineEdit.instruction, inlineEdit.originalCode, activeFile])

  const acceptInlineEdit = useCallback(() => {
    if (!activeFile || !inlineEdit.selection || !inlineEdit.editedCode) return
    const editor = editorRef.current as {
      getModel: () => { getValue: () => string } | null
      executeEdits: (source: string, edits: { range: { startLineNumber: number; startColumn: number; endLineNumber: number; endColumn: number }; text: string }[]) => void
    } | null
    if (!editor) return
    const model = editor.getModel()
    if (!model) return
    const lines = model.getValue().split("\n")
    const sel = inlineEdit.selection
    const prefix = lines.slice(0, sel.startLineNumber - 1)
    const suffix = lines.slice(sel.endLineNumber)
    const firstLineIndent = lines[sel.startLineNumber - 1].slice(0, sel.startColumn - 1)
    const lastLineRemainder = lines[sel.endLineNumber - 1].slice(sel.endColumn - 1)
    const editedLines = inlineEdit.editedCode.split("\n")
    editedLines[0] = firstLineIndent + editedLines[0]
    editedLines[editedLines.length - 1] = editedLines[editedLines.length - 1] + lastLineRemainder
    const newContent = [...prefix, ...editedLines, ...suffix].join("\n")
    updateFileContent(activeFile.path, newContent)
    setInlineEdit(prev => ({ ...prev, visible: false }))
  }, [activeFile, inlineEdit.selection, inlineEdit.editedCode, updateFileContent])

  const onAgentEvent = useCallback((ev: AgentSocketEvent) => {
    const d = ev.data as Record<string, unknown>
    if (ev.type === "token") {
      streamRef.current += String(d.content ?? "")
      setOutput(streamRef.current)
      return
    }
    if (ev.type === "final") {
      const content = String(d.content ?? "")
      streamRef.current = content
      setOutput(content)
      return
    }
    if (ev.type === "error") {
      streamRef.current += `\n[error: ${String(d.message ?? "unknown")}]`
      setOutput(streamRef.current)
      return
    }
    if (ev.type === "confirm_request") {
      setPendingConfirm({
        tool: String(d.tool ?? "tool"),
        arguments: (d.arguments ?? {}) as Record<string, unknown>,
        diff: d.diff ? String(d.diff) : undefined,
      })
      return
    }
    if (ev.type === "done") {
      streamRef.current += `\n\n[done in ${String(d.steps ?? "?")} steps: ${String(d.reason ?? "finished")}]`
      setOutput(streamRef.current)
      return
    }
    if (ev.type === "step_start") {
      traceIdRef.current += 1
      setTraces((prev) => [...prev, { id: traceIdRef.current, kind: "step", text: `Step ${String(d.step ?? "")} — ${String(d.goal ?? "")}` }])
      return
    }
    if (ev.type === "tool_call") {
      let args
      try {
        args = JSON.stringify(d.args)
      } catch {
        args = String(d.args)
      }
      traceIdRef.current += 1
      setTraces((prev) => [...prev, { id: traceIdRef.current, kind: "tool_call", text: `${String(d.name ?? "tool")}(${args})` }])
    }
  }, [])

  const { connected, running, send, respond, cancel } = useAgentSocket(onAgentEvent)

  const speech = useSpeechInput()
  const speechBaseRef = useRef("")

  useEffect(() => {
    if (speech.final) {
      const base = speechBaseRef.current
      setAiPrompt(base ? `${base} ${speech.final}` : speech.final)
    }
  }, [speech.final])

  const toggleMic = useCallback(() => {
    if (speech.listening) {
      speech.stop()
    } else {
      speech.reset()
      speechBaseRef.current = aiPrompt.trim()
      speech.start()
    }
  }, [speech, aiPrompt])

  const runAgent = useCallback(() => {
    const prompt = aiPrompt.trim()
    if (!prompt) return
    streamRef.current = ""
    setOutput("")
    setTraces([])
    setTruthfulStatus("")
    setThinkingProcess("")
    const cfg = AGENT_MODE_TOOLS[agentMode]
    send(prompt, { maxSteps: cfg.maxSteps, diffPreview: cfg.diffPreview, proactiveScan: true })
  }, [aiPrompt, agentMode, send])

  async function runAI() {
    if (truthfulMode) {
      setOutput("Thinking...")
      setTruthfulStatus("")
      setThinkingProcess("")
      try {
        const data = await api.truthfulAgent(aiPrompt, activeFile?.content ?? "", "general")
        setOutput(data.content)
        setTruthfulStatus(data.status)
        setThinkingProcess(data.thinking_process)
      } catch (e) {
        console.error("Truthful agent failed:", e);
        setOutput("Truthful agent unavailable. Start with: raven services code-service")
      }
      return
    }
    if (agentMode === "general") {
      setOutput("Searching...")
      setTraces([])
      try {
        const data = await api.ideContextSearch(aiPrompt, 5)
        const results = data.results || []
        streamRef.current = results.map(r => `[${r.score.toFixed(2)}] ${r.file}\n${r.content.slice(0, 200)}`).join("\n\n")
        setOutput(streamRef.current)
      } catch (e) {
        console.error("Search failed:", e);
        setOutput("Search failed")
      }
      return
    }
    runAgent()
  }

  async function indexCodebase() {
    setIndexStatus("Indexing...")
    try {
      const data = await api.ideContextIndex(".")
      setIndexStatus(`Indexed ${data.indexed} files`)
    } catch (e) {
      console.error("Indexing failed:", e);
      setIndexStatus("Indexing failed")
    }
  }

  function submitPrompt() {
    runAI()
  }

  const approveConfirm = useCallback(() => {
    if (pendingConfirm) {
      respond({ type: "confirm", data: { approved: true } })
      setPendingConfirm(null)
    }
  }, [pendingConfirm, respond])

  const denyConfirm = useCallback(() => {
    if (pendingConfirm) {
      respond({ type: "confirm", data: { approved: false } })
      setPendingConfirm(null)
    }
  }, [pendingConfirm, respond])

  async function runTerminal() {
    if (!terminalInput.trim()) return
    const cmd = terminalInput.trim()
    setTerminalInput("")
    setTerminalHistory(h => [...h, { input: cmd, output: "Processing..." }])
    scrollTerminal()
    try {
      const data = await api.ideAgentExecute(cmd, "ide-terminal")
      setTerminalHistory(h => {
        const copy = [...h]
        copy[copy.length - 1] = { input: cmd, output: data.output || data.error || JSON.stringify(data) }
        return copy
      })
    } catch (e) {
      console.error("Terminal exec failed:", e);
      setTerminalHistory(h => {
        const copy = [...h]
        copy[copy.length - 1] = { input: cmd, output: "[agent unavailable]" }
        return copy
      })
    }
    scrollTerminal()
  }

  const scrollTerminal = useCallback(() => {
    setTimeout(() => terminalEndRef.current?.scrollIntoView({ behavior: "smooth" }), 50)
  }, [])

  const runSearch = useCallback(async () => {
    const q = searchQuery.trim()
    if (!q) return
    setSearching(true)
    try {
      if (searchMode === "semantic") {
        const data = await api.searchSemantic(q, ".")
        setSearchResults(data.results.map(r => ({ file: r.file, text: r.text, range: r.range })))
      } else {
        const data = await api.search(q, ".")
        setSearchResults(data.results.map(r => ({ file: r.file, line: r.line, text: r.text })))
      }
    } catch {
      setSearchResults([])
    } finally {
      setSearching(false)
    }
  }, [searchQuery, searchMode])

  const busy = running || !connected

  function renderTreeNode(node: FileTreeNode, depth: number): React.ReactNode {
    if (node.type === "directory") {
      const expanded = expandedDirs.has(node.path)
      return (
        <div key={node.path}>
          <div
            className="flex items-center gap-1 px-2 py-0.5 cursor-pointer text-xs text-secondary hover:bg-tertiary rounded"
            style={{ paddingLeft: `${depth * 12 + 4}px` }}
            onClick={() => toggleDir(node.path)}
          >
            {expanded ? <ChevronDown className="w-3 h-3 shrink-0" /> : <ChevronRight className="w-3 h-3 shrink-0" />}
            {expanded ? <FolderOpen className="w-3.5 h-3.5 shrink-0 text-accent" /> : <FolderClosed className="w-3.5 h-3.5 shrink-0 text-accent" />}
            <span className="truncate">{node.name}</span>
          </div>
          {expanded && node.children?.map(child => renderTreeNode(child, depth + 1))}
        </div>
      )
    }
    const isActive = activePath === node.path
    return (
      <div
        key={node.path}
        className={`flex items-center gap-1 px-2 py-0.5 cursor-pointer text-xs rounded ${isActive ? "bg-accent/20 text-primary" : "text-secondary hover:bg-tertiary"}`}
        style={{ paddingLeft: `${depth * 12 + 20}px` }}
        onClick={() => openFile(node.path)}
      >
        <FileIcon className="w-3 h-3 shrink-0" />
        <span className="truncate">{node.name}</span>
      </div>
    )
  }

  const openPaths = Object.keys(openFiles)

  return (
    <div className="grid grid-cols-[220px_1fr_320px] h-[calc(100vh-2rem)] bg-primary">
      <div className="border-r border-default flex flex-col bg-secondary overflow-hidden">
        <div className="px-3 py-1.5 text-xs font-semibold text-tertiary border-b border-default bg-tertiary flex items-center justify-between">
          <span>Explorer</span>
          <button onClick={loadTree} className="text-[10px] text-tertiary hover:text-secondary cursor-pointer border-none bg-transparent">Refresh</button>
        </div>
        <div className="flex-1 overflow-auto py-1">
          {fileTree ? renderTreeNode(fileTree, 0) : (
            <div className="px-3 py-2 text-xs text-tertiary">Loading...</div>
          )}
        </div>
        {treeRoot && (
          <div className="px-2 py-1 text-[10px] text-tertiary border-t border-default truncate" title={treeRoot}>
            {treeRoot}
          </div>
        )}
      </div>

      <div className="flex flex-col min-w-0">
        {openPaths.length > 0 && (
          <div className="flex border-b border-default bg-tertiary overflow-x-auto">
            {openPaths.map(p => {
              const f = openFiles[p]
              const isActive = p === activePath
              return (
                <div
                  key={p}
                  className={`flex items-center gap-1 px-3 py-1.5 text-xs cursor-pointer border-r border-default min-w-0 max-w-[180px] ${
                    isActive ? "bg-primary text-primary" : "bg-tertiary text-tertiary hover:text-secondary"
                  }`}
                  onClick={() => setActivePath(p)}
                >
                  <span className={`truncate ${f.dirty ? "font-semibold" : ""}`}>{f.name}</span>
                  {f.dirty && <span className="w-1.5 h-1.5 rounded-full bg-accent shrink-0" />}
                  <button
                    onClick={(e) => { e.stopPropagation(); closeFile(p) }}
                    className="ml-1 shrink-0 text-tertiary hover:text-primary cursor-pointer border-none bg-transparent p-0"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              )
            })}
          </div>
        )}

        <div className="flex-1 flex flex-col min-h-0">
          {activeFile ? (
            <>
              <div className="border-b border-default px-4 py-1 text-[11px] text-tertiary bg-tertiary truncate flex items-center justify-between">
                <span className="truncate">{activeFile.path}</span>
                {activeFile.dirty && (
                  <button onClick={() => saveFile(activeFile.path)}
                    className="ml-2 text-[10px] text-accent hover:text-primary cursor-pointer border-none bg-transparent shrink-0">
                    Save
                  </button>
                )}
              </div>
              <div className="flex-1 min-h-0 relative" ref={editorContainerRef}>
                <Editor
                  height="100%"
                  language={activeFile.language}
                  theme={theme === "dark" ? "vs-dark" : "light"}
                  value={activeFile.content}
                  onChange={(val) => updateFileContent(activeFile.path, val ?? "")}
                  onMount={handleEditorMount}
                  options={{ minimap: { enabled: false }, fontSize: 14, padding: { top: 16 }, inlineSuggest: { enabled: true } }}
                />
                {inlineEdit.visible && (
                  <div
                    className="absolute z-30 bg-tertiary border border-default rounded-lg shadow-lg p-2 flex flex-col gap-2 min-w-[320px] max-w-[480px]"
                    style={{ top: inlineEdit.top, left: inlineEdit.left }}
                  >
                    {inlineEdit.loading ? (
                      <div className="flex items-center gap-2 text-xs text-tertiary px-1 py-2">
                        <Loader2 className="w-3.5 h-3.5 animate-spin" /> Editing...
                      </div>
                    ) : inlineEdit.diff ? (
                      <>
                        <div className="text-[10px] text-tertiary px-1">Review changes</div>
                        <div className="max-h-[200px] overflow-auto font-mono text-[11px] bg-primary rounded px-2 py-1">
                          {inlineEdit.diff.split("\n").map((line, i) => (
                            <div key={i} className={
                              line.startsWith("+") ? "text-green-400" :
                              line.startsWith("-") ? "text-red-400" :
                              "text-tertiary"
                            }>{line}</div>
                          ))}
                        </div>
                        <div className="flex gap-1 justify-end">
                          <button onClick={() => setInlineEdit(prev => ({ ...prev, visible: false }))}
                            className="px-2 py-1 text-xs rounded border border-default bg-transparent text-tertiary hover:text-primary cursor-pointer">
                            Cancel
                          </button>
                          <button onClick={acceptInlineEdit}
                            className="px-2 py-1 text-xs rounded border border-accent bg-accent/10 text-accent hover:bg-accent/20 cursor-pointer">
                            Accept
                          </button>
                        </div>
                      </>
                    ) : (
                      <div className="flex items-center gap-1">
                        <span className="text-[10px] text-accent font-medium shrink-0">Edit:</span>
                        <input
                          autoFocus
                          value={inlineEdit.instruction}
                          onChange={(e) => setInlineEdit(prev => ({ ...prev, instruction: e.target.value }))}
                          onKeyDown={(e) => { if (e.key === "Enter") submitInlineEdit(); if (e.key === "Escape") setInlineEdit(prev => ({ ...prev, visible: false })) }}
                          placeholder="How should this code change?"
                          className="flex-1 px-2 py-1 text-xs bg-primary border border-default rounded text-primary placeholder:text-quaternary focus:outline-none focus:border-accent"
                        />
                        <button onClick={submitInlineEdit}
                          className="px-2 py-1 text-xs rounded border border-accent bg-accent/10 text-accent hover:bg-accent/20 cursor-pointer shrink-0">
                          Go
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-tertiary text-sm">
              Open a file from the explorer to start editing
            </div>
          )}
        </div>

        <div className="h-52 border-t border-default bg-secondary flex flex-col shrink-0">
          <div className="px-3 py-1 text-xs text-tertiary border-b border-default bg-tertiary">
            Terminal
          </div>
          <div className="flex-1 overflow-auto p-1">
            {terminalHistory.map((line, i) => (
              <div key={i} className="font-mono text-xs text-success px-2 py-0.5 whitespace-pre-wrap">
                <span className="text-tertiary">raven@ssrjkk:~$ </span>{line.input}<br />
                <span className="text-tertiary">{line.output}</span>
              </div>
            ))}
            <div ref={terminalEndRef} />
          </div>
          <div className="flex gap-1 px-2 py-1 border-t border-default">
            <input
              value={terminalInput}
              onChange={(e) => setTerminalInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runTerminal()}
              placeholder="command..."
              className="flex-1 input-base font-mono text-xs"
            />
            <button onClick={runTerminal}
              className="btn-outline" style={{ padding: "0.25rem 0.75rem", fontSize: "0.75rem" }}>
              Run
            </button>
          </div>
        </div>
      </div>

      <div className="border-l border-default flex flex-col bg-secondary relative">
        <div className="flex border-b border-default">
          <button onClick={() => setSidebarTab("ai")}
            className={`flex items-center gap-1.5 flex-1 px-3 py-2 border-none cursor-pointer text-xs font-medium transition ${
              sidebarTab === "ai" ? "bg-primary text-primary" : "bg-transparent text-tertiary hover:text-secondary"
            }`}>
            <Bot className="w-3.5 h-3.5" /> AI
          </button>
          <button onClick={() => setSidebarTab("debug")}
            className={`flex items-center gap-1.5 flex-1 px-3 py-2 border-none cursor-pointer text-xs font-medium transition ${
              sidebarTab === "debug" ? "bg-primary text-primary" : "bg-transparent text-tertiary hover:text-secondary"
            }`}>
            <Bug className="w-3.5 h-3.5" /> Debug
          </button>
          <button onClick={() => setSidebarTab("search")}
            className={`flex items-center gap-1.5 flex-1 px-3 py-2 border-none cursor-pointer text-xs font-medium transition ${
              sidebarTab === "search" ? "bg-primary text-primary" : "bg-transparent text-tertiary hover:text-secondary"
            }`}>
            <Search className="w-3.5 h-3.5" /> Search
          </button>
        </div>

        {sidebarTab === "ai" ? (
          <>
            <div className="p-3 border-b border-default flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold">AI Agent</div>
                <div className="flex items-center gap-1.5 text-[10px] text-tertiary">
                  <span className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-green-400" : "bg-red-400"}`} />
                  {connected ? (running ? "working" : "idle") : "offline"}
                </div>
              </div>
              <div className="flex gap-1">
                {AGENT_MODES.map(m => (
                  <button key={m.value} onClick={() => setAgentMode(m.value)} disabled={running}
                    className={`text-xs px-2.5 py-1 rounded border-none cursor-pointer transition ${
                      agentMode === m.value
                        ? "bg-accent text-white font-semibold"
                        : "bg-tertiary text-secondary hover:bg-accent-muted"
                    } ${running ? "opacity-50" : ""}`}
                    title={m.desc}>
                    {m.label}
                  </button>
                ))}
              </div>
              <div className="text-[10px] text-tertiary">{AGENT_MODES.find(m => m.value === agentMode)?.desc}</div>
              <button onClick={() => setTruthfulMode(v => !v)}
                className={`flex items-center justify-center gap-1.5 text-xs px-2.5 py-1.5 rounded border-none cursor-pointer transition ${
                  truthfulMode
                    ? "bg-accent-muted text-accent font-semibold"
                    : "bg-tertiary text-tertiary hover:bg-accent-muted"
                }`}>
                <span className={`w-1.5 h-1.5 rounded-full ${truthfulMode ? "bg-accent" : "bg-tertiary"}`} />
                Truthful mode (Chain-of-Verification)
              </button>
            </div>

            <div className="flex-1 p-3 overflow-auto flex flex-col gap-3">
              {truthfulStatus && (
                <div className="flex items-center gap-2">
                  <span className={TRUTHFUL_STATUS[truthfulStatus]?.color ?? "badge badge-accent"}>
                    {TRUTHFUL_STATUS[truthfulStatus]?.label ?? truthfulStatus}
                  </span>
                </div>
              )}
              {output && (
                <div className="card p-3 text-sm leading-relaxed text-secondary whitespace-pre-wrap">
                  {output}
                </div>
              )}
              {traces.length > 0 && (
                <div className="card p-3 flex flex-col gap-1.5">
                  <div className="text-[10px] text-accent uppercase tracking-wider">Agent trace</div>
                  {traces.map(t => (
                    <div key={t.id} className={`font-mono text-xs whitespace-pre-wrap ${t.kind === "tool_call" ? "text-accent" : "text-tertiary"}`}>
                      {t.text}
                    </div>
                  ))}
                </div>
              )}
              {running && (
                <div className="flex items-center gap-2 text-sm text-secondary">
                  <Loader2 className="h-4 w-4 animate-spin text-accent" />
                  Agent is working…
                </div>
              )}
              {thinkingProcess && (
                <details className="card p-3">
                  <summary className="text-[10px] text-accent cursor-pointer uppercase tracking-wider">
                    Verification thinking
                  </summary>
                  <pre className="text-xs text-tertiary whitespace-pre-wrap mt-2 font-mono">{thinkingProcess}</pre>
                </details>
              )}
              {indexStatus && (
                <div className="text-xs text-tertiary">{indexStatus}</div>
              )}
            </div>

            <div className="p-3 border-t border-default flex flex-col gap-2">
              <div className="flex gap-2">
                <input
                  value={aiPrompt}
                  onChange={(e) => setAiPrompt(e.target.value)}
                  placeholder={speech.listening ? (speech.interim || "Listening…") : "Ask AI to build anything..."}
                  className="flex-1 input-base"
                  onKeyDown={(e) => e.key === "Enter" && submitPrompt()}
                  disabled={running}
                />
                {speech.supported && (
                  <button onClick={toggleMic} disabled={running}
                    title={speech.listening ? "Stop voice input" : "Dictate prompt"}
                    className={`flex items-center justify-center rounded px-2.5 ${speech.listening ? "bg-accent text-white" : "bg-tertiary text-secondary hover:bg-accent-muted"} ${running ? "opacity-50" : ""}`}>
                    {speech.listening ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
                  </button>
                )}
                {running ? (
                  <button onClick={cancel}
                    className="flex items-center gap-1 px-3 py-1.5 rounded border-none cursor-pointer text-xs font-semibold bg-red-600 hover:bg-red-700 text-white transition">
                    <Square className="w-3 h-3" /> Stop
                  </button>
                ) : (
                  <button onClick={submitPrompt} disabled={busy}
                    className="btn-primary">
                    {truthfulMode ? "Verify" : agentMode === "general" ? "Search" : "Run"}
                  </button>
                )}
              </div>
              {speech.error && (
                <div className="text-[10px] text-amber-400">Voice input error: {speech.error}</div>
              )}
              <div className="flex gap-1">
                <button onClick={indexCodebase}
                  className="btn-outline" style={{ padding: "0.25rem 0.75rem", fontSize: "0.75rem" }}>
                  Index
                </button>
              </div>
            </div>
          </>
        ) : sidebarTab === "search" ? (
          <div className="p-3 flex flex-col gap-2 flex-1 overflow-hidden">
            <div className="flex gap-1">
              <button onClick={() => setSearchMode("text")}
                className={`flex-1 px-2 py-1 text-xs rounded border ${searchMode === "text" ? "bg-primary text-accent border-accent" : "bg-transparent text-tertiary border-default"}`}>
                Text
              </button>
              <button onClick={() => setSearchMode("semantic")}
                className={`flex-1 px-2 py-1 text-xs rounded border ${searchMode === "semantic" ? "bg-primary text-accent border-accent" : "bg-transparent text-tertiary border-default"}`}>
                Semantic
              </button>
            </div>
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") runSearch() }}
              placeholder="Search..."
              className="w-full px-2 py-1.5 text-xs bg-primary border border-default rounded text-primary placeholder:text-quaternary focus:outline-none focus:border-accent"
            />
            {searching && <div className="text-[10px] text-tertiary">Searching...</div>}
            <div className="flex-1 overflow-auto flex flex-col gap-1">
              {searchResults.map((r, i) => (
                <button key={i}
                  onClick={() => r.file && openFile(r.file)}
                  className="text-left px-2 py-1 text-xs rounded hover:bg-primary/50 cursor-pointer border-none bg-transparent">
                  <div className="text-accent font-mono truncate">
                    {r.file}{r.line ? `:${r.line}` : ""}{r.range ? `:${r.range}` : ""}
                  </div>
                  <div className="text-tertiary truncate">{r.text}</div>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <DebugPanel />
        )}

        {pendingConfirm && (
          <div className="absolute inset-0 z-20 bg-black/50 flex items-center justify-center p-4">
            <div className="card p-4 w-full max-w-lg bg-tertiary max-h-[80vh] flex flex-col">
              <div className="flex items-center gap-2 text-sm font-semibold text-primary mb-2">
                <ShieldAlert className="h-4 w-4 text-amber-400" />
                {pendingConfirm.diff ? "Review changes" : "Allow tool?"}
              </div>
              <div className="text-xs text-secondary mb-1">
                {pendingConfirm.diff ? "The agent wants to edit:" : "The agent wants to run:"}
              </div>
              <div className="font-mono text-xs text-accent mb-3 bg-primary rounded px-2 py-1.5 break-all">
                {pendingConfirm.tool}
                {pendingConfirm.arguments.path ? ` — ${String(pendingConfirm.arguments.path)}` : null}
              </div>
              {pendingConfirm.diff ? (
                <div className="font-mono text-[11px] bg-primary rounded px-2 py-1.5 overflow-auto flex-1 min-h-0 mb-4 border border-default">
                  {pendingConfirm.diff.split("\n").map((line, i) => {
                    if (line.startsWith("+") && !line.startsWith("+++")) return <div key={i} className="bg-green-900/30 text-green-300">{line}</div>
                    if (line.startsWith("-") && !line.startsWith("---")) return <div key={i} className="bg-red-900/30 text-red-300">{line}</div>
                    if (line.startsWith("@@")) return <div key={i} className="text-blue-400">{line}</div>
                    return <div key={i} className="text-tertiary">{line}</div>
                  })}
                </div>
              ) : (
                <div className="font-mono text-[10px] text-tertiary mb-4 bg-primary rounded px-2 py-1.5 whitespace-pre-wrap max-h-28 overflow-auto">
                  {JSON.stringify(pendingConfirm.arguments, null, 2)}
                </div>
              )}
              <div className="flex gap-2">
                <button onClick={denyConfirm}
                  className="btn-outline flex-1">
                  Deny
                </button>
                <button onClick={approveConfirm}
                  className="btn-primary flex-1">
                  Allow
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
