import { Bot, Check, Copy, User } from "lucide-react";
import { memo, useState } from "react";
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
        <div className="bubble-system rounded-full px-3 py-1.5 text-xs max-w-[80%] text-center">
          {message.content}
        </div>
      </div>
    );
  }

  if (isTool) {
    return (
      <div className="flex justify-start">
        <div className="bubble-tool rounded-xl px-3 py-2 text-xs max-w-[80%] font-mono">
          <span
            className="block mb-1 text-micro uppercase tracking-wider text-tertiary"

          >
            Tool Output
          </span>
          <pre className="whitespace-pre-wrap">{message.content.slice(0, 500)}</pre>
        </div>
      </div>
    );
  }

  return (
    <div className={`flex items-end gap-2.5 msg-enter ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && <Avatar role="assistant" />}
      <div
        className={`group relative max-w-[78%] rounded-2xl px-4 py-2.5 ${
          isUser ? "bubble-user on-accent rounded-br-sm" : "bubble-assistant rounded-bl-sm"
        }`}
      >
        <div className="flex items-center justify-between gap-3">
          <span className="text-caption font-medium opacity-60">{isUser ? "You" : "Raven"}</span>
          {ts && (
            <span className="text-micro opacity-0 transition-opacity duration-150 group-hover:opacity-50">
              {ts}
            </span>
          )}
        </div>
        <div className="text-sm leading-relaxed prose max-w-none">
          {isUser ? (
            <MarkdownContent content={message.content} />
          ) : (
            <ArtifactRenderer content={message.content} />
          )}
        </div>
        {!isUser && (
          <div className="absolute -bottom-0.5 right-2 translate-y-full opacity-0 transition-opacity duration-150 group-hover:opacity-100">
            <CopyButton content={message.content} />
          </div>
        )}
      </div>
      {isUser && <Avatar role="user" />}
    </div>
  );
});

export default MessageBubble;

function Avatar({ role }: { role: "user" | "assistant" }) {
  return (
    <div className={`w-7 h-7 shrink-0 rounded-full flex items-center justify-center on-accent ${role === "user" ? "brand-surface" : "avatar-assistant"}`}>
      {role === "user" ? (
        <User size={14} className="on-accent" />
      ) : (
        <Bot size={14} className="text-accent" />
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
      className="inline-flex items-center gap-1 text-micro text-tertiary"

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
