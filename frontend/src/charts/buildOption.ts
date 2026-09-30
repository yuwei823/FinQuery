import type { EChartsCoreOption } from "echarts/core"

import type { VisualizationSpec } from "../types"
import {
  ANIMATION,
  DOWN_COLOR,
  FAINT,
  GRID,
  INK,
  MUTED,
  PAPER,
  SERIES_LADDER,
  TOOLTIP,
  UP_COLOR,
  animationEnabled,
} from "./theme"

type Row = Record<string, unknown>

const CHART_TYPE_LABELS: Record<string, string> = {
  bar: "柱状图",
  pie: "饼图",
  line: "折线图",
  area: "面积图",
  scatter: "散点图",
  heatmap: "热力图",
  candlestick: "K线图",
}

export function chartTypeLabel(type: string): string {
  return CHART_TYPE_LABELS[type] ?? type
}

function numeric(value: unknown): number | null {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function axisText() {
  return { color: MUTED, fontSize: 10, fontWeight: 600 }
}

function baseOption(): EChartsCoreOption {
  return {
    backgroundColor: PAPER,
    animation: animationEnabled(),
    animationDuration: ANIMATION.duration,
    animationEasing: ANIMATION.easing,
    animationDurationUpdate: ANIMATION.durationUpdate,
    textStyle: { color: INK },
    tooltip: { ...TOOLTIP },
    grid: { left: 12, right: 16, top: 18, bottom: 8, containLabel: true },
  }
}

function categoryAxis(labels: string[]) {
  return {
    type: "category" as const,
    data: labels,
    axisLine: { lineStyle: { color: GRID } },
    axisTick: { show: false },
    axisLabel: { ...axisText(), interval: "auto" as const },
  }
}

function valueAxis() {
  return {
    type: "value" as const,
    axisLabel: axisText(),
    splitLine: { lineStyle: { color: GRID, width: 0.5 } },
  }
}

// 将图表规格和查询结果行翻译成 ECharts option；字段缺失或没有可用数据时返回 null。
export function buildChartOption(spec: VisualizationSpec, rows: Row[]): EChartsCoreOption | null {
  switch (spec.type) {
    case "bar":
      return barOption(spec, rows)
    case "pie":
      return pieOption(spec, rows)
    case "line":
    case "area":
      return lineOption(spec, rows, spec.type === "area")
    case "scatter":
      return scatterOption(spec, rows)
    case "heatmap":
      return heatmapOption(spec, rows)
    case "candlestick":
      return candlestickOption(spec, rows)
    default:
      return null
  }
}

function categoryValuePoints(spec: VisualizationSpec, rows: Row[]) {
  return rows
    .map((row) => ({
      label: String(row[spec.category_field] ?? ""),
      value: numeric(row[spec.value_field]),
    }))
    .filter((item): item is { label: string; value: number } => Boolean(item.label) && item.value !== null)
}

function barOption(spec: VisualizationSpec, rows: Row[]): EChartsCoreOption | null {
  const points = categoryValuePoints(spec, rows)
    .sort((left, right) => right.value - left.value)
    .slice(0, spec.max_items)
  if (!points.length) return null
  return {
    ...baseOption(),
    xAxis: categoryAxis(points.map((item) => item.label)),
    yAxis: valueAxis(),
    series: [{
      type: "bar",
      data: points.map((item) => item.value),
      barMaxWidth: 34,
      // 柱端胶囊圆角：竖柱只圆上端。
      itemStyle: { borderRadius: [99, 99, 0, 0], color: SERIES_LADDER[0] },
    }],
  }
}

function pieOption(spec: VisualizationSpec, rows: Row[]): EChartsCoreOption | null {
  const points = categoryValuePoints(spec, rows)
    .map((item) => ({ ...item, value: Math.max(item.value, 0) }))
    .sort((left, right) => right.value - left.value)
    .slice(0, spec.max_items)
  if (!points.length || !points.some((item) => item.value > 0)) return null
  return {
    ...baseOption(),
    legend: {
      bottom: 0,
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { ...axisText(), fontWeight: 400 },
    },
    series: [{
      type: "pie",
      radius: ["45%", "72%"],
      center: ["50%", "44%"],
      avoidLabelOverlap: true,
      label: { show: false },
      itemStyle: { borderColor: PAPER, borderWidth: 2 },
      data: points.map((item) => ({ name: item.label, value: item.value })),
    }],
  }
}

function lineOption(spec: VisualizationSpec, rows: Row[], area: boolean): EChartsCoreOption | null {
  const points = categoryValuePoints(spec, rows).slice(-spec.max_items)
  if (points.length < 2) return null
  return {
    ...baseOption(),
    xAxis: categoryAxis(points.map((item) => item.label)),
    yAxis: { ...valueAxis(), scale: true },
    tooltip: { ...TOOLTIP, trigger: "axis" },
    series: [{
      type: "line",
      data: points.map((item) => item.value),
      // 发丝线 + 小数据点，面积图用低透明填充。
      lineStyle: { width: 1.2, color: SERIES_LADDER[0] },
      itemStyle: { color: SERIES_LADDER[0] },
      symbol: "circle",
      symbolSize: 4,
      areaStyle: area ? { color: SERIES_LADDER[0], opacity: 0.12 } : undefined,
    }],
  }
}

function scatterOption(spec: VisualizationSpec, rows: Row[]): EChartsCoreOption | null {
  const points = rows
    .map((row) => [numeric(row[spec.category_field]), numeric(row[spec.value_field])])
    .filter((pair): pair is [number, number] => pair[0] !== null && pair[1] !== null)
    .slice(0, spec.max_items)
  if (!points.length) return null
  return {
    ...baseOption(),
    xAxis: { ...valueAxis(), scale: true, name: spec.category_field, nameTextStyle: axisText() },
    yAxis: { ...valueAxis(), scale: true, name: spec.value_field, nameTextStyle: axisText() },
    series: [{
      type: "scatter",
      data: points,
      symbolSize: 7,
      itemStyle: { color: SERIES_LADDER[0], opacity: 0.85 },
    }],
  }
}

function heatmapOption(spec: VisualizationSpec, rows: Row[]): EChartsCoreOption | null {
  if (!spec.y_field) return null
  const xLabels: string[] = []
  const yLabels: string[] = []
  const cells: [number, number, number][] = []
  for (const row of rows.slice(0, spec.max_items * 4)) {
    const x = String(row[spec.category_field] ?? "")
    const y = String(row[spec.y_field] ?? "")
    const value = numeric(row[spec.value_field])
    if (!x || !y || value === null) continue
    let xi = xLabels.indexOf(x)
    if (xi < 0) { xi = xLabels.push(x) - 1 }
    let yi = yLabels.indexOf(y)
    if (yi < 0) { yi = yLabels.push(y) - 1 }
    cells.push([xi, yi, value])
  }
  if (!cells.length) return null
  const values = cells.map((cell) => cell[2])
  return {
    ...baseOption(),
    grid: { left: 12, right: 16, top: 18, bottom: 48, containLabel: true },
    xAxis: categoryAxis(xLabels),
    yAxis: categoryAxis(yLabels),
    visualMap: {
      min: Math.min(...values),
      max: Math.max(...values),
      calculable: false,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      itemWidth: 10,
      textStyle: { color: FAINT, fontSize: 10 },
      // 明度即数据：值越大墨色越深。
      inRange: { color: [GRID, SERIES_LADDER[0]] },
    },
    series: [{ type: "heatmap", data: cells, label: { show: false } }],
  }
}

function candlestickOption(spec: VisualizationSpec, rows: Row[]): EChartsCoreOption | null {
  const { open_field, high_field, low_field, close_field } = spec
  if (!open_field || !high_field || !low_field || !close_field) return null
  const points = rows
    .map((row) => ({
      label: String(row[spec.category_field] ?? ""),
      // ECharts K 线数据顺序：[open, close, low, high]
      values: [open_field, close_field, low_field, high_field].map((field) => numeric(row[field])),
    }))
    .filter((item) => item.label && item.values.every((value) => value !== null))
    .slice(-spec.max_items) as { label: string; values: number[] }[]
  if (!points.length) return null
  return {
    ...baseOption(),
    xAxis: categoryAxis(points.map((item) => item.label)),
    yAxis: { ...valueAxis(), scale: true },
    tooltip: { ...TOOLTIP, trigger: "axis" },
    series: [{
      type: "candlestick",
      data: points.map((item) => item.values),
      itemStyle: {
        color: UP_COLOR,
        color0: DOWN_COLOR,
        borderColor: UP_COLOR,
        borderColor0: DOWN_COLOR,
      },
    }],
  }
}
