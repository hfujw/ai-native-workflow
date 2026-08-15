import { useDropdown } from "../hooks/useDropdown";

/** 卡片式下拉（ChatGPT 思考等级样式：名称 + 描述 + 左侧绿线 + Pro 徽章） */
export default function LevelSelect({
  value,
  options,
  onChange,
}: {
  value: string;
  options: { id: string; name: string; desc: string; pro?: boolean }[];
  onChange: (id: string) => void;
}) {
  const { open, toggle, close, triggerRef, portal } = useDropdown();
  const selected = options.find((o) => o.id === value) ?? options[0];

  return (
    <>
      <button ref={triggerRef} className="dropdown-btn" onClick={toggle}>{selected.name} {open ? "▾" : "◂"}</button>
      {portal(
        <div className="level-menu">
          {options.map((o) => (
            <div
              key={o.id}
              className={`level-item ${o.id === value ? "selected" : ""}`}
              onClick={() => { onChange(o.id); close(); }}
            >
              <div className="level-indicator" />
              <div className="level-body">
                <div className="level-name-row">
                  <span className="level-name">{o.name}</span>
                  {o.pro && <span className="level-pro">Pro</span>}
                </div>
                <span className="level-desc">{o.desc}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
