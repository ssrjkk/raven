import { useMutation } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { api } from "../api/client";

type Tab = "generate" | "edit" | "analyze" | "documents" | "video" | "upload";

export default function Media() {
  const [tab, setTab] = useState<Tab>("generate");
  const [error, setError] = useState("");

  // generate
  const [prompt, setPrompt] = useState("");
  const [imageUrl, setImageUrl] = useState("");

  // edit
  const [editPath, setEditPath] = useState("");
  const [editResize, setEditResize] = useState("");
  const [editCrop, setEditCrop] = useState("");
  const [editRotate, setEditRotate] = useState("0");
  const [editFlip, setEditFlip] = useState("");
  const [editFormat, setEditFormat] = useState("");
  const [editQuality, setEditQuality] = useState("85");
  const [editResult, setEditResult] = useState("");

  // analyze
  const [analyzePath, setAnalyzePath] = useState("");
  const [analyzePrompt, setAnalyzePrompt] = useState("Describe this image in detail");
  const [analyzeResult, setAnalyzeResult] = useState("");

  // documents
  const [docPath, setDocPath] = useState("");
  const [docPages, setDocPages] = useState("");
  const [docText, setDocText] = useState("");
  const [docMeta, setDocMeta] = useState<Record<string, unknown> | null>(null);

  // video
  const [videoPath, setVideoPath] = useState("");
  const [videoAction, setVideoAction] = useState("info");
  const [videoTime, setVideoTime] = useState("1.0");
  const [videoSize, setVideoSize] = useState("320x240");
  const [videoInterval, setVideoInterval] = useState("5.0");
  const [videoMaxFrames, setVideoMaxFrames] = useState("10");
  const [videoLang, setVideoLang] = useState("");
  const [videoResult, setVideoResult] = useState("");

  // upload
  const [uploadResult, setUploadResult] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const btnStyle = { backgroundColor: "var(--dt-colors-accent-muted)", color: "var(--dt-colors-accent-default)" };
  const inputStyle: React.CSSProperties = {
    backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)",
    color: "var(--dt-colors-text-primary)", width: "100%", padding: "8px 12px", borderRadius: "6px",
    border: "1px solid", fontSize: "14px", boxSizing: "border-box" as const,
  };

  const generateMutation = useMutation({
    mutationFn: () => api.mediaGenerate(prompt),
    onSuccess: (r) => { if (r.error) setError(r.error); else setImageUrl(r.url); setError(""); },
    onError: (e: any) => setError(e.message || "Generation failed"),
  });

  const editMutation = useMutation({
    mutationFn: () => api.mediaProcess(editPath, {
      resize: editResize || undefined,
      crop: editCrop || undefined,
      rotate: parseInt(editRotate) || 0,
      flip: editFlip || undefined,
      output_format: editFormat || undefined,
      quality: parseInt(editQuality) || 85,
    }),
    onSuccess: (r) => { setEditResult(JSON.stringify(r, null, 2)); setError(""); },
    onError: (e: any) => setError(e.message || "Edit failed"),
  });

  const analyzeMutation = useMutation({
    mutationFn: () => api.mediaAnalyze(analyzePath, analyzePrompt),
    onSuccess: (d) => { setAnalyzeResult(d.result || JSON.stringify(d)); setError(""); },
    onError: (e: any) => setError(e.message || "Analysis failed"),
  });

  const videoMutation = useMutation({
    mutationFn: () => {
      switch (videoAction) {
        case "info": return api.mediaVideoInfo(videoPath);
        case "thumbnail": return api.mediaVideoThumbnail(videoPath, parseFloat(videoTime) || 1, videoSize);
        case "transcribe": return api.mediaVideoTranscribe(videoPath, videoLang || undefined);
        case "frames": return api.mediaVideoExtractFrames(videoPath, parseFloat(videoInterval) || 5, parseInt(videoMaxFrames) || 10, videoSize);
        default: return api.mediaVideoInfo(videoPath);
      }
    },
    onSuccess: (d) => {
      if (d) setVideoResult(typeof d.result === "string" ? d.result : JSON.stringify(d, null, 2));
      setError("");
    },
    onError: (e: any) => setError(e.message || "Video action failed"),
  });

  const parseMutation = useMutation({
    mutationFn: () => api.mediaParse(docPath, docPages || undefined),
    onSuccess: (r) => {
      setDocText(r.text); setDocMeta(r.metadata); setError("");
      if (r.truncated) setError("Output truncated to 50000 chars");
    },
    onError: (e: any) => setError(e.message || "Parse failed"),
  });

  async function handleUpload() {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setError(""); setUploadResult("");
    try {
      const r = await api.mediaUpload(file);
      setUploadResult(JSON.stringify(r, null, 2));
    } catch (e: any) {
      setError(e.message || "Upload failed");
    }
  }

  const TABS = [
    { key: "generate" as const, label: "Generate" },
    { key: "edit" as const, label: "Edit" },
    { key: "analyze" as const, label: "Analyze" },
    { key: "documents" as const, label: "Documents" },
    { key: "video" as const, label: "Video" },
    { key: "upload" as const, label: "Upload" },
  ];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-primary">Media</h1>

      {error && (
        <div className="px-4 py-2 rounded text-sm bg-danger-subtle text-danger">
          {error}
          <button onClick={() => setError("")} className="ml-3 text-xs text-tertiary">dismiss</button>
        </div>
      )}

      <div className="flex gap-1 border-b flex-wrap border-default">
        {TABS.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className="px-4 py-2 text-sm font-medium transition rounded-t"
            style={{
              color: tab === t.key ? "var(--dt-colors-accent-default)" : "var(--dt-colors-text-secondary)",
              borderBottom: tab === t.key ? "2px solid var(--dt-colors-accent-default)" : "2px solid transparent",
            }}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "generate" && (
        <div className="space-y-4 max-w-2xl">
          <textarea style={inputStyle} rows={3} placeholder="Describe the image to generate..." value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          <div className="flex gap-2 items-center">
            <button onClick={() => generateMutation.mutate()} disabled={generateMutation.isPending || !prompt}
              className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-40" style={btnStyle}>
              {generateMutation.isPending ? "Generating..." : "Generate Image"}
            </button>
          </div>
          {imageUrl && (
            <div className="rounded overflow-hidden border border-default">
              <img src={imageUrl} alt="Generated" className="w-full" />
            </div>
          )}
        </div>
      )}

      {tab === "edit" && (
        <div className="space-y-4 max-w-2xl">
          <p className="text-sm text-tertiary">Apply transformations to an image file.</p>
          <input style={inputStyle} placeholder="File path (e.g. /path/to/image.jpg)" value={editPath} onChange={(e) => setEditPath(e.target.value)} />
          <div className="grid grid-cols-2 gap-3">
            <input style={inputStyle} placeholder="Resize (e.g. 800x600)" value={editResize} onChange={(e) => setEditResize(e.target.value)} />
            <input style={inputStyle} placeholder="Crop (left,upper,right,lower)" value={editCrop} onChange={(e) => setEditCrop(e.target.value)} />
            <input style={inputStyle} placeholder="Rotate (degrees)" type="number" value={editRotate} onChange={(e) => setEditRotate(e.target.value)} />
            <select style={inputStyle} value={editFlip} onChange={(e) => setEditFlip(e.target.value)}>
              <option value="">No flip</option>
              <option value="horizontal">Flip horizontal</option>
              <option value="vertical">Flip vertical</option>
            </select>
            <select style={inputStyle} value={editFormat} onChange={(e) => setEditFormat(e.target.value)}>
              <option value="">Keep original</option>
              <option value="png">PNG</option>
              <option value="jpeg">JPEG</option>
              <option value="webp">WebP</option>
              <option value="gif">GIF</option>
            </select>
            <input style={inputStyle} placeholder="Quality (1-100)" type="number" min="1" max="100" value={editQuality} onChange={(e) => setEditQuality(e.target.value)} />
          </div>
          <button onClick={() => editMutation.mutate()} disabled={editMutation.isPending || !editPath}
            className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-40" style={btnStyle}>
            {editMutation.isPending ? "Processing..." : "Apply Edits"}
          </button>
          {editResult && (
            <pre className="p-3 rounded border text-xs overflow-auto card-bordered text-primary">
              {editResult}
            </pre>
          )}
        </div>
      )}

      {tab === "analyze" && (
        <div className="space-y-4 max-w-2xl">
          <p className="text-sm text-tertiary">Analyze an image using GPT-4o Vision.</p>
          <input style={inputStyle} placeholder="File path to image" value={analyzePath} onChange={(e) => setAnalyzePath(e.target.value)} />
          <textarea style={inputStyle} rows={2} placeholder="Prompt (e.g., Describe this image in detail)" value={analyzePrompt} onChange={(e) => setAnalyzePrompt(e.target.value)} />
          <button onClick={() => analyzeMutation.mutate()} disabled={analyzeMutation.isPending || !analyzePath}
            className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-40" style={btnStyle}>
            {analyzeMutation.isPending ? "Analyzing..." : "Analyze Image"}
          </button>
          {analyzeResult && (
            <div className="p-3 rounded border text-sm whitespace-pre-wrap card-bordered text-primary">
              {analyzeResult}
            </div>
          )}
        </div>
      )}

      {tab === "documents" && (
        <div className="space-y-4 max-w-2xl">
          <input style={inputStyle} placeholder="File path (e.g. /path/to/document.pdf)" value={docPath} onChange={(e) => setDocPath(e.target.value)} />
          <input style={inputStyle} placeholder="Pages (PDF only, e.g. 1-3,5 РІР‚вЂќ leave empty for all)" value={docPages} onChange={(e) => setDocPages(e.target.value)} />
          <button onClick={() => parseMutation.mutate()} disabled={parseMutation.isPending || !docPath}
            className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-40" style={btnStyle}>
            {parseMutation.isPending ? "Parsing..." : "Parse Document"}
          </button>
          {docMeta && (
            <div className="p-3 rounded border text-xs card-bordered text-tertiary">
              Metadata: {JSON.stringify(docMeta)}
            </div>
          )}
          {docText && (
            <pre className="p-3 rounded border text-xs overflow-auto max-h-96 whitespace-pre-wrap card-bordered text-primary">
              {docText}
            </pre>
          )}
        </div>
      )}

      {tab === "video" && (
        <div className="space-y-4 max-w-2xl">
          <div className="flex gap-2 items-center flex-wrap">
            <select style={{ ...inputStyle, width: "auto" }} value={videoAction} onChange={(e) => setVideoAction(e.target.value)}>
              <option value="info">Get Info</option>
              <option value="thumbnail">Thumbnail</option>
              <option value="transcribe">Transcribe</option>
              <option value="frames">Extract Frames</option>
            </select>
          </div>
          <input style={inputStyle} placeholder="File path to video" value={videoPath} onChange={(e) => setVideoPath(e.target.value)} />
          {videoAction === "thumbnail" && (
            <div className="grid grid-cols-2 gap-3">
              <input style={inputStyle} placeholder="Timestamp (seconds)" type="number" value={videoTime} onChange={(e) => setVideoTime(e.target.value)} />
              <input style={inputStyle} placeholder="Size (e.g. 320x240)" value={videoSize} onChange={(e) => setVideoSize(e.target.value)} />
            </div>
          )}
          {videoAction === "transcribe" && (
            <input style={inputStyle} placeholder="Language code (optional, e.g. en)" value={videoLang} onChange={(e) => setVideoLang(e.target.value)} />
          )}
          {videoAction === "frames" && (
            <div className="grid grid-cols-3 gap-3">
              <input style={inputStyle} placeholder="Interval (sec)" type="number" value={videoInterval} onChange={(e) => setVideoInterval(e.target.value)} />
              <input style={inputStyle} placeholder="Max frames" type="number" value={videoMaxFrames} onChange={(e) => setVideoMaxFrames(e.target.value)} />
              <input style={inputStyle} placeholder="Size (e.g. 640x480)" value={videoSize} onChange={(e) => setVideoSize(e.target.value)} />
            </div>
          )}
          <button onClick={() => videoMutation.mutate()} disabled={videoMutation.isPending || !videoPath}
            className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-40" style={btnStyle}>
            {videoMutation.isPending ? "Processing..." : `Run ${videoAction}`}
          </button>
          {videoResult && (
            <pre className="p-3 rounded border text-xs overflow-auto max-h-96 whitespace-pre-wrap card-bordered text-primary">
              {videoResult}
            </pre>
          )}
        </div>
      )}

      {tab === "upload" && (
        <div className="space-y-4 max-w-lg">
          <input ref={fileRef} type="file" style={inputStyle} className="file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:text-sm" onChange={handleUpload} />
          {uploadResult && (
            <pre className="p-3 rounded border text-xs overflow-auto card-bordered text-primary">
              {uploadResult}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
