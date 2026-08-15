import { useState } from "react";
import { useDropdown } from "../hooks/useDropdown";

const MODELS = ["deepseek-Flash", "deepseek-Pro"];
const TOOLS = [
  { name: "搜索", icon: "🔍" },
  { name: "图表", icon: "📊" },
  { name: "图片", icon: "🖼️" },
  { name: "地图", icon: "🗺️" },
];

export default function Composer({ onSend }: { onSend: (text: string) => void }) {
  const [input, setInput] = useState("");
  const [model, setModel] = useState(MODELS[0]);
  const [tools, setTools] = useState<string[]>([]);

  const modelDrop = useDropdown();
  const plusDrop = useDropdown();

  const addTool = (t: string) => setTools((ts) => (ts.includes(t) ? ts : [...ts, t]));
  const removeTool = (t: string) => setTools((ts) => ts.filter((x) => x !== t));

  const send = () => {
    const text = input.trim();
    if (!text) return;
    onSend(text);
    setInput("");
  };

  return (
    <div className="composer-area">
      {/* 工具 chips（选中工具时显示在输入框上方） */}
      {tools.length > 0 && (
        <div className="composer-tools">
          {tools.map((t) => (
            <span className="tool-chip" key={t}>
              {t}
              <button className="tool-chip-x" onClick={() => removeTool(t)}>×</button>
            </span>
          ))}
        </div>
      )}

      {/* 输入框 */}
      <div className="composer">
        <button ref={plusDrop.triggerRef} className="plus-btn" onClick={plusDrop.toggle}>＋</button>
        {plusDrop.portal(
          <div className="plus-menu">
            {TOOLS.map((t) => (
              <button key={t.name} onClick={() => { addTool(t.name); plusDrop.close(); }}>
                <span>{t.icon}</span> {t.name}
              </button>
            ))}
          </div>
        )}

        <textarea
          value={input}
          onChange={(e) => setInput(e.currentTarget.value)}
          placeholder="发送消息..."
          rows={1}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />

        {/* 模型选择 */}
        <button ref={modelDrop.triggerRef} className="model-chip" onClick={modelDrop.toggle}>
          {model} {modelDrop.open ? "▾" : "◂"}
        </button>
        {modelDrop.portal(
          <div className="model-menu">
            {MODELS.map((m) => (
              <button
                key={m}
                className={m === model ? "active" : ""}
                onClick={() => { setModel(m); modelDrop.close(); }}
              >
                {m} {m === model && "✓"}
              </button>
            ))}
          </div>
        )}

        <button className="send-btn" disabled={!input.trim()} onClick={send}>↑</button>
      </div>
    </div>
  );
}
