import { memo, useState } from "react";
import { Bot, Check, Copy, User } from "lucide-react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";

import { MessageData } from "../api/client";
import ArtifactRenderer from "./ArtifactRenderer";

interface MessageBubbleProps {
  message: MessageData;
}

const MessageBubble = memo(function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";
  const isTool = message.role === "tool";
  const ts = message.created_at ? new Date(message.created_at).toLocaleString() : null;

  if (isSystem) {
    return (
      <div className="flex justify-center">
        <div
          className="rounded-full px-3 py-1.5 text-xs max-w-[80%] text-center"
          style={{
            backgroundColor: "var(--dt-colors-bg-tertiary)",
            color: "var(--dt-colors-text-tertiary)",
            border: "1px solid var(--dt-colors-border-default)",
          }}
        >
          {message.content}
        </div>
      </div>
    );
  }

  if (isTool) {
    return (
      <div className="flex justify-start">
        <div
          className="rounded-xl px-3 py-2 text-xs max-w-[80%] font-mono"
          style={{
            backgroundColor: "var(--dt-colors-bg-tertiary)",
            color: "var(--dt-colors-text-secondary)",
            border: "1px dashed var(--dt-colors-border-default)",
          }}
        >
          <span
            className="block mb-1 text-[10px] uppercase tracking-wider"
            style={{ color: "var(--dt-colors-text-tertiary)" }}
          >
            Tool Output
          </span>
          <pre className="whitespace-pre-wrap">{message.content.slice(0, 500)}</pre>
        </div>
      </div>
    );
  }

  return (
    <div className={`flex items-end gap-2.5 ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && <Avatar role="assistant" />}
      <div
        className={`max-w-[78%] rounded-2xl px-4 py-2.5 ${
          isUser ? "text-white rounded-br-sm" : "rounded-bl-sm"
        }`}
        style={
          isUser
            ? {
                backgroundImage: "linear-gradient(135deg, var(--dt-colors-accent-default), var(--dt-colors-accent-hover, #6d28d9))",
                boxShadow: "0 4px 16px var(--dt-colors-accent-muted, rgba(124, 58, 237, 0.3))",
              }
            : {
                backgroundColor: "var(--dt-colors-bg-tertiary)",
                color: "var(--dt-colors-text-primary)",
                border: "1px solid var(--dt-colors-border-default)",
              }
        }
      >
        <div className="text-[11px] font-medium mb-1 opacity-60 flex items-center gap-2">
          <span>{isUser ? "You" : "Raven"}</span>
          {ts && <span className="text-[10px] opacity-50">{ts}</span>}
        </div>
        <div className="text-sm leading-relaxed prose prose-invert max-w-none">
          {isUser ? (
            <MarkdownContent content={message.content} />
          ) : (
            <ArtifactRenderer content={message.content} />
          )}
        </div>
        {!isUser && <CopyButton content={message.content} />}
      </div>
      {isUser && <Avatar role="user" />}
    </div>
  );
});

export default MessageBubble;

function Avatar({ role }: { role: "user" | "assistant" }) {
  return (
    <div
      className="w-7 h-7 shrink-0 rounded-full flex items-center justify-center text-white shadow-md"
      style={
        role === "user"
          ? {
              backgroundImage: "linear-gradient(135deg, var(--dt-colors-accent-default), #d946ef)",
              boxShadow: "0 2px 10px var(--dt-colors-accent-muted, rgba(124, 58, 237, 0.35))",
            }
          : {
              backgroundColor: "var(--dt-colors-bg-tertiary)",
              border: "1px solid var(--dt-colors-border-default)",
            }
      }
    >
      {role === "user" ? (
        <User size={14} className="text-white" />
      ) : (
        <Bot size={14} style={{ color: "var(--dt-colors-accent-default)" }} />
      )}
    </div>
  );
}

function CopyButton({ content }: { content: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };
  return (
    <button
      type="button"
      onClick={copy}
      className="mt-1.5 inline-flex items-center gap-1 text-[10px] opacity-50 hover:opacity-100 transition-opacity"
      style={{ color: "var(--dt-colors-text-tertiary)" }}
      aria-label="Copy response"
    >
      {copied ? <Check size={11} /> : <Copy size={11} />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function MarkdownContent({ content }: { content: string }) {
  return <ReactMarkdown rehypePlugins={[rehypeSanitize]}>{content}</ReactMarkdown>;
}
