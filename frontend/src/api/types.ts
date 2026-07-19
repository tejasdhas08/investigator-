export interface User {
  id: string;
  email: string;
  full_name: string;
  role: "investigator" | "supervisor" | "admin";
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface CaseListItem {
  id: string;
  case_number: string;
  title: string;
  status: string;
  person_count_total: number | null;
  created_at: string;
}

export interface Case extends CaseListItem {
  context_description: string;
  failure_reason: string | null;
  narrative_json: NarrativeDoc | null;
  person_count_male: number | null;
  person_count_female: number | null;
  person_count_unknown_gender: number | null;
}

export interface CaseStatus {
  status: string;
  stage: string | null;
  stage_progress_pct: number | null;
  failure_reason: string | null;
}

export interface Video {
  id: string;
  media_type: "video" | "photo";
  original_filename: string;
  duration_seconds: number | null;
  quality_notes: string[] | null;
  stream_url: string | null;
}

export interface Person {
  id: string;
  label: string;
  display_alias: string | null;
  gender_estimate: "male" | "female" | "unknown";
  gender_confidence: number | null;
  gender_human_override: string | null;
  age_estimate_range: string | null;
  face_visible: boolean;
  detection_confidence_avg: number;
  appearance_description: string | null;
  activity_summary: string | null;
  first_seen_ms: number | null;
  last_seen_ms: number | null;
  presence_intervals: { video_id: string; start_ms: number; end_ms: number }[] | null;
  is_suspect_match: boolean;
  face_crop_url: string | null;
  body_crop_url: string | null;
}

export interface TimelineEvent {
  id: string;
  video_id: string;
  event_type: string;
  start_ms: number;
  end_ms: number;
  person_label: string | null;
  target_person_label: string | null;
  label: string;
  description: string | null;
  confidence: number;
  bbox: { x: number; y: number; w: number; h: number } | null;
  object_class: string | null;
  actor_direction: string | null;
  is_suspicious: boolean;
  requires_human_review: boolean;
  review_status: "unreviewed" | "approved" | "rejected" | "edited";
  human_note: string | null;
  evidence_frame_urls: string[];
}

export interface NarrativeSection {
  section_index: number;
  time_range_ms: [number, number];
  heading: string;
  text: string;
  cited_event_ids: string[];
}

export interface HypothesisClaim {
  claim: string;
  verdict: "supported" | "contradicted" | "unsupported" | "partially_supported";
  explanation: string;
  cited_event_ids: string[];
}

export interface HypothesisCheck {
  hypothesis_text: string;
  claims: HypothesisClaim[];
  overall: string;
}

export interface NarrativeDoc {
  overall_summary: string;
  narrative_sections: NarrativeSection[];
  person_summaries: { person_label: string; text: string; cited_event_ids: string[] }[];
  suspicious_activity_summary: {
    text: string;
    severity: "low" | "medium" | "high";
    cited_event_ids: string[];
    requires_human_review: boolean;
  }[];
  uncertainties: { text: string; related_event_ids: string[] }[];
  evidence_gaps: string[];
  hypothesis_check?: HypothesisCheck | null;
  disclaimer: string;
  human_edits?: { path: string; original_text: string; edited_text: string }[];
}

export interface ExplainSignal {
  label: string;
  value: string | number | boolean;
  detail: string | null;
}

export interface EventExplanation {
  event_id: string;
  confidence: number;
  requires_human_review: boolean;
  review_status: string;
  signals: ExplainSignal[];
}

export interface SuspectMatchResult {
  id: string;
  person_id: string;
  person_label: string | null;
  cosine_similarity: number;
  verdict: "match" | "possible_match" | "no_match";
  best_frame_ms: number | null;
  review_status: "unreviewed" | "confirmed" | "rejected";
  comparison_face_url: string | null;
}

export interface SuspectReference {
  id: string;
  display_name: string;
  photo_url: string | null;
  results: SuspectMatchResult[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: { event_id: string; start_ms: number; end_ms: number; confidence: number }[] | null;
  created_at: string;
}

export interface ExportReport {
  id: string;
  created_at: string;
  sha256: string | null;
  status: string;
  includes_chat: boolean;
}
