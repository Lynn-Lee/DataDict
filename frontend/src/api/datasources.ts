import { apiRequest } from "@/api/client";
import type { MetadataPage } from "@/api/tables";

// 数据源列表接口，契约见后端 app/schemas/metadata_queries.py::DataSourceOut。
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
}

export function listDataSources(page = 1, pageSize = 100): Promise<MetadataPage<DataSource>> {
  return apiRequest<MetadataPage<DataSource>>("/datasources", {
    params: { page, page_size: pageSize },
  });
}
