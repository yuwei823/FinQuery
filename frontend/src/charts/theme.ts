import { echarts } from "./echarts"

// 设计 token 移植自 lieflat-charts 的 mono-tokens 结构，色值适配 FinQuery 品牌调色板
// （见 src/styles/_settings.scss）。结构对应关系：
// INK=neutral-950 PAPER=neutral-50 MUTED=neutral-500 FAINT=neutral-300 GRID=neutral-150
export const INK = "#17221c"
export const PAPER = "#f7f9f7"
export const MUTED = "#7b6f6a"
export const FAINT = "#9f9691"
export const GRID = "#dce2dd"

// 系列色 ladder：品牌红棕与数据绿优先，其后按明度递退，按重要性分配而不是随机取色。
export const SERIES_LADDER = [
  "#7a3b32",
  "#24714f",
  "#a96558",
  "#62a07f",
  "#c18476",
  "#6983a8",
  "#d2aa60",
  "#8d827d",
]

// K 线涨跌色遵循国内习惯：红涨绿跌。
export const UP_COLOR = "#b94646"
export const DOWN_COLOR = "#24714f"

export const FONT_FAMILY = 'Inter, "Microsoft YaHei", "Noto Sans SC", sans-serif'

// 入场动画：快进快停，不弹跳。
export const ANIMATION = {
  duration: 900,
  easing: "quarticOut",
  durationUpdate: 300,
} as const

export const TOOLTIP = {
  backgroundColor: INK,
  borderWidth: 0,
  padding: [10, 14],
  textStyle: { color: PAPER, fontFamily: FONT_FAMILY, fontSize: 12 },
} as const

export const THEME_NAME = "finquery"

let registered = false

export function ensureFinQueryTheme(): string {
  if (!registered) {
    echarts.registerTheme(THEME_NAME, {
      color: SERIES_LADDER,
      textStyle: { fontFamily: FONT_FAMILY },
    })
    registered = true
  }
  return THEME_NAME
}

export function animationEnabled(): boolean {
  return !window.matchMedia("(prefers-reduced-motion: reduce)").matches
}
