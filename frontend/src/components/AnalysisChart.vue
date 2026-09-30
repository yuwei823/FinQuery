<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"

import { buildChartOption, chartTypeLabel } from "../charts/buildOption"
import { echarts } from "../charts/echarts"
import { ensureFinQueryTheme } from "../charts/theme"
import type { ReportDataSource, VisualizationSpec } from "../types"

const props = defineProps<{
  spec: VisualizationSpec
  sources: ReportDataSource[]
}>()

const host = ref<HTMLElement | null>(null)
let chart: ReturnType<typeof echarts.init> | null = null

const source = computed(() => props.sources.find((item) => item.taskId === props.spec.source_task_id))
const option = computed(() => buildChartOption(props.spec, source.value?.rows ?? []))

const fieldHint = computed(() => {
  const fields = [
    props.spec.category_field,
    props.spec.value_field,
    props.spec.y_field,
    props.spec.open_field,
    props.spec.high_field,
    props.spec.low_field,
    props.spec.close_field,
  ].filter((field): field is string => Boolean(field))
  return [...new Set(fields)].join(" × ")
})

function render() {
  if (!host.value || !option.value) return
  if (!chart) chart = echarts.init(host.value, ensureFinQueryTheme())
  chart.setOption(option.value, true)
}

function resize() {
  chart?.resize()
}

onMounted(() => {
  render()
  window.addEventListener("resize", resize)
})

watch(option, () => {
  if (!option.value) {
    chart?.clear()
    return
  }
  render()
})

onBeforeUnmount(() => {
  window.removeEventListener("resize", resize)
  chart?.dispose()
  chart = null
})
</script>

<template>
  <section class="analysis-chart">
    <header>
      <div><small>{{ chartTypeLabel(spec.type) }}</small><strong>{{ spec.title }}</strong></div>
      <span>{{ fieldHint }}</span>
    </header>
    <div v-if="!option" class="chart-empty">找不到该图表引用的数据或数值字段。</div>
    <div v-show="option" ref="host" class="chart-host"></div>
  </section>
</template>
