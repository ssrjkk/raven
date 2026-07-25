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
    <div className="h-full flex flex-col text-xs font-mono bg-[#0d0d0d] text-gray-300">
      <div className="px-3 py-1.5 text-xs text-gray-500 border-b border-[#222] bg-[#252526] flex items-center justify-between">
        <span>Debugger</span>
        {sessionActive && <span className={`w-2 h-2 rounded-full ${isPaused ? "bg-yellow-400" : "bg-green-500"}`} />}
      </div>

      <div className="px-2 py-1.5 border-b border-[#222] flex gap-1 items-center">
        {!sessionActive ? (
          <div className="flex gap-1 w-full">
            <input
              value={file}
              onChange={e => setFile(e.target.value)}
              placeholder="file.py"
              className="flex-1 bg-[#1a1a1a] border border-[#333] rounded px-2 py-1 text-xs outline-none text-gray-100"
              onKeyDown={e => e.key === "Enter" && startSession()}
            />
            <button onClick={startSession}
              className="flex items-center gap-1 bg-green-800 hover:bg-green-700 text-white border-none rounded px-2 py-1 cursor-pointer text-xs transition">
              <Play className="w-3 h-3" /> Start
            </button>
          </div>
        ) : (
          <>
            <button onClick={resume} disabled={!isPaused}
              className="flex items-center gap-1 bg-[#333] hover:bg-[#444] disabled:opacity-30 disabled:cursor-not-allowed text-white border-none rounded px-2 py-1 cursor-pointer text-xs transition">
              <Play className="w-3 h-3" /> Cont
            </button>
            <button onClick={stepOver} disabled={!isPaused}
              className="flex items-center gap-1 bg-[#333] hover:bg-[#444] disabled:opacity-30 disabled:cursor-not-allowed text-white border-none rounded px-2 py-1 cursor-pointer text-xs transition">
              <SkipForward className="w-3 h-3" /> Over
            </button>
            <button onClick={stepInto} disabled={!isPaused}
              className="flex items-center gap-1 bg-[#333] hover:bg-[#444] disabled:opacity-30 disabled:cursor-not-allowed text-white border-none rounded px-2 py-1 cursor-pointer text-xs transition">
              <CornerDownRight className="w-3 h-3" /> Into
            </button>
            <button onClick={stopSession}
              className="flex items-center gap-1 bg-red-900 hover:bg-red-800 text-white border-none rounded px-2 py-1 cursor-pointer text-xs transition ml-auto">
              <Square className="w-3 h-3" /> Stop
            </button>
          </>
        )}
      </div>

      {!sessionActive && (
        <div className="px-2 py-1.5 border-b border-[#222]">
          <div className="text-[10px] text-gray-500 mb-1">Breakpoints</div>
          {breakpoints.map((bp, i) => (
            <div key={i} className="flex items-center gap-1 py-0.5">
              <span className="text-gray-400">{bp.file}:{bp.line}</span>
              <button onClick={() => removeBreakpoint(i)} className="text-red-500 hover:text-red-400 border-none bg-transparent cursor-pointer p-0 leading-none">x</button>
            </div>
          ))}
          <div className="flex gap-1 mt-1">
            <input value={bpFile} onChange={e => setBpFile(e.target.value)} placeholder="file.py"
              className="flex-1 bg-[#1a1a1a] border border-[#333] rounded px-1.5 py-0.5 text-[10px] outline-none text-gray-100" />
            <input value={bpLine} onChange={e => setBpLine(e.target.value)} placeholder="line"
              className="w-14 bg-[#1a1a1a] border border-[#333] rounded px-1.5 py-0.5 text-[10px] outline-none text-gray-100"
              onKeyDown={e => e.key === "Enter" && addBreakpoint()} />
            <button onClick={addBreakpoint}
              className="bg-[#333] hover:bg-[#444] text-white border-none rounded px-1.5 py-0.5 cursor-pointer text-[10px] transition">+</button>
          </div>
        </div>
      )}

      {isPaused && (
        <div className="flex-1 overflow-auto">
          <div className="px-2 py-1 text-[10px] text-gray-500 border-b border-[#222] uppercase tracking-wider">Call Stack</div>
          <div className="border-b border-[#222]">
            {state?.frames?.map((frame, i) => (
              <button key={i} onClick={() => setSelectedFrame(i)}
                className={`w-full text-left px-2 py-1 border-none cursor-pointer text-[11px] font-mono transition ${
                  i === selectedFrame ? "bg-blue-900/40 text-blue-300" : "bg-transparent text-gray-400 hover:bg-[#1a1a1a]"
                }`}>
                <span className="text-gray-500">#{(state.frames?.length ?? 1) - 1 - i}</span>{" "}
                <span className="text-blue-400">{frame.function}</span>
                <br />
                <span className="text-gray-600 ml-3">{frame.filename}:{frame.line}</span>
              </button>
            ))}
            {(!state?.frames || state.frames.length === 0) && (
              <div className="px-2 py-1 text-gray-600 italic text-[10px]">No frames</div>
            )}
          </div>

          <div className="px-2 py-1 text-[10px] text-gray-500 uppercase tracking-wider">Variables</div>
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
                          className="bg-transparent border-none cursor-pointer p-0 text-gray-500 hover:text-gray-300">
                          {isExpanded ? <ChevronDown className="w-2.5 h-2.5" /> : <ChevronRight className="w-2.5 h-2.5" />}
                        </button>
                      )}
                      <span className="text-purple-400">{key}</span>
                      <span className="text-gray-600">=</span>
                      {isObject && isExpanded ? (
                        <pre className="text-[10px] text-gray-400 whitespace-pre-wrap break-all ml-4">{val}</pre>
                      ) : (
                        <span className="text-gray-400 truncate max-w-[200px] block">{val}</span>
                      )}
                    </div>
                  </div>
                )
              })
            ) : (
              <div className="px-2 py-1 text-gray-600 italic text-[10px]">No variables</div>
            )}
          </div>

          <div className="mt-2 px-2 py-1 bg-yellow-900/20 border-t border-yellow-900/50">
            <div className="text-[10px] text-yellow-500">
              Paused at {state?.paused_file}:{state?.paused_line}
            </div>
          </div>
        </div>
      )}

      {state?.error && (
        <div className="px-2 py-1 bg-red-900/30 border-t border-red-900/50">
          <pre className="text-[10px] text-red-400 whitespace-pre-wrap">{state.error}</pre>
        </div>
      )}
    </div>
  )
}
