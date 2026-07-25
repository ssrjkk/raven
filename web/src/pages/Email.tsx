import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";

interface EmailThread {
  from: string;
  subject: string;
  date?: string;
  body_preview?: string;
}

interface EmailConfig {
  smtp_configured?: boolean;
  smtp_host?: string;
  imap_configured?: boolean;
  imap_host?: string;
  smtp_lib_available?: boolean;
  imap_lib_available?: boolean;
}

type Tab = "send" | "inbox" | "config";

export default function EmailPage() {
  const [tab, setTab] = useState<Tab>("send");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  // send
  const [to, setTo] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");

  // inbox
  const [emails, setEmails] = useState<EmailThread[]>([]);
  const [total, setTotal] = useState(0);

  // config
  const [config, setConfig] = useState<EmailConfig>({});

  const sendMail = useMutation({
    mutationFn: () => api.emailSend(to, subject, body),
    onSuccess: (r) => {
      setMsg(`Email sent to ${r.to}`);
      setTo(""); setSubject(""); setBody("");
    },
    onError: (e: any) => setError(e.message || "Send failed"),
  });

  const loadInbox = useMutation({
    mutationFn: () => api.emailInbox(10),
    onSuccess: (r) => { setEmails(r.emails); setTotal(r.total); },
    onError: (e: any) => setError(e.message || "Failed to load inbox"),
  });

  const loadConfig = useMutation({
    mutationFn: () => api.emailConfig(),
    onSuccess: (r) => setConfig(r),
    onError: (e: any) => setError(e.message || "Failed to load config"),
  });

  const tabs: { key: Tab; label: string }[] = [
    { key: "send", label: "Send Email" },
    { key: "inbox", label: "Inbox" },
    { key: "config", label: "Configuration" },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Email Channel</h1>

      <div className="flex gap-1 mb-6 border-b border-default">
        {tabs.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className="px-4 py-2 text-sm font-medium rounded-t-lg transition"
            style={{ color: tab === t.key ? "var(--dt-colors-accent-default)" : "var(--dt-colors-text-secondary)", borderBottom: tab === t.key ? "2px solid var(--dt-colors-accent-default)" : "2px solid transparent" }}>
            {t.label}
          </button>
        ))}
      </div>

      {error && <div className="p-3 mb-4 rounded-lg text-sm bg-danger-muted text-danger">{error}</div>}
      {msg && <div className="p-3 mb-4 rounded-lg text-sm bg-success-muted text-success">{msg}</div>}

      {tab === "send" && (
        <div className="p-4 rounded-lg bg-secondary">
          <h2 className="text-lg font-semibold mb-3">Send Email</h2>
          <div className="space-y-3 mb-3">
            <input placeholder="To (email address)" value={to} onChange={e => setTo(e.target.value)}
              className="w-full px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
            <input placeholder="Subject" value={subject} onChange={e => setSubject(e.target.value)}
              className="w-full px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
            <textarea placeholder="Email body..." value={body} onChange={e => setBody(e.target.value)}
              rows={6} className="w-full px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
          </div>
          <button onClick={() => sendMail.mutate()} disabled={sendMail.isPending || !to || !subject}
            className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50 bg-accent text-white">
            {sendMail.isPending ? "Sending..." : "Send Email"}
          </button>
        </div>
      )}

      {tab === "inbox" && (
        <div className="p-4 rounded-lg bg-secondary">
          <div className="flex justify-between items-center mb-3">
            <h2 className="text-lg font-semibold">Inbox ({total})</h2>
            <button onClick={() => loadInbox.mutate()} className="px-3 py-1 rounded-lg text-xs btn-secondary-text">
              Refresh
            </button>
          </div>
          {emails.length === 0 ? (
            <p className="text-sm text-tertiary">No emails loaded. Click Refresh.</p>
          ) : (
            <div className="space-y-2">
              {emails.map((e, i) => (
                <div key={i} className="p-3 rounded-lg bg-tertiary">
                  <div className="flex justify-between text-sm">
                    <span className="font-medium">{e.from}</span>
                    <span className="text-xs text-tertiary">{e.date}</span>
                  </div>
                  <p className="text-sm font-medium mt-1">{e.subject}</p>
                  <p className="text-xs mt-1 text-tertiary">{e.body_preview?.slice(0, 200)}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "config" && (
        <div className="p-4 rounded-lg bg-secondary">
          <div className="flex justify-between items-center mb-3">
            <h2 className="text-lg font-semibold">Email Configuration</h2>
            <button onClick={() => loadConfig.mutate()} className="px-3 py-1 rounded-lg text-xs btn-secondary-text">
              Check
            </button>
          </div>
          {Object.keys(config).length === 0 ? (
            <p className="text-sm text-tertiary">Click Check to load config.</p>
          ) : (
            <div className="space-y-2 text-sm">
              <div className="flex justify-between p-2 rounded-lg bg-tertiary">
                <span>SMTP</span>
                <span>{config.smtp_configured ? `РІСљвЂњ ${config.smtp_host}` : "РІСљвЂ” Not configured"}</span>
              </div>
              <div className="flex justify-between p-2 rounded-lg bg-tertiary">
                <span>IMAP</span>
                <span>{config.imap_configured ? `РІСљвЂњ ${config.imap_host}` : "РІСљвЂ” Not configured"}</span>
              </div>
              <div className="flex justify-between p-2 rounded-lg bg-tertiary">
                <span>SMTP Library</span>
                <span>{config.smtp_lib_available ? "РІСљвЂњ Installed" : "РІСљвЂ” Not installed"}</span>
              </div>
              <div className="flex justify-between p-2 rounded-lg bg-tertiary">
                <span>IMAP Library</span>
                <span>{config.imap_lib_available ? "РІСљвЂњ Installed" : "РІСљвЂ” Not installed"}</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
