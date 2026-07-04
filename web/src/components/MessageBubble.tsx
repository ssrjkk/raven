import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import { MessageData } from "../api/client";

interface MessageBubbleProps {
  message: MessageData;
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";
  const isTool = message.role === "tool";
  const ts = message.created_at ? new Date(message.created_at).toLocaleString() : null;

  if (isSystem) {
    return (
      <div className="flex justify-center">
        <div className="bg-gray-800/30 border border-gray-700/30 rounded-lg px-3 py-1.5 text-xs text-gray-500 max-w-[80%] text-center">
          {message.content}
        </div>
      </div>
    );
  }

  if (isTool) {
    return (
      <div className="flex justify-start">
        <div className="bg-gray-900/40 border border-gray-700/20 rounded-lg px-3 py-2 text-xs text-gray-500 max-w-[80%] font-mono">
          <span className="text-[10px] text-gray-600 uppercase tracking-wider block mb-1">Tool Output</span>
          <pre className="whitespace-pre-wrap">{message.content.slice(0, 500)}</pre>
        </div>
      </div>
    );
  }

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`
          max-w-[80%] rounded-2xl px-4 py-2.5
          ${isUser
            ? "bg-violet-600/80 text-white rounded-br-sm"
            : "bg-gray-800/50 border border-gray-700/50 text-gray-100 rounded-bl-sm"
          }
        `}
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
}

function MarkdownContent({ content }: { content: string }) {
  return <ReactMarkdown rehypePlugins={[rehypeSanitize]}>{content}</ReactMarkdown>;
}