import { apiRequest } from "@/api/client";
import type { MetadataPage } from "@/api/tables";

// 标准字段定义接口，契约见后端 app/schemas/standard_fields.py。
export type StandardFieldStatus = "DRAFT" | "CONFIRMED" | "DEPRECATED";

export interface SimilarStandard {
  id: number;
  standard_name: string;
  raw_type: string | null;
  business_meaning: string | null;
  matched_by: "NAME" | "ALIAS" | "MEANING";
  score: number;
}

export interface StandardField {
  id: number;
  standard_name: string;
  cluster_key: string | null;
  // 非空 = 通用字段名按注释释义拆出来的分组，同名可能并存多条不同概念
  sub_key: string;
  merged_into_id: number | null;
  business_meaning: string | null;
  logical_type: string;
  raw_type: string | null;
  status: StandardFieldStatus;
  source_type: string;
  has_conflict: boolean;
  type_distribution: Record<string, number> | null;
  candidate_count: number;
  doc_count: number;
  version: number;
  similar_standards: SimilarStandard[];
}

export interface StandardFieldItem {
  column_urn: string;
  db_name: string | null;
  table_name: string | null;
  column_name: string | null;
  raw_type: string | null;
  logical_type: string | null;
  conforms: boolean | null;
}

export interface StandardFieldDetail extends StandardField {
  items: StandardFieldItem[];
}

export interface GenerateSummary {
  generated: number;
  updated: number;
  skipped_confirmed: number;
  skipped_conflict: number;
}

export interface ConfirmPayload {
  standard_name?: string;
  raw_type: string;
  logical_type: string;
  business_meaning: string;
}

export interface ListStandardFieldsParams {
  status?: StandardFieldStatus;
  conflict?: boolean;
  q?: string;
  page: number;
  pageSize: number;
}

export function listStandardFields(
  params: ListStandardFieldsParams,
): Promise<MetadataPage<StandardField>> {
  return apiRequest<MetadataPage<StandardField>>("/standard-fields", {
    params: {
      status: params.status,
      conflict: params.conflict,
      q: params.q,
      page: params.page,
      page_size: params.pageSize,
    },
  });
}

export function getStandardField(id: number): Promise<StandardFieldDetail> {
  return apiRequest<StandardFieldDetail>(`/standard-fields/${id}`);
}

export function confirmStandardField(id: number, payload: ConfirmPayload): Promise<StandardField> {
  return apiRequest<StandardField>(`/standard-fields/${id}/confirm`, {
    method: "POST",
    body: payload,
  });
}

export function generateStandardFields(): Promise<GenerateSummary> {
  return apiRequest<GenerateSummary>("/standard-fields/generate", { method: "POST" });
}

// 关联（合并）到已有标准：候选的存量字段迁到目标下，候选置 MERGED，
// 来源字段名记为目标的业务别名。用于避免标准库出现两个同义标准。
export function mergeStandardField(sourceId: number, targetId: number): Promise<StandardField> {
  return apiRequest<StandardField>(`/standard-fields/${sourceId}/merge-into/${targetId}`, {
    method: "POST",
  });
}

// ── 终版标准定义库（含业务标签） ──

export interface StandardFieldTag {
  id: number;
  name: string;
}

export interface StandardFieldLibraryItem extends StandardField {
  tags: StandardFieldTag[];
}

export function listStandardLibrary(params: {
  q?: string;
  page: number;
  pageSize: number;
}): Promise<MetadataPage<StandardFieldLibraryItem>> {
  return apiRequest<MetadataPage<StandardFieldLibraryItem>>("/standard-fields/library", {
    params: { q: params.q, page: params.page, page_size: params.pageSize },
  });
}

export function listTagOptions(): Promise<string[]> {
  return apiRequest<string[]>("/standard-fields/tag-options");
}

export function attachTag(id: number, name: string): Promise<StandardFieldTag[]> {
  return apiRequest<StandardFieldTag[]>(`/standard-fields/${id}/tags`, {
    method: "POST",
    body: { name },
  });
}

export function detachTag(id: number, tagId: number): Promise<StandardFieldTag[]> {
  return apiRequest<StandardFieldTag[]>(`/standard-fields/${id}/tags/${tagId}`, {
    method: "DELETE",
  });
}
