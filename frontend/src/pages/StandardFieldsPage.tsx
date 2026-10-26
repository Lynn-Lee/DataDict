import { ReloadOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Drawer,
  Input,
  Modal,
  Radio,
  Segmented,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useEffect, useMemo, useState } from "react";

import {
  confirmStandardField,
  generateStandardFields,
  getStandardField,
  listStandardFields,
  type StandardField,
  type StandardFieldItem,
} from "@/api/standardFields";
import { EmptyState, ErrorState } from "@/components/QueryStates";

const PAGE_SIZE = 20;
const DEBOUNCE_MS = 300;

type FilterKey = "all" | "draft" | "conflict" | "confirmed";

const FILTERS: { value: FilterKey; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "draft", label: "待确认" },
  { value: "conflict", label: "冲突待裁决" },
  { value: "confirmed", label: "已定版" },
];

// 确认时后端要求同时给出归一逻辑类型，按原始类型串推断。
function inferLogicalType(rawType: string, fallback: string): string {
  const t = rawType.toLowerCase();
  if (/^(varchar|char|text|longtext|mediumtext|clob|nvarchar)/.test(t)) return "STRING";
  if (/^(bigint|int|integer|smallint|tinyint|mediumint)/.test(t)) return "INT";
  if (/^(decimal|numeric|money)/.test(t)) return "DECIMAL";
  if (/^(datetime|timestamp)/.test(t)) return "DATETIME";
  if (/^date$/.test(t)) return "DATE";
  if (/^(float|double|real)/.test(t)) return "FLOAT";
  if (/^(json|jsonb)/.test(t)) return "JSON";
  return fallback;
}

function distributionEntries(row: StandardField): [string, number][] {
  return Object.entries(row.type_distribution ?? {}).sort((a, b) => b[1] - a[1]);
}

function useDebouncedValue<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

export default function StandardFieldsPage() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<FilterKey>("all");
  const [keywordInput, setKeywordInput] = useState("");
  const [page, setPage] = useState(1);

  const keyword = useDebouncedValue(keywordInput, DEBOUNCE_MS).trim() || undefined;
  useEffect(() => {
    setPage(1);
  }, [filter, keyword]);

  const listQuery = useQuery({
    queryKey: ["standard-fields", filter, keyword, page],
    queryFn: () =>
      listStandardFields({
        status: filter === "confirmed" ? "CONFIRMED" : filter === "all" ? undefined : "DRAFT",
        conflict: filter === "conflict" ? true : undefined,
        q: keyword,
        page,
        pageSize: PAGE_SIZE,
      }),
    placeholderData: (previous) => previous,
  });

  const generateMutation = useMutation({
    mutationFn: generateStandardFields,
    onSuccess: (summary) => {
      message.success(
        `聚类完成：新增 ${summary.generated} 个候选，刷新 ${summary.updated} 个，` +
          `冲突待裁决 ${summary.skipped_conflict} 个`,
      );
      void queryClient.invalidateQueries({ queryKey: ["standard-fields"] });
    },
    onError: () => message.error("聚类生成失败，请稍后重试"),
  });

  // ── 确认定版弹窗 ──
  const [confirmTarget, setConfirmTarget] = useState<StandardField | null>(null);
  const [selectedType, setSelectedType] = useState("");
  const [meaning, setMeaning] = useState("");

  const openConfirm = (row: StandardField) => {
    const entries = distributionEntries(row);
    setConfirmTarget(row);
    setSelectedType(row.raw_type ?? entries[0]?.[0] ?? "");
    setMeaning(row.business_meaning ?? "");
  };

  const confirmMutation = useMutation({
    mutationFn: (vars: { id: number; rawType: string; meaning: string; fallback: string }) =>
      confirmStandardField(vars.id, {
        raw_type: vars.rawType,
        logical_type: inferLogicalType(vars.rawType, vars.fallback),
        business_meaning: vars.meaning,
      }),
    onSuccess: (confirmed) => {
      message.success(`已定版：${confirmed.standard_name} ${confirmed.raw_type}`);
      setConfirmTarget(null);
      setDetailId(confirmed.id);
      void queryClient.invalidateQueries({ queryKey: ["standard-fields"] });
    },
    onError: () => message.error("定版失败，请重试"),
  });

  const submitConfirm = () => {
    if (!confirmTarget) return;
    if (!meaning.trim()) {
      message.warning("中文释义不能为空");
      return;
    }
    if (!selectedType) {
      message.warning("请选择标准类型");
      return;
    }
    confirmMutation.mutate({
      id: confirmTarget.id,
      rawType: selectedType,
      meaning: meaning.trim(),
      fallback: confirmTarget.logical_type,
    });
  };

  // ── 详情抽屉（存量源字段清单 + conforms） ──
  const [detailId, setDetailId] = useState<number | null>(null);
  const detailQuery = useQuery({
    queryKey: ["standard-field-detail", detailId],
    queryFn: () => getStandardField(detailId as number),
    enabled: detailId !== null,
  });

  const columns = useMemo<ColumnsType<StandardField>>(
    () => [
      {
        title: "字段名",
        dataIndex: "standard_name",
        width: 180,
        render: (value: string, row) => (
          <Typography.Text strong code onClick={() => setDetailId(row.id)} style={{ cursor: "pointer" }}>
            {value}
          </Typography.Text>
        ),
      },
      { title: "覆盖表数", dataIndex: "candidate_count", width: 90, align: "right" },
      {
        title: "类型分布",
        key: "distribution",
        width: 240,
        render: (_, row) => (
          <Space direction="vertical" size={2}>
            {distributionEntries(row).map(([type, count]) => (
              <span key={type}>
                <Tag color={row.has_conflict ? "gold" : "blue"} style={{ fontFamily: "monospace" }}>
                  {type}
                </Tag>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  ×{count}
                </Typography.Text>
              </span>
            ))}
          </Space>
        ),
      },
      {
        title: "推荐定义",
        key: "recommendation",
        width: 170,
        render: (_, row) =>
          row.status === "CONFIRMED" ? (
            <Space size={4}>
              <Tag color="green" style={{ fontFamily: "monospace" }}>{row.raw_type}</Tag>
              <Tag>{row.logical_type}</Tag>
            </Space>
          ) : row.has_conflict ? (
            <Tag color="red">语义冲突 · 待人工裁决</Tag>
          ) : (
            <Space size={4}>
              <Tag color="blue" style={{ fontFamily: "monospace" }}>{row.raw_type}</Tag>
              <Tag>{row.logical_type}</Tag>
            </Space>
          ),
      },
      {
        title: "业务释义",
        dataIndex: "business_meaning",
        ellipsis: true,
        render: (value: string | null) =>
          value || <Typography.Text type="secondary">—</Typography.Text>,
      },
      {
        title: "状态",
        dataIndex: "status",
        width: 110,
        render: (value: string, row) =>
          value === "CONFIRMED" ? (
            <Tag color="green">已定版 v{row.version}</Tag>
          ) : row.has_conflict ? (
            <Tag color="gold">冲突待裁决</Tag>
          ) : (
            <Tag color="blue">待确认</Tag>
          ),
      },
      {
        title: "操作",
        key: "actions",
        width: 150,
        render: (_, row) =>
          row.status === "CONFIRMED" ? (
            <Button type="link" size="small" onClick={() => setDetailId(row.id)}>
              查看存量字段
            </Button>
          ) : (
            <Space size={4}>
              <Button type="primary" size="small" onClick={() => openConfirm(row)}>
                {row.has_conflict ? "冲突裁决" : "确认定版"}
              </Button>
              <Button type="link" size="small" onClick={() => setDetailId(row.id)}>
                详情
              </Button>
            </Space>
          ),
      },
    ],
    // eslint 不需要依赖：openConfirm/setDetailId 为稳定引用
    [],
  );

  const itemColumns: ColumnsType<StandardFieldItem> = [
    { title: "库", dataIndex: "db_name", width: 110 },
    { title: "表", dataIndex: "table_name", width: 200, ellipsis: true },
    {
      title: "字段",
      dataIndex: "column_name",
      width: 160,
      render: (value: string | null) => <Typography.Text code>{value}</Typography.Text>,
    },
    {
      title: "原始类型",
      dataIndex: "raw_type",
      width: 130,
      render: (value: string | null) => <Typography.Text code>{value}</Typography.Text>,
    },
    {
      title: "符合标准",
      dataIndex: "conforms",
      width: 100,
      render: (value: boolean | null) =>
        value === null ? (
          <Tag>待回算</Tag>
        ) : value ? (
          <Tag color="green">符合</Tag>
        ) : (
          <Tag color="orange">不符合</Tag>
        ),
    },
  ];

  return (
    <Card>
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Space wrap style={{ justifyContent: "space-between", width: "100%" }}>
          <Space wrap>
            <Segmented
              options={FILTERS}
              value={filter}
              onChange={(value) => setFilter(value as FilterKey)}
            />
            <Input.Search
              allowClear
              placeholder="字段名或业务释义"
              style={{ width: 240 }}
              value={keywordInput}
              onChange={(event) => setKeywordInput(event.target.value)}
            />
          </Space>
          <Button
            icon={<ReloadOutlined />}
            loading={generateMutation.isPending}
            onClick={() => generateMutation.mutate()}
          >
            重新聚类
          </Button>
        </Space>

        <Alert
          type="info"
          showIcon
          message="治理闭环：同步存量字段 → 同名聚类生成候选 → 人工确认定版 → API / MCP 供 AI 建表查询；status、type 等黑名单通用字段名已排除，需逐表人工归组。"
        />

        {listQuery.isError ? (
          <ErrorState
            error={listQuery.error}
            onRetry={() => void listQuery.refetch()}
            forbiddenMessage="无权限访问标准定义工作台"
            errorMessage="候选列表加载失败"
          />
        ) : (
          <Table<StandardField>
            rowKey="id"
            size="middle"
            columns={columns}
            dataSource={listQuery.data?.items ?? []}
            loading={listQuery.isLoading}
            locale={{ emptyText: <EmptyState simple={false} description="该筛选条件下暂无候选" /> }}
            pagination={{
              current: listQuery.data?.page ?? page,
              pageSize: PAGE_SIZE,
              total: listQuery.data?.total ?? 0,
              showSizeChanger: false,
              showTotal: (total) => `共 ${total} 个字段名`,
              onChange: setPage,
            }}
          />
        )}
      </Space>

      <Modal
        title={
          confirmTarget
            ? `确认标准定义 · ${confirmTarget.standard_name}`
            : "确认标准定义"
        }
        open={confirmTarget !== null}
        onCancel={() => setConfirmTarget(null)}
        onOk={submitConfirm}
        okText="确认定版"
        cancelText="取消"
        confirmLoading={confirmMutation.isPending}
        destroyOnClose
      >
        {confirmTarget && (
          <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            <Typography.Text type="secondary">
              该字段名在 {confirmTarget.candidate_count} 张表中出现。定版后成为全公司唯一标准，
              存量字段将按类型一致性回算 conforms 标记。
            </Typography.Text>
            {confirmTarget.has_conflict && (
              <Alert
                type="warning"
                showIcon
                message="类型存在语义级冲突，系统不给自动推荐，必须人工裁决"
              />
            )}
            <div>
              <Typography.Text strong>标准类型</Typography.Text>
              <Radio.Group
                style={{ display: "block", marginTop: 8 }}
                value={selectedType}
                onChange={(event) => setSelectedType(event.target.value as string)}
              >
                <Space direction="vertical">
                  {distributionEntries(confirmTarget).map(([type, count]) => (
                    <Radio key={type} value={type}>
                      <Typography.Text code>{type}</Typography.Text>
                      <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                        ×{count} 张表{count === Math.max(...distributionEntries(confirmTarget).map(([, c]) => c)) ? " · 众数" : ""}
                      </Typography.Text>
                    </Radio>
                  ))}
                </Space>
              </Radio.Group>
            </div>
            <div>
              <Typography.Text strong>中文释义 / 业务含义</Typography.Text>
              <Input.TextArea
                style={{ marginTop: 8 }}
                rows={2}
                value={meaning}
                onChange={(event) => setMeaning(event.target.value)}
                placeholder="如：运单号"
              />
            </div>
          </Space>
        )}
      </Modal>

      <Drawer
        title={detailQuery.data ? `标准定义 · ${detailQuery.data.standard_name}` : "标准定义详情"}
        width={720}
        open={detailId !== null}
        onClose={() => setDetailId(null)}
        destroyOnClose
      >
        {detailQuery.isLoading ? (
          <Typography.Text type="secondary">加载中…</Typography.Text>
        ) : detailQuery.isError ? (
          <ErrorState error={detailQuery.error} onRetry={() => void detailQuery.refetch()} />
        ) : detailQuery.data ? (
          <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            <Space wrap>
              <Tag color={detailQuery.data.status === "CONFIRMED" ? "green" : "blue"}>
                {detailQuery.data.status === "CONFIRMED" ? "已定版" : "待确认"}
              </Tag>
              {detailQuery.data.raw_type && (
                <Tag style={{ fontFamily: "monospace" }}>{detailQuery.data.raw_type}</Tag>
              )}
              <Tag>{detailQuery.data.logical_type}</Tag>
              <Typography.Text>{detailQuery.data.business_meaning ?? "—"}</Typography.Text>
            </Space>
            <Typography.Text type="secondary">
              存量源字段 {detailQuery.data.items.length} 个
              {detailQuery.data.status === "CONFIRMED" &&
                `，符合 ${detailQuery.data.items.filter((i) => i.conforms === true).length} 个`}
            </Typography.Text>
            <Table<StandardFieldItem>
              rowKey="column_urn"
              size="small"
              columns={itemColumns}
              dataSource={detailQuery.data.items}
              pagination={{ pageSize: 10, showSizeChanger: false }}
            />
          </Space>
        ) : null}
      </Drawer>
    </Card>
  );
}
