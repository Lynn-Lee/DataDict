import { apiRequest } from "@/api/client";
import type { MetadataPage } from "@/api/tables";

// 数据源接口，契约见后端 app/schemas/metadata_queries.py::DataSourceOut
// 与 app/schemas/datasource_admin.py。密码密文永不出现在响应中。
export interface ScopeRule {
  db?: string;
  table?: string;
}

export interface DataSource {
  id: number;
  code: string;
  name: string;
  db_type: string;
  env: string;
  host: string;
  port: number;
  default_db: string | null;
  group_name: string | null;
  enabled: boolean;
  username: string;
  sync_cron: string | null;
  last_sync_at: string | null;
  include_rules: ScopeRule[];
  exclude_rules: ScopeRule[];
}

export interface DataSourcePayload {
  code: string;
  name: string;
  db_type: string;
  env: string;
  host: string;
  port: number;
  default_db?: string | null;
  username: string;
  password?: string | null;
  include_rules: ScopeRule[];
  exclude_rules: ScopeRule[];
  sync_cron: string;
  group_name?: string | null;
  enabled: boolean;
}

export interface ConnectionTestResult {
  ok: boolean;
  message: string;
}

export function listDataSources(page = 1, pageSize = 100): Promise<MetadataPage<DataSource>> {
  return apiRequest<MetadataPage<DataSource>>("/datasources", {
    params: { page, page_size: pageSize },
  });
}

export function createDataSource(payload: DataSourcePayload): Promise<DataSource> {
  return apiRequest<DataSource>("/datasources", { method: "POST", body: payload });
}

export function updateDataSource(id: number, payload: DataSourcePayload): Promise<DataSource> {
  return apiRequest<DataSource>(`/datasources/${id}`, { method: "PUT", body: payload });
}

export function testDataSourceConnection(id: number): Promise<ConnectionTestResult> {
  return apiRequest<ConnectionTestResult>(`/datasources/${id}/test`, { method: "POST" });
}

export function triggerDataSourceSync(id: number): Promise<{ started: boolean }> {
  return apiRequest<{ started: boolean }>(`/datasources/${id}/sync`, { method: "POST" });
}
