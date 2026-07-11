import { useState } from "react";
import { api } from "../api/client";

type Tab = "send" | "inbox" | "config";

export default function EmailPage() {
  const [tab, setTab] = useState<Tab>("send");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(false);

  // send
  const [to, setTo] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");

  // inbox
  const [emails, setEmails] = useState<any[]>([]);
  const [total, setTotal] = useState(0);

  // config
  const [config, setConfig] = useState<Record<string, any>>({});

  async function handleSend() {
    setMsg(""); setError("");
    setLoading(true);
    try {
      const r: any = await api.emailSend(to, subject, body);
      setMsg(`Email sent to ${r.to}`);
      setTo(""); setSubject(""); setBody("");
    } catch (e: any) {
      setError(e.message || "Send failed");
    } finally { setLoading(false); }
  }

  async function loadInbox() {
    setLoading(true); setError("");
    try {
      const r = await api.emailInbox(10);
      setEmails(r.emails);
      setTotal(r.total);
    } catch (e: any) {
      setError(e.message || "Failed to load inbox");
    } finally { setLoading(false); }
  }

  async function loadConfig() {
    setLoading(true); setError("");
    try {
      const r = await api.emailConfig();
      setConfig(r);
    } catch (e: any) {
      setError(e.message || "Failed to load config");
    } finally { setLoading(false); }
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: "send", label: "Send Email" },
    { key: "inbox", label: "Inbox" },
    { key: "config", label: "Configuration" },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Email Channel</h1>

      <div className="flex gap-1 mb-6 border-b" style={{ borderColor: "var(--dt-colors-border-default)" }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className="px-4 py-2 text-sm font-medium rounded-t-lg transition"
            style={{ color: tab === t.key ? "var(--dt-colors-accent-default)" : "var(--dt-colors-text-secondary)", borderBottom: tab === t.key ? "2px solid var(--dt-colors-accent-default)" : "2px solid transparent" }}>
            {t.label}
          </button>
        ))}
      </div>

      {error && <div className="p-3 mb-4 rounded-lg text-sm" style={{ backgroundColor: "rgba(239,68,68,0.1)", color: "var(--dt-colors-danger-default)" }}>{error}</div>}
      {msg && <div className="p-3 mb-4 rounded-lg text-sm" style={{ backgroundColor: "rgba(34,197,94,0.1)", color: "var(--dt-colors-success-default)" }}>{msg}</div>}

      {tab === "send" && (
        <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
          <h2 className="text-lg font-semibold mb-3">Send Email</h2>
          <div className="space-y-3 mb-3">
            <input placeholder="To (email address)" value={to} onChange={e => setTo(e.target.value)}
              className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
            <input placeholder="Subject" value={subject} onChange={e => setSubject(e.target.value)}
              className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
            <textarea placeholder="Email body..." value={body} onChange={e => setBody(e.target.value)}
              rows={6} className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
          </div>
          <button onClick={handleSend} disabled={loading || !to || !subject}
            className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
            {loading ? "Sending..." : "Send Email"}
          </button>
        </div>
      )}

      {tab === "inbox" && (
        <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
          <div className="flex justify-between items-center mb-3">
            <h2 className="text-lg font-semibold">Inbox ({total})</h2>
            <button onClick={loadInbox} className="px-3 py-1 rounded-lg text-xs" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-secondary)" }}>
              Refresh
            </button>
          </div>
          {emails.length === 0 ? (
            <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>No emails loaded. Click Refresh.</p>
          ) : (
            <div className="space-y-2">
              {emails.map((e, i) => (
                <div key={i} className="p-3 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                  <div className="flex justify-between text-sm">
                    <span className="font-medium">{e.from}</span>
                    <span className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>{e.date}</span>
                  </div>
                  <p className="text-sm font-medium mt-1">{e.subject}</p>
                  <p className="text-xs mt-1" style={{ color: "var(--dt-colors-text-tertiary)" }}>{e.body_preview?.slice(0, 200)}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "config" && (
        <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
          <div className="flex justify-between items-center mb-3">
            <h2 className="text-lg font-semibold">Email Configuration</h2>
            <button onClick={loadConfig} className="px-3 py-1 rounded-lg text-xs" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-secondary)" }}>
              Check
            </button>
          </div>
          {Object.keys(config).length === 0 ? (
            <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>Click Check to load config.</p>
          ) : (
            <div className="space-y-2 text-sm">
              <div className="flex justify-between p-2 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                <span>SMTP</span>
                <span>{config.smtp_configured ? `✓ ${config.smtp_host}` : "✗ Not configured"}</span>
              </div>
              <div className="flex justify-between p-2 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                <span>IMAP</span>
                <span>{config.imap_configured ? `✓ ${config.imap_host}` : "✗ Not configured"}</span>
              </div>
              <div className="flex justify-between p-2 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                <span>SMTP Library</span>
                <span>{config.smtp_lib_available ? "✓ Installed" : "✗ Not installed"}</span>
              </div>
              <div className="flex justify-between p-2 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                <span>IMAP Library</span>
                <span>{config.imap_lib_available ? "✓ Installed" : "✗ Not installed"}</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
