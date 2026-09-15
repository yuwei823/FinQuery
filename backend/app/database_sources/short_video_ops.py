from __future__ import annotations


DATABASE_ID = "short_video_ops"

SYNONYMS: dict[str, list[str]] = {
    # 用户增长
    "short_video_ops.user_profiles.region": ["地区", "区域", "大区"],
    "short_video_ops.user_registrations.registration_id": [
        "注册数", "注册量", "注册人数", "新增注册用户数",
    ],
    "short_video_ops.user_registrations.registered_at": ["注册时间", "注册日期"],
    "short_video_ops.user_activations.is_activated": [
        "激活用户", "激活人数", "有效激活", "激活率",
    ],
    "short_video_ops.user_retention.is_retained": [
        "留存用户", "留存人数", "留存率",
    ],
    "short_video_ops.user_retention.retention_day": [
        "留存周期", "次留", "七留", "D1留存", "D7留存",
    ],
    "short_video_ops.user_daily_activity.active_minutes": ["活跃时长", "活跃分钟数"],
    "short_video_ops.user_daily_activity.session_count": ["会话数", "访问次数"],
    "short_video_ops.user_churn_events.inactive_days": ["不活跃天数", "沉默天数"],
    "short_video_ops.user_lifecycle_snapshots.engagement_score": [
        "参与度评分", "活跃度评分", "用户参与度",
    ],

    # 增长汇总指标
    "short_video_ops.growth_daily_metrics.metric_date": [
        "指标日期", "统计日期", "日期", "月份",
    ],
    "short_video_ops.growth_daily_metrics.new_users": [
        "新增用户", "新增用户数", "拉新人数", "新增人数",
    ],
    "short_video_ops.growth_daily_metrics.activated_users": [
        "激活用户", "激活用户数", "激活人数",
    ],
    "short_video_ops.growth_daily_metrics.day1_retained_users": [
        "次日留存用户", "次留用户", "D1留存用户",
    ],
    "short_video_ops.growth_daily_metrics.day7_retained_users": [
        "七日留存用户", "7日留存用户", "七留用户", "D7留存用户",
    ],
    "short_video_ops.growth_daily_metrics.daily_active_users": [
        "每日活跃用户", "日活用户", "日活", "DAU",
    ],

    # 渠道投放
    "short_video_ops.acquisition_channels.channel_name": [
        "渠道", "投放渠道", "获客渠道", "渠道名称",
    ],
    "short_video_ops.ad_campaigns.objective": ["投放目标", "广告目标", "计划目标"],
    "short_video_ops.ad_campaigns.budget": ["预算", "广告预算", "投放预算"],
    "short_video_ops.ad_daily_stats.stat_date": [
        "投放日期", "广告统计日期", "统计日期", "日期", "月份",
    ],
    "short_video_ops.ad_daily_stats.impressions": [
        "曝光", "曝光量", "曝光次数", "展示量",
    ],
    "short_video_ops.ad_daily_stats.clicks": ["点击", "点击量", "点击次数"],
    "short_video_ops.ad_daily_stats.conversions": [
        "转化", "转化数", "转化量", "转化次数",
    ],
    "short_video_ops.ad_daily_stats.spend": [
        "消耗", "广告消耗", "投放消耗", "投放费用", "广告花费",
    ],
    "short_video_ops.ad_daily_stats.click_through_rate": ["点击率", "CTR"],
    "short_video_ops.ad_daily_stats.cost_per_conversion": [
        "转化成本", "单次转化成本", "CPA",
    ],
    "short_video_ops.channel_conversion_events.conversion_event_id": [
        "转化事件数", "转化事件数量",
    ],
    "short_video_ops.channel_conversion_events.conversion_value": [
        "转化价值", "转化金额", "平均转化价值",
    ],

    # 内容运营
    "short_video_ops.content_categories.category_name": [
        "内容分类", "内容类别", "内容品类", "视频分类",
    ],
    "short_video_ops.contents.content_id": ["内容数", "内容数量", "视频数", "作品数"],
    "short_video_ops.ad_creatives.creative_id": ["创意数", "创意数量", "广告创意数"],
    "short_video_ops.content_daily_metrics.metric_date": [
        "内容统计日期", "指标日期", "日期", "月份",
    ],
    "short_video_ops.content_daily_metrics.play_count": [
        "播放量", "播放数", "播放次数",
    ],
    "short_video_ops.content_daily_metrics.watch_seconds": [
        "观看时长", "播放时长", "总观看时长",
    ],
    "short_video_ops.content_daily_metrics.interaction_count": [
        "互动量", "互动数", "互动次数",
    ],
    "short_video_ops.content_daily_metrics.play_rate": ["播放率", "曝光播放率"],
    "short_video_ops.content_daily_metrics.completion_rate": ["完播率", "播放完成率"],
    "short_video_ops.video_interactions.interaction_id": [
        "互动数", "互动量", "互动行为数",
    ],
    "short_video_ops.video_interactions.valid_interaction": ["有效互动", "有效互动数"],
    "short_video_ops.creator_profiles.follower_count": ["粉丝数", "粉丝数量"],
    "short_video_ops.creator_daily_metrics.published_count": [
        "发布量", "发布数", "发布内容数",
    ],
    "short_video_ops.creator_daily_metrics.interaction_rate": ["互动率", "创作者互动率"],
    "short_video_ops.trending_topics.heat_score": ["话题热度", "热度", "热度分"],
}
