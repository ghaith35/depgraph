// Mirror of backend graph schema + D3 simulation fields

export interface Node {
  id: string;
  label: string;
  language: string;
  size: number; // LOC approximation
  is_cycle: boolean;
  cluster: string;
  parse_error?: boolean;
  is_outlier_hub?: boolean;
  // D3 simulation fields (mutated in place by the simulation)
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  fx?: number | null;
  fy?: number | null;
  index?: number;
}

export interface Edge {
  source: string | Node;
  target: string | Node;
  symbol: string | null;
  line: number;
  is_cycle: boolean;
  has_dynamic_target?: boolean;
  type?: string;
  index?: number;
}

export interface SetupSteps {
  runtime: string;
  install_cmd: string | null;
  build_cmd: string | null;
  run_cmd: string | null;
  env_vars: string[];
  notes: string[];
}

export interface Stats {
  file_count: number;
  total_size_bytes: number;
  total_loc?: number;
  languages: Record<string, number>;
  commit_sha: string;
  repo_url?: string;
  analysis_duration_ms: number;
}

export interface Progress {
  done: number;
  total: number;
  phase: string;
}
