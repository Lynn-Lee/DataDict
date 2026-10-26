import { ArrowLeftOutlined, EditOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Card,
  Descriptions,
  Input,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  getFieldAnnotation,
  mergeAnnotationPayload,
  upsertFieldAnnotation,
  type FieldAnnotationOut,
} from "@/api/annotations";
import { ApiError } from "@/api/client";
import { EmptyState, ErrorState, LoadingState } from "@/components/QueryStates";
import { getTable, getTableDdl, listColumns, type ColumnMeta } from "@/api/tables";
import { listChanges, type SchemaChange } from "@/api/changes";
import { formatBytes, formatCount } from "@/utils/format";

const PAGE_SIZE = 50;

// 长文本单元格：截断 + Tooltip，避免撑破固定列宽。
function EllipsisCell({ text }: { text: string | null }) {
  if (!text) {
    return <Typography.Text type="secondary">—</Typography.Text>;
  }
  return (
    <Tooltip title={text} placement="topLeft">
      <Typography.Text ellipsis style={{ maxWidth: "100%" }}>
        {text}
      </Typography.Text>
    </Tooltip>
  );
}

// 非编辑列固定列宽 + Tooltip 截断，避免长文本撑破布局。
const STATIC_COLUMNS: ColumnsType<ColumnMeta> = [
  {
    title: "#",
    dataIndex: "ordinal",
    key: "ordinal",
    width: 60,
    fixed: "left",
  },
  {
    title: "字段名",
    dataIndex: "column_name",
    key: "column_name",
    width: 200,
    fixed: "left",
    render: (name: string, record) => (
      <Space size={4} wrap>
        <Typography.Text strong>{name}</Typography.Text>
        {record.is_primary_key && <Tag color="gold">PK</Tag>}
      </Space>
    ),
  },
  {
    title: "类型",
    dataIndex: "raw_type",
    key: "type",
    width: 150,
    render: (rawType: string, record) => (
      <Tooltip title={`采集类型：${rawType}`} placement="topLeft">
        <Tag>{record.effective_type ?? rawType}</Tag>
      </Tooltip>
    ),
  },
  {
    title: "可空",
    dataIndex: "is_nullable",
    key: "is_nullable",
    width: 80,
    render: (nullable: boolean) =>
      nullable ? <Tag>可空</Tag> : <Tag color="blue">非空</Tag>,
  },
];

const DOMAIN_COLUMN: ColumnsType<ColumnMeta>[number] = {
  title: "数据域",
  dataIndex: "domain_name",
  key: "domain_name",
  width: 140,
  render: (domain: string | null) =>
    domain ? (
      <Tag color="purple">{domain}</Tag>
    ) : (
      <Typography.Text type="secondary">—</Typography.Text>
    ),
};

function ColumnsTab({ tableUrn }: { tableUrn: string }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [editingUrn, setEditingUrn] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  // editingRef 始终反映最新编辑行：Tab/Enter 切换后，旧输入框迟到的 blur 靠它去重。
  const editingRef = useRef<string | null>(null);
  const savingRef = useRef(false);

  const query = useQuery({
    queryKey: ["columns", tableUrn, page],
    queryFn: () => listColumns(tableUrn, page, PAGE_SIZE),
    placeholderData: (previous) => previous,
  });
  const rows = query.data?.items ?? [];

  const mutation = useMutation({
    mutationFn: async ({ urn, businessMeaning }: { urn: string; businessMeaning: string }) => {
      // 先读现有标注再合并，避免整体替换 upsert 清空其他业务字段。
      let existing: FieldAnnotationOut | null = null;
      try {
        existing = await getFieldAnnotation(urn);
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 404)) {
          throw err;
        }
      }
      return upsertFieldAnnotation(urn, mergeAnnotationPayload(existing, businessMeaning));
    },
    onSuccess: () => {
      // 生成列方案下，字段有效业务语义即时更新，回填后立即可搜到。
      void queryClient.invalidateQueries({ queryKey: ["columns", tableUrn] });
    },
  });

  const setEditing = (urn: string | null, initial = "") => {
    editingRef.current = urn;
    setEditingUrn(urn);
    setDraft(initial);
  };

  const commit = async (record: ColumnMeta, moveNext: boolean) => {
    if (editingRef.current !== record.urn || savingRef.current) {
      return;
    }
    const value = draft.trim();
    const current = record.business_meaning ?? "";
    let ok = true;
    if (value !== current) {
      if (value === "") {
        message.warning("业务含义不能为空，未保存");
        ok = false;
      } else {
        savingRef.current = true;
        try {
          await mutation.mutateAsync({ urn: record.urn, businessMeaning: value });
          message.success("已保存");
        } catch (err) {
          message.error(err instanceof Error ? err.message : "保存失败");
          ok = false;
        } finally {
          savingRef.current = false;
        }
      }
    }
    if (moveNext && ok) {
      const index = rows.findIndex((row) => row.urn === record.urn);
      const nextRow = rows[index + 1];
      if (nextRow) {
        setEditing(nextRow.urn, nextRow.business_meaning ?? "");
        return;
      }
    }
    setEditing(null);
  };

  const meaningColumn: ColumnsType<ColumnMeta>[number] = {
    title: "业务含义",
    key: "meaning",
    width: 300,
    render: (_, record) => {
      if (editingUrn === record.urn) {
        return (
          <Input
            autoFocus
            size="small"
            value={draft}
            disabled={mutation.isPending}
            onChange={(event) => setDraft(event.target.value)}
            onPressEnter={() => void commit(record, false)}
            onBlur={() => void commit(record, false)}
            onKeyDown={(event) => {
              if (event.key === "Tab") {
                event.preventDefault();
                void commit(record, true);
              } else if (event.key === "Escape") {
                setEditing(null);
              }
            }}
          />
        );
      }
      return (
        <div
          onClick={() => setEditing(record.urn, record.business_meaning ?? "")}
          title="点击编辑业务含义"
          style={{ display: "flex", alignItems: "center", gap: 4, cursor: "pointer", minWidth: 0 }}
        >
          <span style={{ flex: 1, minWidth: 0 }}>
            <EllipsisCell text={record.business_meaning ?? record.raw_comment} />
          </span>
          <EditOutlined style={{ color: "#bbb", flexShrink: 0 }} />
        </div>
      );
    },
  };

  if (query.isError) {
    return (
      <ErrorState
        error={query.error}
        onRetry={() => void query.refetch()}
        forbiddenMessage="无权限访问该表字段"
        errorMessage="字段加载失败"
      />
    );
  }

  return (
    <Table<ColumnMeta>
      rowKey="urn"
      size="middle"
      loading={query.isLoading}
      columns={[...STATIC_COLUMNS, meaningColumn, DOMAIN_COLUMN]}
      dataSource={rows}
      tableLayout="fixed"
      scroll={{ x: 930 }}
      pagination={{
        current: query.data?.page ?? page,
        pageSize: query.data?.page_size ?? PAGE_SIZE,
        total: query.data?.total ?? 0,
        showSizeChanger: false,
        hideOnSinglePage: true,
        onChange: setPage,
      }}
    />
  );
}

function DdlTab({ tableUrn, active }: { tableUrn: string; active: boolean }) {
  const query = useQuery({
    queryKey: ["ddl", tableUrn],
    queryFn: () => getTableDdl(tableUrn),
    enabled: active,
  });

  if (query.isLoading) {
    return <LoadingState />;
  }
  if (query.isError) {
    return (
      <ErrorState
        error={query.error}
        onRetry={() => void query.refetch()}
        forbiddenMessage="无权限查看该表 DDL"
        errorMessage="DDL 生成失败"
      />
    );
  }
  if (!query.data) {
    return null;
  }

  return (
    <Typography.Paragraph
      copyable={{ text: query.data.ddl }}
      style={{
        margin: 0,
        padding: 16,
        background: "#f6f8fa",
        borderRadius: 6,
        fontFamily: "'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace",
        fontSize: 13,
        whiteSpace: "pre",
        overflowX: "auto",
      }}
    >
      {query.data.ddl}
    </Typography.Paragraph>
  );
}

const CHANGE_TYPE_META: Record<string, { color: string; label: string }> = {
  TABLE_ADDED: { color: "green", label: "表新增" },
  TABLE_DROPPED: { color: "red", label: "表删除" },
  COLUMN_ADDED: { color: "green", label: "字段新增" },
  COLUMN_DROPPED: { color: "red", label: "字段删除" },
  COLUMN_TYPE_CHANGED: { color: "gold", label: "类型变更" },
  COLUMN_COMMENT_CHANGED: { color: "blue", label: "注释变更" },
  INDEX_ADDED: { color: "green", label: "索引新增" },
  INDEX_DROPPED: { color: "red", label: "索引删除" },
  INDEX_CHANGED: { color: "gold", label: "索引变更" },
};

function changeDetail(row: SchemaChange): string {
  const before = row.before_value ?? {};
  const after = row.after_value ?? {};
  switch (row.change_type) {
    case "COLUMN_TYPE_CHANGED":
      return `${String(before.raw_type ?? "?")} → ${String(after.raw_type ?? "?")}`;
    case "COLUMN_COMMENT_CHANGED":
      return `${String(before.raw_comment ?? "—")} → ${String(after.raw_comment ?? "—")}`;
    default:
      break;
  }
  if (row.change_type.endsWith("ADDED")) {
    const parts = [after.raw_type ?? after.table_type, after.raw_comment ?? after.table_comment];
    return parts.filter(Boolean).map(String).join(" · ");
  }
  if (row.change_type.endsWith("DROPPED")) {
    return String(before.raw_type ?? before.table_type ?? "");
  }
  return JSON.stringify(after).slice(0, 80);
}

function ChangesTab({ tableUrn, active }: { tableUrn: string; active: boolean }) {
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["changes", tableUrn, page],
    queryFn: () => listChanges({ tableUrn, page, pageSize: 20 }),
    enabled: active,
    placeholderData: (previous) => previous,
  });

  if (query.isLoading) {
    return <LoadingState />;
  }
  if (query.isError) {
    return (
      <ErrorState
        error={query.error}
        onRetry={() => void query.refetch()}
        forbiddenMessage="无权限查看变更历史"
        errorMessage="变更历史加载失败"
      />
    );
  }

  const columns: ColumnsType<SchemaChange> = [
    {
      title: "时间",
      dataIndex: "detected_at",
      width: 170,
      render: (value: string | null) =>
        value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—",
    },
    {
      title: "变更类型",
      dataIndex: "change_type",
      width: 110,
      render: (value: string) => {
        const meta = CHANGE_TYPE_META[value];
        return <Tag color={meta?.color}>{meta?.label ?? value}</Tag>;
      },
    },
    {
      title: "对象",
      dataIndex: "urn",
      width: 200,
      render: (value: string) => {
        const parts = value.split(":");
        return (
          <Typography.Text code>
            {parts.length >= 5 ? parts.slice(4).join(":") : "（表本身）"}
          </Typography.Text>
        );
      },
    },
    {
      title: "详情",
      key: "detail",
      ellipsis: true,
      render: (_, row) => changeDetail(row) || <Typography.Text type="secondary">—</Typography.Text>,
    },
  ];

  return (
    <Table<SchemaChange>
      rowKey="id"
      size="small"
      columns={columns}
      dataSource={query.data?.items ?? []}
      locale={{ emptyText: <EmptyState simple description="该表暂无结构变更记录" /> }}
      pagination={{
        current: query.data?.page ?? page,
        pageSize: 20,
        total: query.data?.total ?? 0,
        showSizeChanger: false,
        showTotal: (total) => `共 ${total} 条变更`,
        onChange: setPage,
      }}
    />
  );
}

export default function TableDetailPage() {
  const { urn = "" } = useParams();
  const [activeTab, setActiveTab] = useState<"columns" | "ddl" | "changes">("columns");

  const tableQuery = useQuery({
    queryKey: ["table", urn],
    queryFn: () => getTable(urn),
    enabled: urn.length > 0,
  });

  if (tableQuery.isLoading) {
    return <LoadingState size="large" padding={64} />;
  }

  const table = tableQuery.data?.items[0];

  // 错误态 / 无权限态 / 不存在（空）态：403 无权限，其余错误可重试，空 items 归为“表不存在”。
  if (tableQuery.isError || !table) {
    return (
      <Card>
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Link to="/tables">
            <Button icon={<ArrowLeftOutlined />}>返回表目录</Button>
          </Link>
          {tableQuery.isError ? (
            <ErrorState
              error={tableQuery.error}
              onRetry={() => void tableQuery.refetch()}
              forbiddenMessage="无权限访问该表"
              errorMessage="加载失败"
            />
          ) : (
            <EmptyState simple={false} description={`未找到表「${urn}」`} />
          )}
        </Space>
      </Card>
    );
  }

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Link to="/tables">
        <Button icon={<ArrowLeftOutlined />}>返回表目录</Button>
      </Link>
      <Card>
        <Descriptions
          title={
            <Space size="small" wrap>
              <Typography.Text strong style={{ fontSize: 18 }}>
                {table.table_name}
              </Typography.Text>
              <Tag>{table.table_type}</Tag>
              {table.dw_layer && <Tag color="blue">{table.dw_layer}</Tag>}
              {table.is_deleted && <Tag color="red">已删除</Tag>}
            </Space>
          }
          column={{ xs: 1, sm: 2, md: 3 }}
          size="small"
          bordered
        >
          <Descriptions.Item label="库名">{table.db_name}</Descriptions.Item>
          <Descriptions.Item label="行数">{formatCount(table.row_count)}</Descriptions.Item>
          <Descriptions.Item label="大小">{formatBytes(table.data_size)}</Descriptions.Item>
          <Descriptions.Item label="URN" span={3}>
            <Typography.Text copyable code>
              {table.urn}
            </Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label="表注释" span={3}>
            {table.table_comment ?? <Typography.Text type="secondary">—</Typography.Text>}
          </Descriptions.Item>
        </Descriptions>
      </Card>
      <Card>
        <Tabs
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key as "columns" | "ddl" | "changes")}
          items={[
            {
              key: "columns",
              label: "字段",
              children: <ColumnsTab tableUrn={table.urn} />,
            },
            {
              key: "changes",
              label: "变更历史",
              children: <ChangesTab tableUrn={table.urn} active={activeTab === "changes"} />,
            },
            {
              key: "ddl",
              label: "DDL",
              children: <DdlTab tableUrn={table.urn} active={activeTab === "ddl"} />,
            },
          ]}
        />
      </Card>
    </Space>
  );
}
