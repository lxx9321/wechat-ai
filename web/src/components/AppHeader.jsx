import Clock3 from "lucide-react/dist/esm/icons/clock-3.mjs";
import Menu from "lucide-react/dist/esm/icons/menu.mjs";
import { BRAND_NAME } from "../config/brand.js";

const ICON_SIZE = 20;
const ICON_STROKE = 1.5;

export function AppHeader() {
  return (
    <header className="app-header">
      <a className="brand" href="/" aria-label={`${BRAND_NAME}首页`}>
        {BRAND_NAME}
      </a>

      <div className="header-tools" aria-label="页面工具">
        <button
          className="memory-action"
          type="button"
          disabled
          title="当前没有可清空的聊天记忆"
        >
          <Clock3 aria-hidden="true" size={ICON_SIZE} strokeWidth={ICON_STROKE} />
          <span>清空记忆</span>
        </button>

        <span className="header-divider" aria-hidden="true" />

        <button className="menu-action" type="button" aria-label="打开菜单">
          <Menu aria-hidden="true" size={24} strokeWidth={ICON_STROKE} />
        </button>
      </div>
    </header>
  );
}
