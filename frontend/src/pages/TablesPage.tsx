import { useQuery } from "@tanstack/react-query";
import { Card, Input, Select, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { listDataSources } from "@/api/datasources";
import { listTables, type TableDetail } from "@/api/tables";
import { EmptyState, ErrorState } from "@/components/QueryStates";
import { formatBytes, formatCount } from "@/utils/format";

const PAGE_SIZE = 20;
const DEBOUNCE_MS = 300;

function useDebouncedValue<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

const COLUMNS: ColumnsType<TableDetail> = [
  {
    title: "表名",
    dataIndex: "table_name",
    render: (_, row) => (
      <Link to={`/tables/${encodeURIComponent(row.urn)}`}>
        <Typography.Text strong>{row.table_name}</Typography.Text>
      </Link>
    ),
  },
  { title: "库", dataIndex: "db_name", width: 140 },
  {
    title: "类型",
    dataIndex: "table_type",
    width: 90,
    render: (value: string) => <Tag>{value}</Tag>,
  },
  {
    title: "注释",
    dataIndex: "table_comment",
    ellipsis: true,
    render: (value: string | null) => value || <Typography.Text type="secondary">—</Typography.Text>,
  },
  {
    title: "行数",
    dataIndex: "row_count",
    width: 120,
    align: "right",
    render: (value: number | null) => formatCount(value),
  },
  {
    title: "大小",
    dataIndex: "data_size",
    width: 100,
    align: "right",
    render: (value: number | null) => formatBytes(value),
  },
];

export default function TablesPage() {
  const [page, setPage] = useState(1);
  const [sourceId, setSourceId] = useState<number | undefined>();
  const [dbInput, setDbInput] = useState("");
  const [keywordInput, setKeywordInput] = useState("");

  const dbName = useDebouncedValue(dbInput, DEBOUNCE_MS).trim() || undefined;
  const keyword = useDebouncedValue(keywordInput, DEBOUNCE_MS).trim() || undefined;

  // 筛选条件变化时回到第一页。
  useEffect(() => {
    setPage(1);
  }, [sourceId, dbName, keyword]);

  const sources = useQuery({ queryKey: ["datasources"], queryFn: () => listDataSources() });
  const tables = useQuery({
    queryKey: ["tables", sourceId, dbName, keyword, page],
    queryFn: () => listTables({ sourceId, dbName, keyword, page, pageSize: PAGE_SIZE }),
    placeholderData: (previous) => previous,
  });

  return (
    <Card>
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Space wrap>
          <Select
            allowClear
            placeholder="全部数据源"
            style={{ width: 240 }}
            loading={sources.isLoading}
            value={sourceId}
            onChange={setSourceId}
            options={(sources.data?.items ?? []).map((source) => ({
              value: source.id,
              label: source.name,
            }))}
          />
          <Input
            allowClear
            placeholder="库名（精确匹配）"
            style={{ width: 180 }}
            value={dbInput}
            onChange={(event) => setDbInput(event.target.value)}
          />
          <Input.Search
            allowClear
            placeholder="表名或注释关键词"
            style={{ width: 260 }}
            value={keywordInput}
            onChange={(event) => setKeywordInput(event.target.value)}
          />
        </Space>
        {tables.isError ? (
          <ErrorState
            error={tables.error}
            onRetry={() => void tables.refetch()}
            forbiddenMessage="无权限访问表目录"
            errorMessage="表目录加载失败"
          />
        ) : (
          <Table<TableDetail>
            rowKey="urn"
            size="middle"
            columns={COLUMNS}
            dataSource={tables.data?.items ?? []}
            loading={tables.isLoading}
            locale={{ emptyText: <EmptyState simple={false} description="没有符合条件的表" /> }}
            pagination={{
              current: tables.data?.page ?? page,
              pageSize: PAGE_SIZE,
              total: tables.data?.total ?? 0,
              showSizeChanger: false,
              showTotal: (total) => `共 ${total} 张表`,
              onChange: setPage,
            }}
          />
        )}
      </Space>
    </Card>
  );
}
