import { apiRequest } from "@/api/client";
import type { MetadataPage } from "@/api/tables";

// 治理待办接口，契约见后端 app/schemas/governance.py。
// STANDARD_CONFLICT=字段类型与标准不一致（URN 是字段）；
// STANDARD_MISSING=该表仍有字段没关联已定版标准（URN 是表，按表聚合避免刷屏）。
export interface GovernanceGapColumn {
  column_name: string;
  raw_type: string | null;
  raw_comment: string | null;
  has_draft_candidate: boolean;
}

export interface GovernanceTodo {
  id: number;
  column_urn: string;
  todo_type: "STANDARD_CONFLICT" | "STANDARD_MISSING";
  db_name: string | null;
  table_name: string | null;
  column_name: string | null;
  actual_type: string | null;
  standard_field_id: number | null;
  standard_name: string | null;
  expected_type: string | null;
  business_meaning: string | null;
  missing_count: number | null;
  missing_columns: GovernanceGapColumn[];
  preview_truncated: boolean;
  status: "OPEN" | "DONE" | "IGNORED";
  action: "ADOPT" | "EXEMPT" | "IGNORE" | "AUTO_RESOLVED" | null;
  reason: string | null;
  created_at: string | null;
  done_at: string | null;
}

export interface SweepSummary {
  attached_conforming: number;
  attached_conflicting: number;
  conforms_updated: number;
  todos_created: number;
  reattached: number;
  detached: number;
  missing_todos_created: number;
  missing_todos_updated: number;
  missing_todos_closed: number;
  missing_tables: number;
  scope: string;
  clustered_generated: number;
  clustered_updated: number;
}

export function sweepGovernance(): Promise<SweepSummary> {
  return apiRequest<SweepSummary>("/governance/sweep", { method: "POST" });
}

export function listGovernanceTodos(params: {
  status?: string;
  todoType?: string;
  page: number;
  pageSize: number;
}): Promise<MetadataPage<GovernanceTodo>> {
  return apiRequest<MetadataPage<GovernanceTodo>>("/governance/todos", {
    params: {
      status: params.status,
      todo_type: params.todoType,
      page: params.page,
      page_size: params.pageSize,
    },
  });
}

export function resolveGovernanceTodo(
  id: number,
  action: "ADOPT" | "EXEMPT" | "IGNORE",
  reason?: string,
): Promise<GovernanceTodo> {
  return apiRequest<GovernanceTodo>(`/governance/todos/${id}/resolve`, {
    method: "POST",
    body: { action, reason },
  });
}
