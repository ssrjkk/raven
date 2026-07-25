import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import { useApiQuery } from "../hooks/useApiQuery";

interface VoiceSpeaker {
  speaker_id: string;
  num_samples: number;
}

interface VerifyResult {
  verified: boolean;
  score: number;
  threshold: number;
  latency_ms: number;
  anti_spoof_score?: number | null;
  is_spoof?: boolean;
}

interface IdentifyResult {
  speaker_id: string;
  score: number;
  verified: boolean;
}

interface VoiceStats {
  enrolled_speakers?: number;
  continuous_sessions?: number;
  threshold?: number;
  encoder_model?: string;
}

type Tab = "speakers" | "verify" | "continuous" | "stats";

export default function Voice() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("speakers");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  // enroll form
  const [enrollId, setEnrollId] = useState("");
  const [enrollSamples, setEnrollSamples] = useState("");

  // verify form
  const [verifyId, setVerifyId] = useState("");
  const [verifyAudio, setVerifyAudio] = useState("");
  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null);

  // identify form
  const [identifyAudio, setIdentifyAudio] = useState("");
  const [identifyResult, setIdentifyResult] = useState<IdentifyResult[] | null>(null);

  // continuous form
  const [contId, setContId] = useState("");
  const [contInterval, setContInterval] = useState("5");

  const { data: speakersData } = useApiQuery<{ speakers: VoiceSpeaker[] }>(["voiceSpeakers"], () => api.voiceSpeakers(), { enabled: tab === "speakers" });
  const speakers = speakersData?.speakers ?? [];

  const { data: stats } = useApiQuery<VoiceStats>(["voiceStats"], () => api.voiceStats(), { enabled: tab === "stats" });

  const enroll = useMutation({
    mutationFn: () => {
      let samples: number[][];
      try { samples = JSON.parse(enrollSamples); }
      catch (e) { throw new Error("Invalid JSON for audio_samples (must be array of number arrays)"); }
      return api.voiceEnroll(enrollId, samples);
    },
    onSuccess: (r) => {
      setMsg(`Speaker '${r.speaker_id}' enrolled (${r.samples_processed} samples)`);
      setEnrollId(""); setEnrollSamples("");
      qc.invalidateQueries({ queryKey: ["voiceSpeakers"] });
    },
    onError: (e: any) => setError(e.message || "Enroll failed"),
  });

  const verify = useMutation({
    mutationFn: () => {
      let audio: number[];
      try { audio = JSON.parse(verifyAudio); }
      catch (e) { throw new Error("Invalid JSON for audio (must be array of numbers)"); }
      return api.voiceVerify(verifyId, audio);
    },
    onSuccess: (r) => { setVerifyResult(r); setError(""); },
    onError: (e: any) => setError(e.message || "Verify failed"),
  });

  const identify = useMutation({
    mutationFn: () => {
      let audio: number[];
      try { audio = JSON.parse(identifyAudio); }
      catch (e) { throw new Error("Invalid JSON for audio (must be array of numbers)"); }
      return api.voiceIdentify(audio);
    },
    onSuccess: (r) => { setIdentifyResult(r.results); setError(""); },
    onError: (e: any) => setError(e.message || "Identify failed"),
  });

  const removeSpeaker = useMutation({
    mutationFn: (id: string) => api.voiceRemove(id),
    onSuccess: (_data, id) => {
      setMsg(`Speaker '${id}' removed`);
      qc.invalidateQueries({ queryKey: ["voiceSpeakers"] });
    },
    onError: (e: any) => setError(e.message || "Remove failed"),
  });

  const continuousStart = useMutation({
    mutationFn: () => api.voiceContinuousStart(contId, parseFloat(contInterval) || 5),
    onSuccess: (r) => setMsg(`Continuous auth started for '${r.speaker_id}' (interval=${r.interval_sec}s)`),
    onError: (e: any) => setError(e.message || "Failed to start continuous auth"),
  });

  const tabs: { key: Tab; label: string }[] = [
    { key: "speakers", label: "Speakers" },
    { key: "verify", label: "Verify / Identify" },
    { key: "continuous", label: "Continuous Auth" },
    { key: "stats", label: "Statistics" },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Voice Biometrics</h1>

      <div className="flex gap-1 mb-6 border-b border-default">
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
        <div className="p-3 mb-4 rounded-lg text-sm bg-danger-muted text-danger">
          {error}
        </div>
      )}
      {msg && (
        <div className="p-3 mb-4 rounded-lg text-sm bg-success-muted text-success">
          {msg}
        </div>
      )}

      {tab === "speakers" && (
        <div className="space-y-6">
          <div className="p-4 rounded-lg bg-secondary">
            <h2 className="text-lg font-semibold mb-3">Enroll Speaker</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
              <input
                placeholder="Speaker ID"
                value={enrollId}
                onChange={e => setEnrollId(e.target.value)}
                className="px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default"
              />
              <textarea
                placeholder='[[0.1,0.2,...],[0.3,0.4,...]] (JSON array of audio samples)'
                value={enrollSamples}
                onChange={e => setEnrollSamples(e.target.value)}
                rows={3}
                className="px-3 py-2 rounded-lg text-sm font-mono md:col-span-2 bg-tertiary text-primary border-default"
              />
            </div>
            <button
              onClick={() => enroll.mutate()}
              disabled={enroll.isPending || !enrollId || !enrollSamples}
              className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50 bg-accent text-white"
            >
              {enroll.isPending ? "Processing..." : "Enroll"}
            </button>
          </div>

          <div className="p-4 rounded-lg bg-secondary">
            <h2 className="text-lg font-semibold mb-3">Enrolled Speakers ({speakers.length})</h2>
            {speakers.length === 0 ? (
              <p className="text-sm text-tertiary">No speakers enrolled.</p>
            ) : (
              <div className="space-y-2">
                {speakers.map((s) => (
                  <div key={s.speaker_id} className="flex items-center justify-between p-3 rounded-lg bg-tertiary">
                    <div>
                      <span className="font-medium">{s.speaker_id}</span>
                      <span className="ml-3 text-sm text-tertiary">
                        {s.num_samples} samples
                      </span>
                    </div>
                    <button
                      onClick={() => removeSpeaker.mutate(s.speaker_id)}
                      className="px-3 py-1 rounded-lg text-xs font-medium bg-danger-subtle text-danger"
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
          <div className="p-4 rounded-lg bg-secondary">
            <h2 className="text-lg font-semibold mb-3">Verify Speaker</h2>
            <div className="space-y-3 mb-3">
              <input
                placeholder="Speaker ID"
                value={verifyId}
                onChange={e => setVerifyId(e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default"
              />
              <textarea
                placeholder='[0.1,0.2,...] (audio as array of floats)'
                value={verifyAudio}
                onChange={e => setVerifyAudio(e.target.value)}
                rows={4}
                className="w-full px-3 py-2 rounded-lg text-sm font-mono bg-tertiary text-primary border-default"
              />
            </div>
            <button
              onClick={() => verify.mutate()}
              disabled={verify.isPending || !verifyId || !verifyAudio}
              className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50 bg-accent text-white"
            >
              {verify.isPending ? "Processing..." : "Verify"}
            </button>
            {verifyResult && (
              <div className="mt-3 p-3 rounded-lg text-sm bg-tertiary">
                <p className={verifyResult.verified ? "text-green-500" : "text-red-500"}>
                  {verifyResult.verified ? "РІСљвЂњ VERIFIED" : "РІСљвЂ” REJECTED"}
                </p>
                <p>Score: {verifyResult.score} (threshold: {verifyResult.threshold})</p>
                <p>Latency: {verifyResult.latency_ms.toFixed(1)}ms</p>
                {verifyResult.anti_spoof_score !== null && (
                  <p>Spoof score: {verifyResult.anti_spoof_score}{verifyResult.is_spoof ? " (spoof detected)" : ""}</p>
                )}
              </div>
            )}
          </div>

          <div className="p-4 rounded-lg bg-secondary">
            <h2 className="text-lg font-semibold mb-3">Identify Speaker</h2>
            <div className="space-y-3 mb-3">
              <textarea
                placeholder='[0.1,0.2,...] (audio as array of floats)'
                value={identifyAudio}
                onChange={e => setIdentifyAudio(e.target.value)}
                rows={4}
                className="w-full px-3 py-2 rounded-lg text-sm font-mono bg-tertiary text-primary border-default"
              />
            </div>
            <button
              onClick={() => identify.mutate()}
              disabled={identify.isPending || !identifyAudio}
              className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50 bg-accent text-white"
            >
              {identify.isPending ? "Processing..." : "Identify"}
            </button>
            {identifyResult && (
              <div className="mt-3 space-y-2">
                {identifyResult.map((r, i) => (
                  <div key={i} className="p-2 rounded-lg text-sm bg-tertiary">
                    <span className="font-medium">{r.speaker_id}</span>
                    <span className="ml-2">score={r.score}</span>
                    <span className="ml-2">{r.verified ? "РІСљвЂњ" : "РІСљвЂ”"}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "continuous" && (
        <div className="p-4 rounded-lg bg-secondary">
          <h2 className="text-lg font-semibold mb-3">Continuous Authentication</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
            <input
              placeholder="Speaker ID"
              value={contId}
              onChange={e => setContId(e.target.value)}
              className="px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default"
            />
            <input
              placeholder="Interval (seconds)"
              value={contInterval}
              onChange={e => setContInterval(e.target.value)}
              type="number"
              min="1"
              step="0.5"
              className="px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default"
            />
            <button
              onClick={() => continuousStart.mutate()}
              disabled={continuousStart.isPending || !contId}
              className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50 bg-accent text-white"
            >
              {continuousStart.isPending ? "Processing..." : "Start Continuous Auth"}
            </button>
          </div>
          <p className="text-xs text-tertiary">
            Starts a periodic verification loop. The speaker must be enrolled first.
          </p>
        </div>
      )}

      {tab === "stats" && (
        <div className="p-4 rounded-lg bg-secondary">
          <h2 className="text-lg font-semibold mb-3">Voice Biometrics Statistics</h2>
          {stats === undefined ? (
            <p className="text-sm text-tertiary">Loading...</p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              {[
                { label: "Enrolled Speakers", value: stats.enrolled_speakers },
                { label: "Continuous Sessions", value: stats.continuous_sessions },
                { label: "Threshold", value: stats.threshold },
                { label: "Encoder Model", value: stats.encoder_model?.split("/").pop() },
              ].map(s => (
                <div key={s.label} className="p-3 rounded-lg text-center bg-tertiary">
                  <div className="text-2xl font-bold">{s.value ?? "РІР‚вЂќ"}</div>
                  <div className="text-xs mt-1 text-tertiary">{s.label}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
