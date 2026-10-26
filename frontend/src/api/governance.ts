import { apiRequest } from "@/api/client";
import type { MetadataPage } from "@/api/tables";

// 治理待办接口，契约见后端 app/schemas/governance.py。
export interface GovernanceTodo {
  id: number;
  column_urn: string;
  db_name: string | null;
  table_name: string | null;
  column_name: string | null;
  actual_type: string | null;
  standard_field_id: number | null;
  standard_name: string | null;
  expected_type: string | null;
  business_meaning: string | null;
  status: "OPEN" | "DONE" | "IGNORED";
  action: "ADOPT" | "EXEMPT" | "IGNORE" | null;
  reason: string | null;
  created_at: string | null;
  done_at: string | null;
}

export interface SweepSummary {
  attached_conforming: number;
  attached_conflicting: number;
  conforms_updated: number;
  todos_created: number;
}

export function sweepGovernance(): Promise<SweepSummary> {
  return apiRequest<SweepSummary>("/governance/sweep", { method: "POST" });
}

export function listGovernanceTodos(params: {
  status?: string;
  page: number;
  pageSize: number;
}): Promise<MetadataPage<GovernanceTodo>> {
  return apiRequest<MetadataPage<GovernanceTodo>>("/governance/todos", {
    params: { status: params.status, page: params.page, page_size: params.pageSize },
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
