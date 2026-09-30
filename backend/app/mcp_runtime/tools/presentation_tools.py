from __future__ import annotations

from typing import Annotated

from pydantic import Field

from ..schemas import ChartSpecResult


Title = Annotated[str, Field(description="简洁、明确的图表标题", min_length=1, max_length=80)]
SourceTaskId = Annotated[
    str,
    Field(description="数据来源任务ID，必须来自当前可用数据上下文", min_length=1, max_length=64),
]
FieldName = Annotated[
    str,
    Field(description="查询结果中真实存在的字段名", min_length=1, max_length=128),
]
MaxItems = Annotated[int, Field(description="最多展示的数据项数", ge=3, le=30)]


def build_bar_chart(
    title: Title,
    source_task_id: SourceTaskId,
    category_field: FieldName,
    value_field: FieldName,
    max_items: MaxItems = 12,
) -> ChartSpecResult:
    """生成柱状图展示配置，用于比较不同类别的数值大小。"""
    return ChartSpecResult(
        type="bar",
        title=title,
        source_task_id=source_task_id,
        category_field=category_field,
        value_field=value_field,
        max_items=max_items,
    )


def build_pie_chart(
    title: Title,
    source_task_id: SourceTaskId,
    category_field: FieldName,
    value_field: FieldName,
    max_items: MaxItems = 8,
) -> ChartSpecResult:
    """生成饼图展示配置，用于展示少量类别之间的占比构成。"""
    return ChartSpecResult(
        type="pie",
        title=title,
        source_task_id=source_task_id,
        category_field=category_field,
        value_field=value_field,
        max_items=max_items,
    )


def build_line_chart(
    title: Title,
    source_task_id: SourceTaskId,
    category_field: FieldName,
    value_field: FieldName,
    max_items: MaxItems = 30,
) -> ChartSpecResult:
    """生成折线图展示配置，用于展示指标随日期等有序序列的变化趋势。"""
    return ChartSpecResult(
        type="line",
        title=title,
        source_task_id=source_task_id,
        category_field=category_field,
        value_field=value_field,
        max_items=max_items,
    )


def build_area_chart(
    title: Title,
    source_task_id: SourceTaskId,
    category_field: FieldName,
    value_field: FieldName,
    max_items: MaxItems = 30,
) -> ChartSpecResult:
    """生成面积图展示配置，用于强调单序列总量随有序序列的变化。"""
    return ChartSpecResult(
        type="area",
        title=title,
        source_task_id=source_task_id,
        category_field=category_field,
        value_field=value_field,
        max_items=max_items,
    )


def build_scatter_chart(
    title: Title,
    source_task_id: SourceTaskId,
    category_field: FieldName,
    value_field: FieldName,
    max_items: MaxItems = 30,
) -> ChartSpecResult:
    """生成散点图展示配置，category_field 与 value_field 均为数值字段，用于观察两个数值维度的关系。"""
    return ChartSpecResult(
        type="scatter",
        title=title,
        source_task_id=source_task_id,
        category_field=category_field,
        value_field=value_field,
        max_items=max_items,
    )


def build_heatmap(
    title: Title,
    source_task_id: SourceTaskId,
    category_field: FieldName,
    y_field: FieldName,
    value_field: FieldName,
    max_items: MaxItems = 30,
) -> ChartSpecResult:
    """生成热力图展示配置，用于展示两个离散维度交叉后的数值大小。"""
    return ChartSpecResult(
        type="heatmap",
        title=title,
        source_task_id=source_task_id,
        category_field=category_field,
        y_field=y_field,
        value_field=value_field,
        max_items=max_items,
    )


def build_candlestick_chart(
    title: Title,
    source_task_id: SourceTaskId,
    category_field: FieldName,
    open_field: FieldName,
    high_field: FieldName,
    low_field: FieldName,
    close_field: FieldName,
    max_items: MaxItems = 30,
) -> ChartSpecResult:
    """生成K线图展示配置，用于展示OHLC四值行情；category_field 为日期字段。"""
    return ChartSpecResult(
        type="candlestick",
        title=title,
        source_task_id=source_task_id,
        category_field=category_field,
        open_field=open_field,
        high_field=high_field,
        low_field=low_field,
        close_field=close_field,
        # 契约为 OHLC 四字段，value_field 仅用于满足展示层结构。
        value_field=close_field,
        max_items=max_items,
    )
