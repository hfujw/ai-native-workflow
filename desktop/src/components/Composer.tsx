import { useMemo, useState } from "react";
import { useDropdown } from "../hooks/useDropdown";
import { IconCheck, IconChevronDown, IconSend } from "./icons";
import { groupModelsByProvider, type ModelItem } from "../lib/api";

/** 输入栏 —— DSH InputBar 样式：上输入区 + 下行右侧 [模型选择][发送] */
export default function Composer({
  onSend,
  models,
  modelId,
  onModelIdChange,
  iterable,
  sending,
}: {
  onSend: (text: string) => void;
  /** 可选模型（来自设置页管理，持久化） */
  models: ModelItem[];
  /** 选中的模型（受控：由 App 持有并持久化，发送时传给后端） */
  modelId: string;
  onModelIdChange: (id: string) => void;
  /** 成品可迭代状态：为 true 时输入会修改当前页面 */
  iterable?: boolean;
  /** 生成/迭代进行中：禁用发送，防连点 */
  sending?: boolean;
}) {
  const [input, setInput] = useState("");
  const modelDrop = useDropdown();

  const current = models.find((m) => m.id === modelId) ?? models[0];
  const groups = useMemo(() => groupModelsByProvider(models), [models]);

  const send = () => {
    if (sending) return;
    const text = input.trim();
    if (!text) return;
    onSend(text);
    setInput("");
  };

  return (
    <div className="composer-area">
      <div className="composer">
        {/* 上行：输入文字 */}
        <textarea
          value={input}
          onChange={(e) => setInput(e.currentTarget.value)}
          placeholder={iterable ? "继续修改这个页面..." : "给 Lumen 提供灵感..."}
          maxLength={500}
          rows={1}
          autoFocus
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />

        {/* 下行右侧：模型选择（挨着发送左边）+ 发送 */}
        <div className="composer-foot">
          <button
            ref={modelDrop.triggerRef}
            className={`model-select ${modelDrop.open ? "open" : ""}`}
            onClick={modelDrop.toggle}
            title="选择模型"
            disabled={models.length === 0}
          >
            <span className="model-select-name">{current?.name ?? "无可用模型"}</span>
            {current?.provider && (
              <span className="model-select-provider">{current.provider}</span>
            )}
            <IconChevronDown className={`chev ${modelDrop.open ? "open" : ""}`} size={13} />
          </button>
          {modelDrop.portal(
            <div className="model-menu">
              {groups.map((g) => (
                <section key={g.provider} className="model-group" role="group" aria-label={g.provider}>
                  <div className="model-group-title">{g.provider}</div>
                  {g.models.map((m) => (
                    <button
                      key={m.id}
                      className={`model-option ${m.id === current?.id ? "selected" : ""}`}
                      onClick={() => { onModelIdChange(m.id); modelDrop.close(); }}
                      title={m.modelId}
                    >
                      <div className="model-option-copy">
                        <span className="model-option-name">{m.name}</span>
                        <span className="model-option-desc">{m.modelId}</span>
                      </div>
                      {m.id === current?.id && <IconCheck size={15} />}
                    </button>
                  ))}
                </section>
              ))}
            </div>
          )}

          <button className="send-btn" disabled={!input.trim() || sending} onClick={send} title={sending ? "生成中..." : "发送"}>
            <IconSend size={15} />
          </button>
        </div>
      </div>
    </div>
  );
}
