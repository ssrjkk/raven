import { ChevronDown, ChevronRight,CornerDownRight, Play, SkipForward, Square } from "lucide-react"
import { useEffect, useRef,useState } from "react"

import { api, type DebugState } from "../api/client"

interface BreakpointEntry {
  file: string
  line: number
  enabled: boolean
}

export default function DebugPanel() {
  const [sessionActive, setSessionActive] = useState(false)
  const [state, setState] = useState<DebugState | null>(null)
  const [selectedFrame, setSelectedFrame] = useState<number>(0)
  const [expandedVars, setExpandedVars] = useState<Set<string>>(new Set())
  const [file, setFile] = useState("")
  const [breakpoints, setBreakpoints] = useState<BreakpointEntry[]>([])
  const [bpFile, setBpFile] = useState("")
  const [bpLine, setBpLine] = useState("")
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  useEffect(() => {
    return () => stopPolling()
  }, [])

  function startPolling() {
    stopPolling()
    pollRef.current = setInterval(async () => {
      try {
        const s = await api.debugState()
        setState(s)
        if (s.status === "running" || s.status === "stopped" || s.status === "error") {
          stopPolling()
          setSessionActive(false)
        }
      } catch (e) {
        console.error("debug poll:", e)
        stopPolling()
      }
    }, 500)
  }

  async function startSession() {
    if (!file.trim()) return
    try {
      const res = await api.debugStart(file.trim(), breakpoints)
      setState(res)
      setSessionActive(true)
      setSelectedFrame(0)
      if (res.status === "paused") startPolling()
    } catch (e) {
      console.error("debug start:", e)
    }
  }

  async function stopSession() {
    stopPolling()
    try {
      await api.debugStop()
    } catch (e) {
      console.error("debug stop:", e)
    }
    setSessionActive(false)
    setState(null)
  }

  async function stepOver() {
    try {
      const res = await api.debugStepOver()
      setState(res)
      setSelectedFrame(0)
      if (res.status === "paused") startPolling()
    } catch (e) {
      console.error("step over:", e)
    }
  }

  async function stepInto() {
    try {
      const res = await api.debugStepInto()
      setState(res)
      setSelectedFrame(0)
      if (res.status === "paused") startPolling()
    } catch (e) {
      console.error("step into:", e)
    }
  }

  async function resume() {
    try {
      const res = await api.debugContinue()
      setState(res)
      if (res.status === "paused") startPolling()
    } catch (e) {
      console.error("continue:", e)
    }
  }

  async function addBreakpoint() {
    if (!bpFile.trim() || !bpLine.trim()) return
    const line = parseInt(bpLine, 10)
    if (isNaN(line)) return
    const newBp: BreakpointEntry = { file: bpFile.trim(), line, enabled: true }
    setBreakpoints(prev => [...prev, newBp])
    setBpLine("")
  }

  function removeBreakpoint(index: number) {
    setBreakpoints(prev => prev.filter((_, i) => i !== index))
  }

  function toggleVar(key: string) {
    setExpandedVars(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const isPaused = state?.status === "paused"
  const currentFrame = state?.frames?.[selectedFrame]

  return (
    <div className="h-full flex flex-col text-xs font-mono bg-primary text-secondary">
      <div className="px-3 py-1.5 text-xs text-tertiary border-b border-default bg-tertiary flex items-center justify-between">
        <span>Debugger</span>
        {sessionActive && <span className={`w-2 h-2 rounded-full ${isPaused ? "bg-[var(--dt-colors-status-warning)]" : "bg-[var(--dt-colors-status-success)]"}`} />}
      </div>

      <div className="px-2 py-1.5 border-b border-default flex gap-1 items-center">
        {!sessionActive ? (
          <div className="flex gap-1 w-full">
            <input
              value={file}
              onChange={e => setFile(e.target.value)}
              placeholder="file.py"
              className="flex-1 bg-secondary border border-default rounded px-2 py-1 text-xs outline-none text-primary"
              onKeyDown={e => e.key === "Enter" && startSession()}
            />
            <button onClick={startSession}
              className="flex items-center gap-1 text-white bg-[var(--dt-colors-status-success)] hover:brightness-110 border-none rounded px-2 py-1 cursor-pointer text-xs transition">
              <Play className="w-3 h-3" /> Start
            </button>
          </div>
        ) : (
          <>
            <button onClick={resume} disabled={!isPaused}
              className="flex items-center gap-1 bg-tertiary hover:bg-[var(--dt-colors-bg-hover)] disabled:opacity-30 disabled:cursor-not-allowed text-primary border-none rounded px-2 py-1 cursor-pointer text-xs transition">
              <Play className="w-3 h-3" /> Cont
            </button>
            <button onClick={stepOver} disabled={!isPaused}
              className="flex items-center gap-1 bg-tertiary hover:bg-[var(--dt-colors-bg-hover)] disabled:opacity-30 disabled:cursor-not-allowed text-primary border-none rounded px-2 py-1 cursor-pointer text-xs transition">
              <SkipForward className="w-3 h-3" /> Over
            </button>
            <button onClick={stepInto} disabled={!isPaused}
              className="flex items-center gap-1 bg-tertiary hover:bg-[var(--dt-colors-bg-hover)] disabled:opacity-30 disabled:cursor-not-allowed text-primary border-none rounded px-2 py-1 cursor-pointer text-xs transition">
              <CornerDownRight className="w-3 h-3" /> Into
            </button>
            <button onClick={stopSession}
              className="flex items-center gap-1 text-white bg-[var(--dt-colors-status-error)] hover:brightness-110 border-none rounded px-2 py-1 cursor-pointer text-xs transition ml-auto">
              <Square className="w-3 h-3" /> Stop
            </button>
          </>
        )}
      </div>

      {!sessionActive && (
        <div className="px-2 py-1.5 border-b border-default">
          <div className="text-[10px] text-tertiary mb-1">Breakpoints</div>
          {breakpoints.map((bp, i) => (
            <div key={i} className="flex items-center gap-1 py-0.5">
              <span className="text-secondary">{bp.file}:{bp.line}</span>
              <button onClick={() => removeBreakpoint(i)} className="text-danger hover:brightness-110 border-none bg-transparent cursor-pointer p-0 leading-none">x</button>
            </div>
          ))}
          <div className="flex gap-1 mt-1">
            <input value={bpFile} onChange={e => setBpFile(e.target.value)} placeholder="file.py"
              className="flex-1 bg-secondary border border-default rounded px-1.5 py-0.5 text-[10px] outline-none text-primary" />
            <input value={bpLine} onChange={e => setBpLine(e.target.value)} placeholder="line"
              className="w-14 bg-secondary border border-default rounded px-1.5 py-0.5 text-[10px] outline-none text-primary"
              onKeyDown={e => e.key === "Enter" && addBreakpoint()} />
            <button onClick={addBreakpoint}
              className="bg-tertiary hover:bg-[var(--dt-colors-bg-hover)] text-primary border-none rounded px-1.5 py-0.5 cursor-pointer text-[10px] transition">+</button>
          </div>
        </div>
      )}

      {isPaused && (
        <div className="flex-1 overflow-auto">
          <div className="px-2 py-1 text-[10px] text-tertiary border-b border-default uppercase tracking-wider">Call Stack</div>
          <div className="border-b border-default">
            {state?.frames?.map((frame, i) => (
              <button key={i} onClick={() => setSelectedFrame(i)}
                className={`w-full text-left px-2 py-1 border-none cursor-pointer text-[11px] font-mono transition ${
                  i === selectedFrame ? "bg-accent-muted text-accent" : "bg-transparent text-secondary hover:bg-secondary"
                }`}>
                <span className="text-tertiary">#{(state.frames?.length ?? 1) - 1 - i}</span>{" "}
                <span className="text-accent">{frame.function}</span>
                <br />
                <span className="text-tertiary ml-3">{frame.filename}:{frame.line}</span>
              </button>
            ))}
            {(!state?.frames || state.frames.length === 0) && (
              <div className="px-2 py-1 text-tertiary italic text-[10px]">No frames</div>
            )}
          </div>

          <div className="px-2 py-1 text-[10px] text-tertiary uppercase tracking-wider">Variables</div>
          <div className="px-1">
            {currentFrame?.locals && Object.keys(currentFrame.locals).length > 0 ? (
              Object.entries(currentFrame.locals).map(([key, val]) => {
                const isExpanded = expandedVars.has(key)
                const isObject = val.startsWith("{") || val.startsWith("[") || val.length > 60
                return (
                  <div key={key} className="py-0.5">
                    <div className="flex items-start gap-1">
                      {isObject && (
                        <button onClick={() => toggleVar(key)}
                          className="bg-transparent border-none cursor-pointer p-0 text-tertiary hover:text-secondary">
                          {isExpanded ? <ChevronDown className="w-2.5 h-2.5" /> : <ChevronRight className="w-2.5 h-2.5" />}
                        </button>
                      )}
                      <span className="text-accent">{key}</span>
                      <span className="text-tertiary">=</span>
                      {isObject && isExpanded ? (
                        <pre className="text-[10px] text-secondary whitespace-pre-wrap break-all ml-4">{val}</pre>
                      ) : (
                        <span className="text-secondary truncate max-w-[200px] block">{val}</span>
                      )}
                    </div>
                  </div>
                )
              })
            ) : (
              <div className="px-2 py-1 text-tertiary italic text-[10px]">No variables</div>
            )}
          </div>

          <div className="mt-2 px-2 py-1 bg-warning-muted border-t border-[var(--dt-colors-status-warning)]">
            <div className="text-[10px] text-warning">
              Paused at {state?.paused_file}:{state?.paused_line}
            </div>
          </div>
        </div>
      )}

      {state?.error && (
        <div className="px-2 py-1 bg-danger-muted border-t border-[var(--dt-colors-status-error)]">
          <pre className="text-[10px] text-danger whitespace-pre-wrap">{state.error}</pre>
        </div>
      )}
    </div>
  )
}
