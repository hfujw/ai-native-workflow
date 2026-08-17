import { Component, type ReactNode } from "react";

/** 全局错误边界——一个组件崩了不会全屏白，给出可恢复的兜底。 */
export default class ErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            display: "flex",
            height: "100vh",
            alignItems: "center",
            justifyContent: "center",
            color: "var(--text-2)",
            fontSize: 14,
            background: "var(--main-bg)",
          }}
        >
          <div style={{ textAlign: "center", display: "flex", flexDirection: "column", gap: 14 }}>
            <div>出错了，界面需要刷新</div>
            <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
              <button
                onClick={() => this.setState({ hasError: false })}
                style={{
                  border: "1px solid var(--border-medium)",
                  background: "var(--surface-2)",
                  color: "var(--text-1)",
                  fontFamily: "inherit",
                  fontSize: 13,
                  padding: "8px 16px",
                  borderRadius: 8,
                  cursor: "pointer",
                }}
              >
                重试
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
