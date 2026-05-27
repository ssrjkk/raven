import ReactMarkdown from "react-markdown";
import { MessageData } from "../api/client";

interface MessageBubbleProps {
  message: MessageData;
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";
  const isTool = message.role === "tool";

  if (isSystem) {
    return (
      <div className="flex justify-center">
        <div className="bg-gray-800/30 border border-gray-700/30 rounded-lg px-3 py-1.5 text-xs text-gray-500 max-w-[60%] text-center">
          {message.content.slice(0, 100)}
        </div>
      </div>
    );
  }

  if (isTool) {
    return null;
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
        <div className="text-[11px] font-medium mb-1 opacity-60">
          {isUser ? "You" : "Raven"}
        </div>
        <div className="text-sm leading-relaxed prose prose-invert max-w-none">
          <MarkdownContent content={message.content} />
        </div>
      </div>
    </div>
  );
}

function MarkdownContent({ content }: { content: string }) {
  return <ReactMarkdown>{content}</ReactMarkdown>;
}
