import { apiRequest } from "@/api/client";

// 表详情 / 字段 / DDL 接口，契约见后端 app/schemas/metadata_queries.py。
export interface TableDetail {
  urn: string;
  source_id: number;
  db_name: string;
  table_name: string;
  table_type: string;
  table_comment: string | null;
  row_count: number | null;
  data_size: number | null;
  dw_layer: string | null;
  is_deleted: boolean;
}

export interface ColumnMeta {
  urn: string;
  table_urn: string;
  source_id: number | null;
  db_name: string | null;
  table_name: string | null;
  column_name: string;
  ordinal: number;
  raw_type: string;
  logical_type: string;
  raw_comment: string | null;
  is_nullable: boolean;
  is_primary_key: boolean;
  is_deleted: boolean;
  business_meaning: string | null;
  effective_type: string | null;
  effective_domain_id: number | null;
  domain_name: string | null;
}

export interface MetadataPage<T> {
  total: number;
  page: number;
  page_size: number;
  items: T[];
}

export interface TableDdl {
  urn: string;
  ddl: string;
  total: number;
}

export function getTable(urn: string): Promise<MetadataPage<TableDetail>> {
  return apiRequest<MetadataPage<TableDetail>>("/tables", { params: { urn } });
}

export function listColumns(
  tableUrn: string,
  page: number,
  pageSize: number,
): Promise<MetadataPage<ColumnMeta>> {
  return apiRequest<MetadataPage<ColumnMeta>>("/columns", {
    params: { table_urn: tableUrn, page, page_size: pageSize },
  });
}

export function getTableDdl(urn: string): Promise<TableDdl> {
  return apiRequest<TableDdl>("/tables/ddl", { params: { urn } });
}

export interface ListTablesParams {
  sourceId?: number;
  dbName?: string;
  keyword?: string;
  page: number;
  pageSize: number;
}

// 不传 urn 时分页返回表列表，可按数据源 / 库名（精确）/ 关键词（表名或注释）筛选。
export function listTables(params: ListTablesParams): Promise<MetadataPage<TableDetail>> {
  return apiRequest<MetadataPage<TableDetail>>("/tables", {
    params: {
      source_id: params.sourceId,
      db_name: params.dbName,
      keyword: params.keyword,
      page: params.page,
      page_size: params.pageSize,
    },
  });
}
