export interface PublicConfig {
  assistant_enabled: boolean
  ecg_external_url: string | null
  demo_mode: boolean
}

export interface UserProfile {
  id: string
  account: string
  nickname: string
  bio: string
  timezone: string
  roles: string[]
  is_demo: boolean
  created_at: string
  csrf_token?: string
}

export interface PublicUserProfile {
  id: string
  nickname: string
  bio: string
  is_demo: boolean
  created_at: string
  recent_posts: Array<{
    id: string
    title: string
    category: string
    created_at: string
  }>
}

export type MoodValue = 'very_good' | 'good' | 'neutral' | 'bad' | 'very_bad'

export interface JournalEntry {
  id?: string
  date?: string
  local_date?: string
  recorded?: boolean
  sleep_minutes: number | null
  activity_minutes: number | null
  mood: MoodValue | null
  symptom_tags?: string[]
  tags?: string[]
  note?: string | null
  is_demo?: boolean
  updated_at?: string
}

export interface PlanTemplate {
  key?: string
  template_key?: string
  title: string
  weekdays?: number[]
  weekday_mask?: number
  reminder_enabled?: boolean
  reminder_time?: string | null
}

export interface PlanItem {
  id: string
  plan_id?: string
  title: string
  template_key?: string | null
  active: boolean
  weekdays?: number[]
  weekday_mask?: number
  reminder_enabled: boolean
  reminder_time: string | null
  streak_days?: number
  current_streak?: number
  streak?: number
  completed?: boolean
  is_demo?: boolean
}

export interface TodayItem {
  plan_id: string
  id?: string
  title: string
  completed: boolean
  reminder_enabled?: boolean
  reminder_time?: string | null
  streak_days?: number
  current_streak?: number
  streak?: number
}

export interface DashboardData {
  today_date: string
  plans_summary: {
    due_count: number
    completed_count: number
    items: TodayItem[]
  }
  today_journal: {
    recorded: boolean
    sleep_minutes: number | null
    activity_minutes: number | null
    mood: MoodValue | null
  }
  recent_journals?: JournalEntry[]
  weekly_snapshot?: {
    sleep_mean_minutes?: number | null
    activity_total_minutes?: number | null
    completion_rate?: number | null
  }
  recommended_articles: ArticleSummary[]
  community_highlights: PostSummary[]
  unread_notifications_count: number
}

export interface PostAuthor {
  id: string
  nickname: string
  is_demo?: boolean
}

export interface PostSummary {
  id: string
  title: string
  category: string
  excerpt?: string
  body?: string
  tags?: string[]
  author?: PostAuthor
  author_id?: string
  author_nickname?: string
  is_demo?: boolean
  status?: string
  moderation_reason?: string | null
  like_count?: number
  likes_count?: number
  comment_count?: number
  comments_count?: number
  viewer_liked?: boolean
  liked?: boolean
  viewer_bookmarked?: boolean
  bookmarked?: boolean
  created_at: string
  updated_at?: string
}

export interface PostDetail extends PostSummary {
  body: string
  safety_notice?: string | null
  viewer_liked?: boolean
  liked?: boolean
  viewer_bookmarked?: boolean
  bookmarked?: boolean
  version?: number
}

export interface CommentItem {
  id: string
  post_id: string
  parent_id: string | null
  body: string
  author?: PostAuthor
  author_id?: string
  author_nickname?: string
  status?: string
  created_at: string
  replies?: CommentItem[]
}

export interface ArticleSource {
  title: string
  url: string
  accessed_at?: string
}

export interface ArticleReviewRecord {
  reviewer: string
  review_type: string
  reviewed_at: string
  note?: string
}

export interface ArticleSummary {
  id: string
  slug?: string | null
  title: string
  summary: string
  category: string
  author_byline?: string
  status?: string
  revision?: number
  is_demo?: boolean
  published_at?: string | null
  updated_at?: string
}

export interface ArticleDetail extends ArticleSummary {
  body: string
  author_byline: string
  scope_note: string
  sources: ArticleSource[]
  review_record: ArticleReviewRecord | null
  revision: number
  viewer_bookmarked?: boolean
  bookmarked?: boolean
}

export interface WeeklyReportDailyPoint {
  date: string
  sleep_minutes: number | null
  activity_minutes: number | null
  mood: MoodValue | null
  plans_due?: number
  plans_completed?: number
  due_count?: number
  completed_count?: number
}

export interface WeeklyReportData {
  week_start: string
  week_end: string
  status: 'partial_week' | 'completed_week' | string
  journal_days?: number
  observed_days?: number
  coverage?: {
    journal_days: number
    observed_days: number
  }
  sleep: {
    mean_minutes: number | null
    valid_days: number
  }
  activity: {
    total_minutes: number | null
    valid_days: number
  }
  plans: {
    due: number
    completed: number
    completion_rate: number | null
  }
  daily_series: WeeklyReportDailyPoint[]
}

export interface ChallengeItem {
  id: string
  slug: string
  title: string
  description: string
  rule_type: string
  target_days: number
  start_date: string
  end_date: string
  badge_title: string
  joined?: boolean
  progress_days?: number
  completed_days?: number
  achieved?: boolean
  is_demo?: boolean
}

export interface UserChallengeProgress {
  challenge_id: string
  id?: string
  title?: string
  status?: string
  progress_days?: number
  completed_days?: number
  target_days?: number
  achieved?: boolean
  badge_title?: string
  achieved_date?: string | null
}

export interface AssistantCitation {
  id: string
  title: string
  category?: string
}

export interface AssistantChatResponse {
  answer: string
  mode: string
  citations: AssistantCitation[]
  tools_used?: string[]
  fallback_url?: string
}

export interface NotificationItem {
  id: string
  type: string
  target_type: string
  target_id: string
  summary: string
  read_at: string | null
  created_at: string
  target_available?: boolean
}

export interface FamilyGrantItem {
  id: string
  granter_id: string
  granter_nickname?: string
  viewer_id: string
  viewer_nickname?: string
  status: string
  share_plan_summary: boolean
  share_weekly_sleep: boolean
  share_weekly_activity: boolean
  created_at?: string
}

export interface ModerationReportItem {
  id: string
  reporter_id?: string
  target_type: 'post' | 'comment' | string
  target_id: string
  reason: string
  detail: string
  status: 'pending' | 'actioned' | 'dismissed' | string
  target_preview?: string
  target_title?: string
  target_body?: string
  resolution_note?: string | null
  created_at: string
  resolved_at?: string | null
}

export interface ModerationActionItem {
  id: string
  actor_id: string
  report_id?: string | null
  target_type: string
  target_id: string
  action: string
  reason: string
  created_at: string
}
