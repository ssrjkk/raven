import { useEffect, useState } from "react";
import { api } from "../api/client";

type Tab = "speakers" | "verify" | "continuous" | "stats";

export default function Voice() {
  const [tab, setTab] = useState<Tab>("speakers");
  const [speakers, setSpeakers] = useState<any[]>([]);
  const [stats, setStats] = useState<Record<string, any>>({});
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState("");

  // enroll form
  const [enrollId, setEnrollId] = useState("");
  const [enrollSamples, setEnrollSamples] = useState("");

  // verify form
  const [verifyId, setVerifyId] = useState("");
  const [verifyAudio, setVerifyAudio] = useState("");
  const [verifyResult, setVerifyResult] = useState<any>(null);

  // identify form
  const [identifyAudio, setIdentifyAudio] = useState("");
  const [identifyResult, setIdentifyResult] = useState<any[] | null>(null);

  // continuous form
  const [contId, setContId] = useState("");
  const [contInterval, setContInterval] = useState("5");

  async function loadSpeakers() {
    setLoading(true); setError("");
    try {
      const r = await api.voiceSpeakers();
      setSpeakers(r.speakers);
    } catch (e: any) {
      setError(e.message || "Failed to load speakers");
    } finally { setLoading(false); }
  }

  async function loadStats() {
    setLoading(true); setError("");
    try {
      const r = await api.voiceStats();
      setStats(r);
    } catch (e: any) {
      setError(e.message || "Failed to load stats");
    } finally { setLoading(false); }
  }

  useEffect(() => {
    if (tab === "speakers") loadSpeakers();
    if (tab === "stats") loadStats();
  }, [tab]);

  async function handleEnroll() {
    setMsg(""); setError("");
    let samples: number[][];
    try {
      samples = JSON.parse(enrollSamples);
    } catch {
      setError("Invalid JSON for audio_samples (must be array of number arrays)");
      return;
    }
    setLoading(true);
    try {
      const r: any = await api.voiceEnroll(enrollId, samples);
      setMsg(`Speaker '${r.speaker_id}' enrolled (${r.samples_processed} samples)`);
      setEnrollId(""); setEnrollSamples("");
      loadSpeakers();
    } catch (e: any) {
      setError(e.message || "Enroll failed");
    } finally { setLoading(false); }
  }

  async function handleVerify() {
    setVerifyResult(null); setError("");
    let audio: number[];
    try {
      audio = JSON.parse(verifyAudio);
    } catch {
      setError("Invalid JSON for audio (must be array of numbers)");
      return;
    }
    setLoading(true);
    try {
      const r = await api.voiceVerify(verifyId, audio);
      setVerifyResult(r);
    } catch (e: any) {
      setError(e.message || "Verify failed");
    } finally { setLoading(false); }
  }

  async function handleIdentify() {
    setIdentifyResult(null); setError("");
    let audio: number[];
    try {
      audio = JSON.parse(identifyAudio);
    } catch {
      setError("Invalid JSON for audio (must be array of numbers)");
      return;
    }
    setLoading(true);
    try {
      const r = await api.voiceIdentify(audio);
      setIdentifyResult(r.results);
    } catch (e: any) {
      setError(e.message || "Identify failed");
    } finally { setLoading(false); }
  }

  async function handleRemove(id: string) {
    setError(""); setMsg("");
    setLoading(true);
    try {
      await api.voiceRemove(id);
      setMsg(`Speaker '${id}' removed`);
      loadSpeakers();
    } catch (e: any) {
      setError(e.message || "Remove failed");
    } finally { setLoading(false); }
  }

  async function handleContinuousStart() {
    setMsg(""); setError("");
    setLoading(true);
    try {
      const r: any = await api.voiceContinuousStart(contId, parseFloat(contInterval) || 5);
      setMsg(`Continuous auth started for '${r.speaker_id}' (interval=${r.interval_sec}s)`);
    } catch (e: any) {
      setError(e.message || "Failed to start continuous auth");
    } finally { setLoading(false); }
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: "speakers", label: "Speakers" },
    { key: "verify", label: "Verify / Identify" },
    { key: "continuous", label: "Continuous Auth" },
    { key: "stats", label: "Statistics" },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Voice Biometrics</h1>

      <div className="flex gap-1 mb-6 border-b" style={{ borderColor: "var(--dt-colors-border-default)" }}>
        {tabs.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className="px-4 py-2 text-sm font-medium rounded-t-lg transition"
            style={{
              color: tab === t.key ? "var(--dt-colors-accent-default)" : "var(--dt-colors-text-secondary)",
              borderBottom: tab === t.key ? "2px solid var(--dt-colors-accent-default)" : "2px solid transparent",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="p-3 mb-4 rounded-lg text-sm" style={{ backgroundColor: "rgba(239,68,68,0.1)", color: "var(--dt-colors-danger-default)" }}>
          {error}
        </div>
      )}
      {msg && (
        <div className="p-3 mb-4 rounded-lg text-sm" style={{ backgroundColor: "rgba(34,197,94,0.1)", color: "var(--dt-colors-success-default)" }}>
          {msg}
        </div>
      )}

      {tab === "speakers" && (
        <div className="space-y-6">
          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Enroll Speaker</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
              <input
                placeholder="Speaker ID"
                value={enrollId}
                onChange={e => setEnrollId(e.target.value)}
                className="px-3 py-2 rounded-lg text-sm"
                style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }}
              />
              <textarea
                placeholder='[[0.1,0.2,...],[0.3,0.4,...]] (JSON array of audio samples)'
                value={enrollSamples}
                onChange={e => setEnrollSamples(e.target.value)}
                rows={3}
                className="px-3 py-2 rounded-lg text-sm font-mono md:col-span-2"
                style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }}
              />
            </div>
            <button
              onClick={handleEnroll}
              disabled={loading || !enrollId || !enrollSamples}
              className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50"
              style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}
            >
              {loading ? "Processing..." : "Enroll"}
            </button>
          </div>

          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Enrolled Speakers ({speakers.length})</h2>
            {speakers.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>No speakers enrolled.</p>
            ) : (
              <div className="space-y-2">
                {speakers.map((s: any) => (
                  <div key={s.speaker_id} className="flex items-center justify-between p-3 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                    <div>
                      <span className="font-medium">{s.speaker_id}</span>
                      <span className="ml-3 text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>
                        {s.num_samples} samples
                      </span>
                    </div>
                    <button
                      onClick={() => handleRemove(s.speaker_id)}
                      className="px-3 py-1 rounded-lg text-xs font-medium"
                      style={{ backgroundColor: "rgba(239,68,68,0.15)", color: "var(--dt-colors-danger-default)" }}
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "verify" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Verify Speaker</h2>
            <div className="space-y-3 mb-3">
              <input
                placeholder="Speaker ID"
                value={verifyId}
                onChange={e => setVerifyId(e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-sm"
                style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }}
              />
              <textarea
                placeholder='[0.1,0.2,...] (audio as array of floats)'
                value={verifyAudio}
                onChange={e => setVerifyAudio(e.target.value)}
                rows={4}
                className="w-full px-3 py-2 rounded-lg text-sm font-mono"
                style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }}
              />
            </div>
            <button
              onClick={handleVerify}
              disabled={loading || !verifyId || !verifyAudio}
              className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50"
              style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}
            >
              {loading ? "Processing..." : "Verify"}
            </button>
            {verifyResult && (
              <div className="mt-3 p-3 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                <p className={verifyResult.verified ? "text-green-500" : "text-red-500"}>
                  {verifyResult.verified ? "✓ VERIFIED" : "✗ REJECTED"}
                </p>
                <p>Score: {verifyResult.score} (threshold: {verifyResult.threshold})</p>
                <p>Latency: {verifyResult.latency_ms.toFixed(1)}ms</p>
                {verifyResult.anti_spoof_score !== null && (
                  <p>Spoof score: {verifyResult.anti_spoof_score}{verifyResult.is_spoof ? " (spoof detected)" : ""}</p>
                )}
              </div>
            )}
          </div>

          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Identify Speaker</h2>
            <div className="space-y-3 mb-3">
              <textarea
                placeholder='[0.1,0.2,...] (audio as array of floats)'
                value={identifyAudio}
                onChange={e => setIdentifyAudio(e.target.value)}
                rows={4}
                className="w-full px-3 py-2 rounded-lg text-sm font-mono"
                style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }}
              />
            </div>
            <button
              onClick={handleIdentify}
              disabled={loading || !identifyAudio}
              className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50"
              style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}
            >
              {loading ? "Processing..." : "Identify"}
            </button>
            {identifyResult && (
              <div className="mt-3 space-y-2">
                {identifyResult.map((r: any, i: number) => (
                  <div key={i} className="p-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                    <span className="font-medium">{r.speaker_id}</span>
                    <span className="ml-2">score={r.score}</span>
                    <span className="ml-2">{r.verified ? "✓" : "✗"}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "continuous" && (
        <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
          <h2 className="text-lg font-semibold mb-3">Continuous Authentication</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
            <input
              placeholder="Speaker ID"
              value={contId}
              onChange={e => setContId(e.target.value)}
              className="px-3 py-2 rounded-lg text-sm"
              style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }}
            />
            <input
              placeholder="Interval (seconds)"
              value={contInterval}
              onChange={e => setContInterval(e.target.value)}
              type="number"
              min="1"
              step="0.5"
              className="px-3 py-2 rounded-lg text-sm"
              style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }}
            />
            <button
              onClick={handleContinuousStart}
              disabled={loading || !contId}
              className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50"
              style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}
            >
              {loading ? "Processing..." : "Start Continuous Auth"}
            </button>
          </div>
          <p className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>
            Starts a periodic verification loop. The speaker must be enrolled first.
          </p>
        </div>
      )}

      {tab === "stats" && (
        <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
          <h2 className="text-lg font-semibold mb-3">Voice Biometrics Statistics</h2>
          {loading ? (
            <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>Loading...</p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              {[
                { label: "Enrolled Speakers", value: stats.enrolled_speakers },
                { label: "Continuous Sessions", value: stats.continuous_sessions },
                { label: "Threshold", value: stats.threshold },
                { label: "Encoder Model", value: stats.encoder_model?.split("/").pop() },
              ].map(s => (
                <div key={s.label} className="p-3 rounded-lg text-center" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                  <div className="text-2xl font-bold">{s.value ?? "—"}</div>
                  <div className="text-xs mt-1" style={{ color: "var(--dt-colors-text-tertiary)" }}>{s.label}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
