import { apiRequest } from "@/api/client";
import type { MetadataPage } from "@/api/tables";

// 结构变更记录接口，契约见后端 app/schemas/metadata_queries.py::ChangeOut。
export interface SchemaChange {
  id: number;
  urn: string;
  table_urn: string | null;
  asset_type: string | null;
  change_type: string;
  before_value: Record<string, unknown> | null;
  after_value: Record<string, unknown> | null;
  rename_candidate: string | null;
  rename_status: string | null;
  detected_at: string | null;
}

export function listChanges(params: {
  tableUrn?: string;
  urn?: string;
  page: number;
  pageSize: number;
}): Promise<MetadataPage<SchemaChange>> {
  return apiRequest<MetadataPage<SchemaChange>>("/changes", {
    params: {
      table_urn: params.tableUrn,
      urn: params.urn,
      page: params.page,
      page_size: params.pageSize,
    },
  });
}
