/** 配置预检（纯函数）——发送前提示，不等生成才报"未配置 Key"。
 *
 * 从 App.tsx 抽出，便于单测。逻辑与 App 原实现完全一致。
 */

export type PreflightInput = {
  /** 当前选中模型所属提供方已配置的 API Key（空 = 未配置） */
  modelKey: string;
  /** 生成参数里的联网搜索开关 */
  searchEnabled: boolean;
  /** 搜索服务列表（每个服务有自己的 apiKey） */
  searchServices: { apiKey?: string }[];
};

/** 返回配置预检提示文案；空字符串 = 配置齐全，无需提示。 */
export function computeConfigHint(input: PreflightInput): string {
  const { modelKey, searchEnabled, searchServices } = input;
  const searchOnButNoKey =
    searchEnabled && searchServices.length > 0 && !searchServices.some((s) => s.apiKey);

  if (!modelKey) return "未配置模型 API Key——请到 设置→模型 填写";
  if (searchOnButNoKey) return "联网搜索已开启但搜索服务未配置 Key——将只用自身知识";
  return "";
}
