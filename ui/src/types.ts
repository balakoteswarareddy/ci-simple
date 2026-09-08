export interface RunSummary {
  id: string;
  repo_url: string;
  platform: string;
  status: string;
  current_step: string;
  risk_level: string;
  created_at: string;
  updated_at: string;
  request: string;
}

export interface PolicyFinding {
  rule: string;
  message: string;
}

export interface PolicyDecision {
  decision: string;
  deny: PolicyFinding[];
  approval_reasons: PolicyFinding[];
  evaluator: string;
  evaluated_at: string;
}

export interface ValidationFinding {
  validator: string;
  level: string;
  message: string;
  file: string;
  line: number;
  remediation: string;
}

export interface ValidationResult {
  validator: string;
  version: string;
  passed: boolean;
  errors: ValidationFinding[];
  warnings: ValidationFinding[];
  provenance: Record<string, string>;
}

export interface RunDetail extends RunSummary {
  revision: string;
  request_full?: string;
  renderer: string;
  rendered_yaml: string;
  explanation: string;
  error: string;
  repair_attempts: number;
  options: Record<string, unknown>;
  context: Record<string, unknown>;
  intent: Record<string, unknown>;
  plan: Record<string, unknown>;
  policy: PolicyDecision;
  ir: Record<string, unknown>;
  validation: ValidationResult[];
  security: Record<string, unknown>;
  supply_chain: Record<string, unknown>;
  publish: Record<string, unknown>;
  costs: Record<string, unknown>[];
}

export interface RunEvent {
  seq: number;
  step: string;
  level: string;
  message: string;
  data: Record<string, unknown>;
  created_at: string;
}

export const TERMINAL = new Set(["succeeded", "failed", "denied", "cancelled"]);
