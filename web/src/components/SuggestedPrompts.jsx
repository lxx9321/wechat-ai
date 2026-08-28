import ChevronRight from "lucide-react/dist/esm/icons/chevron-right.mjs";
import Code2 from "lucide-react/dist/esm/icons/code-2.mjs";
import ImageIcon from "lucide-react/dist/esm/icons/image.mjs";
import ListTree from "lucide-react/dist/esm/icons/list-tree.mjs";
import PlaySquare from "lucide-react/dist/esm/icons/play-square.mjs";

const ICON_SIZE = 20;
const ICON_STROKE = 1.45;

const PROMPTS = [
  {
    text: "帮我推荐一部节奏快的悬疑剧",
    Icon: PlaySquare,
  },
  {
    text: "分析一下这张图片",
    Icon: ImageIcon,
  },
  {
    text: "给我解释一个技术问题",
    Icon: Code2,
  },
  {
    text: "帮我整理一个想法",
    Icon: ListTree,
  },
];

export function SuggestedPrompts({ onSelect }) {
  return (
    <div className="suggested-prompts" aria-label="建议问题">
      {PROMPTS.map(({ text, Icon }) => (
        <button
          className="suggested-prompt"
          key={text}
          type="button"
          onClick={() => onSelect(text)}
        >
          <Icon
            className="prompt-icon"
            aria-hidden="true"
            size={ICON_SIZE}
            strokeWidth={ICON_STROKE}
          />
          <span>{text}</span>
          <ChevronRight
            className="prompt-chevron"
            aria-hidden="true"
            size={22}
            strokeWidth={ICON_STROKE}
          />
        </button>
      ))}
    </div>
  );
}
