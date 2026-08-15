import { useDropdown } from "../hooks/useDropdown";

/** 自绘下拉框（替代原生 select，贴合暗色主题） */
export default function Dropdown({
  value,
  options,
  onChange,
}: {
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  const { open, toggle, close, triggerRef, portal } = useDropdown();
  const current = options.find((o) => o.value === value);

  return (
    <>
      <button ref={triggerRef} className="dropdown-btn" onClick={toggle}>
        {current?.label ?? value} {open ? "▾" : "◂"}
      </button>
      {portal(
        <div className="dropdown-menu">
          {options.map((o) => (
            <button
              key={o.value}
              className={o.value === value ? "active" : ""}
              onClick={() => { onChange(o.value); close(); }}
            >
              {o.label} {o.value === value && "✓"}
            </button>
          ))}
        </div>
      )}
    </>
  );
}
