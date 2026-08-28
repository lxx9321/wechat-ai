import { SuggestedPrompts } from "./SuggestedPrompts.jsx";

export function EmptyState({ onPromptSelect }) {
  return (
    <div className="empty-state">
      <div className="empty-state-copy">
        <h1>今天想聊点什么？</h1>
        <p>我可以帮你发现好故事、分析内容、解答问题，或陪你理清想法。</p>
        <span className="accent-rule" aria-hidden="true" />
      </div>

      <SuggestedPrompts onSelect={onPromptSelect} />
    </div>
  );
}

