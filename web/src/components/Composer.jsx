import { useLayoutEffect, useRef, useState } from "react";
import ImagePlus from "lucide-react/dist/esm/icons/image-plus.mjs";
import Send from "lucide-react/dist/esm/icons/send.mjs";

const COMPOSER_MIN_HEIGHT = 100;
const COMPOSER_MAX_HEIGHT = 280;
const TEXTAREA_MIN_HEIGHT = 36;

export function Composer({ value, onChange }) {
  const textareaRef = useRef(null);
  const composingRef = useRef(false);
  const [announcement, setAnnouncement] = useState("");

  const hasContent = value.trim().length > 0;

  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    textarea.style.height = "auto";
    const nextHeight = Math.min(
      Math.max(textarea.scrollHeight, TEXTAREA_MIN_HEIGHT),
      COMPOSER_MAX_HEIGHT - 64,
    );
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > nextHeight ? "auto" : "hidden";
  }, [value]);

  function handleSubmit(event) {
    event?.preventDefault();
    if (!hasContent || composingRef.current) return;

    setAnnouncement("已完成本地发送预览，本阶段未连接真实 AI 接口。稿件内容已保留。");
  }

  function handleKeyDown(event) {
    const isComposing = composingRef.current || event.nativeEvent.isComposing;
    if (event.key !== "Enter" || event.shiftKey || isComposing) return;

    event.preventDefault();
    handleSubmit();
  }

  function handleImageAction() {
    setAnnouncement("图片上传将在后续阶段接入。");
  }

  return (
    <form
      className="composer"
      style={{ minHeight: `${COMPOSER_MIN_HEIGHT}px` }}
      onSubmit={handleSubmit}
      aria-label="消息输入区"
    >
      <label className="sr-only" htmlFor="message-composer">
        输入你的问题
      </label>
      <textarea
        id="message-composer"
        ref={textareaRef}
        value={value}
        rows={1}
        maxLength={2000}
        placeholder="输入你的问题..."
        onChange={(event) => onChange(event.target.value)}
        onCompositionStart={() => {
          composingRef.current = true;
        }}
        onCompositionEnd={() => {
          composingRef.current = false;
        }}
        onKeyDown={handleKeyDown}
      />

      <div className="composer-actions">
        <button
          className="composer-icon-button attachment-action"
          type="button"
          aria-label="添加图片"
          title="图片上传将在后续阶段接入"
          onClick={handleImageAction}
        >
          <ImagePlus aria-hidden="true" size={24} strokeWidth={1.5} />
        </button>

        <button
          className="composer-icon-button send-action"
          type="submit"
          aria-label="发送消息"
          disabled={!hasContent}
        >
          <Send aria-hidden="true" size={21} strokeWidth={1.6} />
        </button>
      </div>

      <p className="sr-only" aria-live="polite">
        {announcement}
      </p>
    </form>
  );
}
