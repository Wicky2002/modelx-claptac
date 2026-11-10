export interface Provenance { dataset: string; dataset_version: string | null; split: string; seed: number | null; generated_at: string | null; source: string }
export interface Profile extends Provenance {
  schema_version: 1; label_unit: string; labels: { label: string; count: number }[];
  flood_pixels: { flood: number; non_flood: number; ignored: number } | null;
  relationships: { x_label: string; y_label: string; x_unit: string | null; y_unit: string | null; method: string; total_pairs: number; bins: { x: number; y: number; count: number }[] }[];
  notes: string[];
}
export interface DatasetCard { key: string; name: string; version: string; coverage: string; label_meaning: string; missingness: string; licence: string; limits: string[]; verified: boolean; verification: string; splits: { name: string; count: number; unit: string; tiles: number | null }[] }
export interface Evaluation extends Provenance { file: string; model_version: string | null; tiles: number; variants: { name: string; metrics: Record<string, number | null>; events: number; threshold: number | null }[] }
export interface DataReview { mode: string; as_of: string; cards: DatasetCard[]; profiles: Profile[]; evaluations: Evaluation[]; warnings: string[] }
export interface Model { name: string; version: string; status: string; task: string; dataset_versions: Record<string, string>; metrics: Record<string, number | null>; operating_threshold: number | null; registered_at: string; updated_at: string }
export interface Drift { version?: string; status: string; samples?: number; drifted: boolean | null; features?: Record<string, { shift_std: number | null; missing_rate: number; drifted: boolean }> }
export interface ModelsReview {
  mode: string; as_of: string; registry_available: boolean; learning_available: boolean; models: Model[];
  reviews: { name: string; drift: Drift; shadows: { version: string; runs: number; errors: number; compared_with_live: number; mean_abs_difference: number | null }[] }[];
  history: { name: string; version: string; phase: string; at: string; from?: string; to?: string; actor?: string; reason?: string }[];
  requests: { action: { action_type: string; params: Record<string, unknown>; idempotency_key: string }; decision: { status: string; reason: string; approval_id: string | null } }[];
}
