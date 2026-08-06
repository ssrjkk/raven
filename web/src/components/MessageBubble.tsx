import { memo } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";

import { MessageData } from "../api/client";

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
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-2.5 ${
          isUser ? "text-white rounded-br-sm" : "rounded-bl-sm"
        }`}
        style={
          isUser
            ? {
                backgroundImage: "linear-gradient(135deg, var(--dt-colors-accent-default), var(--dt-colors-accent-hover, #6d28d9))",
                boxShadow: "0 4px 16px var(--dt-colors-accent-muted, rgba(124,58,237,0.3))",
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
          <MarkdownContent content={message.content} />
        </div>
      </div>
    </div>
  );
});

export default MessageBubble;

function MarkdownContent({ content }: { content: string }) {
  return <ReactMarkdown rehypePlugins={[rehypeSanitize]}>{content}</ReactMarkdown>;
}
