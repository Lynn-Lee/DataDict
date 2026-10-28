import { ReloadOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  AutoComplete,
  Button,
  Card,
  Input,
  Modal,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useEffect, useMemo, useState } from "react";

import { ApiError } from "@/api/client";
import {
  confirmStandardField,
  generateStandardFields,
  listStandardFields,
  mergeStandardField,
  type SimilarStandard,
  type StandardField,
} from "@/api/standardFields";
import { EmptyState, ErrorState } from "@/components/QueryStates";
import ExcelImportCard from "@/components/ExcelImportCard";
import StandardFieldDrawer from "@/components/StandardFieldDrawer";

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

const LOGICAL_TYPE_OPTIONS = [
  "STRING",
  "INT",
  "DECIMAL",
  "FLOAT",
  "DATETIME",
  "DATE",
  "TIME",
  "BOOL",
  "JSON",
  "BINARY",
  "UNKNOWN",
].map((value) => ({ value, label: value }));

const MATCHED_BY_LABEL: Record<SimilarStandard["matched_by"], string> = {
  NAME: "同名",
  ALIAS: "别名命中",
  MEANING: "释义相似",
};

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

  // ── 确认定版弹窗（标准名/类型/长度/逻辑类型/释义全部可改） ──
  const [confirmTarget, setConfirmTarget] = useState<StandardField | null>(null);
  const [standardName, setStandardName] = useState("");
  const [selectedType, setSelectedType] = useState("");
  const [logicalType, setLogicalType] = useState("");
  const [meaning, setMeaning] = useState("");
  // 改名撞上已有标准时后端返回 409 + existing_id，转为「关联到已有标准」引导
  const [nameClash, setNameClash] = useState<{ id: number; name: string } | null>(null);

  const openConfirm = (row: StandardField) => {
    const entries = distributionEntries(row);
    const type = row.raw_type ?? entries[0]?.[0] ?? "";
    setConfirmTarget(row);
    setStandardName(row.standard_name);
    setSelectedType(type);
    setLogicalType(type ? inferLogicalType(type, row.logical_type) : row.logical_type);
    setMeaning(row.business_meaning ?? "");
    setNameClash(null);
  };

  // ── 关联（合并）到已有标准 ──
  const [mergeTarget, setMergeTarget] = useState<{
    source: StandardField;
    targetId: number;
    targetName: string;
  } | null>(null);

  const invalidateList = () => {
    void queryClient.invalidateQueries({ queryKey: ["standard-fields"] });
    void queryClient.invalidateQueries({ queryKey: ["standard-library"] });
    void queryClient.invalidateQueries({ queryKey: ["standard-field-detail"] });
  };

  const mergeMutation = useMutation({
    mutationFn: (vars: { sourceId: number; targetId: number }) =>
      mergeStandardField(vars.sourceId, vars.targetId),
    onSuccess: (target) => {
      message.success(
        `已关联到标准「${target.standard_name} ${target.raw_type}」，存量字段已迁移` +
          (mergeTarget?.source.sub_key ? "" : "，原字段名记为业务别名"),
      );
      setMergeTarget(null);
      setConfirmTarget(null);
      setNameClash(null);
      invalidateList();
    },
    onError: (err) => message.error(err instanceof Error ? err.message : "关联失败"),
  });

  const confirmMutation = useMutation({
    mutationFn: (vars: { id: number; name: string; rawType: string; logical: string; meaning: string }) =>
      confirmStandardField(vars.id, {
        standard_name: vars.name,
        raw_type: vars.rawType,
        logical_type: vars.logical,
        business_meaning: vars.meaning,
      }),
    onSuccess: (confirmed) => {
      message.success(`已定版：${confirmed.standard_name} ${confirmed.raw_type}`);
      setConfirmTarget(null);
      setNameClash(null);
      setDetailId(confirmed.id);
      invalidateList();
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409 && typeof err.detail.existing_id === "number") {
        setNameClash({
          id: err.detail.existing_id as number,
          name: String(err.detail.existing_name ?? standardName),
        });
        message.warning(err.message);
        return;
      }
      message.error(err instanceof Error ? err.message : "定版失败，请重试");
    },
  });

  const submitConfirm = () => {
    if (!confirmTarget) return;
    if (!standardName.trim()) {
      message.warning("标准字段名不能为空");
      return;
    }
    if (!/^[a-z_][a-z0-9_]*$/.test(standardName.trim())) {
      message.warning("标准字段名只能用小写字母、数字、下划线，且以字母或下划线开头");
      return;
    }
    if (!meaning.trim()) {
      message.warning("中文释义不能为空");
      return;
    }
    if (!selectedType.trim()) {
      message.warning("请填写标准类型（含长度，如 varchar(16)）");
      return;
    }
    confirmMutation.mutate({
      id: confirmTarget.id,
      name: standardName.trim(),
      rawType: selectedType.trim(),
      logical: logicalType || inferLogicalType(selectedType.trim(), confirmTarget.logical_type),
      meaning: meaning.trim(),
    });
  };

  // ── 详情抽屉（共享组件） ──
  const [detailId, setDetailId] = useState<number | null>(null);

  const columns = useMemo<ColumnsType<StandardField>>(
    () => [
      {
        title: "字段名",
        dataIndex: "standard_name",
        width: 180,
        render: (value: string, row) => (
          <Space direction="vertical" size={2}>
            <Typography.Text
              strong
              code
              onClick={() => setDetailId(row.id)}
              style={{ cursor: "pointer" }}
            >
              {value}
            </Typography.Text>
            {row.sub_key && (
              <Tooltip title="通用字段名同名不同义，已按注释释义拆成独立候选，本条只代表其中一个概念">
                <Tag color="purple" style={{ marginInlineEnd: 0 }}>
                  按释义分组
                </Tag>
              </Tooltip>
            )}
          </Space>
        ),
      },
      {
        title: "来源",
        key: "sources",
        width: 130,
        render: (_, row) => (
          <Space direction="vertical" size={0}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              源库 {row.candidate_count} 字段
            </Typography.Text>
            {row.doc_count > 0 && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                Excel 文档 {row.doc_count} 条
              </Typography.Text>
            )}
          </Space>
        ),
      },
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
        title: "疑似已有标准",
        key: "similar",
        width: 240,
        render: (_, row) =>
          row.status !== "DRAFT" || row.similar_standards.length === 0 ? (
            <Typography.Text type="secondary">—</Typography.Text>
          ) : (
            <Space direction="vertical" size={2}>
              {row.similar_standards.map((similar) => (
                <Space key={similar.id} size={4} wrap>
                  <Tooltip
                    title={`${MATCHED_BY_LABEL[similar.matched_by]}${
                      similar.matched_by === "MEANING" ? ` ${similar.score}` : ""
                    } · ${similar.business_meaning ?? ""}`}
                  >
                    <Tag color="purple" style={{ fontFamily: "monospace" }}>
                      {similar.standard_name}
                      {similar.raw_type ? ` ${similar.raw_type}` : ""}
                    </Tag>
                  </Tooltip>
                  <Button
                    type="link"
                    size="small"
                    onClick={() =>
                      setMergeTarget({
                        source: row,
                        targetId: similar.id,
                        targetName: similar.standard_name,
                      })
                    }
                  >
                    关联
                  </Button>
                </Space>
              ))}
            </Space>
          ),
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
          message="治理闭环：同步存量字段 → 同名聚类生成候选 → 人工确认定版 → API / MCP 供 AI 建表查询；status、type 等通用字段名同名不同义，已按注释释义拆成独立候选，可各自定版。"
        />

        <ExcelImportCard />

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
              showTotal: (total) => `共 ${total} 个候选定义`,
              onChange: setPage,
            }}
          />
        )}
      </Space>

      <Modal
        title={
          confirmTarget
            ? `确认标准定义 · ${confirmTarget.cluster_key ?? confirmTarget.standard_name}` +
              (confirmTarget.sub_key
                ? `（${confirmTarget.business_meaning ?? "无释义"}）`
                : "")
            : "确认标准定义"
        }
        open={confirmTarget !== null}
        onCancel={() => setConfirmTarget(null)}
        onOk={submitConfirm}
        okText="确认定版"
        cancelText="取消"
        confirmLoading={confirmMutation.isPending}
        width={620}
        destroyOnHidden
      >
        {confirmTarget && (
          <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            <Typography.Text type="secondary">
              证据来源：源库 {confirmTarget.candidate_count} 个字段
              {confirmTarget.doc_count > 0 && `，Excel 文档 ${confirmTarget.doc_count} 条`}。
              名称、类型、长度、释义都可改；定版后按「字段名 + 类型都一致」回算存量字段的
              conforms。
            </Typography.Text>

            {confirmTarget.has_conflict && (
              <Alert
                type="warning"
                showIcon
                message="类型存在语义级冲突，系统不给自动推荐，必须人工裁决"
              />
            )}

            {confirmTarget.similar_standards.length > 0 && (
              <Alert
                type="info"
                showIcon
                message="标准库中疑似已有同一概念的标准，建议直接关联而不是新建（否则会出现两个同义标准）"
                description={
                  <Space direction="vertical" size={4}>
                    {confirmTarget.similar_standards.map((similar) => (
                      <Space key={similar.id} size={6} wrap>
                        <Tag color="purple" style={{ fontFamily: "monospace" }}>
                          {similar.standard_name} {similar.raw_type}
                        </Tag>
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {similar.business_meaning} · {MATCHED_BY_LABEL[similar.matched_by]}
                          {similar.matched_by === "MEANING" ? ` ${similar.score}` : ""}
                        </Typography.Text>
                        <Button
                          type="link"
                          size="small"
                          onClick={() =>
                            setMergeTarget({
                              source: confirmTarget,
                              targetId: similar.id,
                              targetName: similar.standard_name,
                            })
                          }
                        >
                          关联到该标准
                        </Button>
                      </Space>
                    ))}
                  </Space>
                }
              />
            )}

            {nameClash && (
              <Alert
                type="error"
                showIcon
                message={`标准库已存在「${nameClash.name}」，同一概念只应有一个标准`}
                description={
                  <Button
                    type="primary"
                    size="small"
                    onClick={() =>
                      setMergeTarget({
                        source: confirmTarget,
                        targetId: nameClash.id,
                        targetName: nameClash.name,
                      })
                    }
                  >
                    改为关联到「{nameClash.name}」
                  </Button>
                }
              />
            )}

            <div>
              <Typography.Text strong>标准字段名</Typography.Text>
              <Input
                style={{ marginTop: 8, fontFamily: "monospace" }}
                value={standardName}
                onChange={(event) => setStandardName(event.target.value)}
                placeholder="如：waybill_no（小写字母/数字/下划线）"
              />
              {confirmTarget.cluster_key &&
                confirmTarget.cluster_key !== standardName &&
                !confirmTarget.sub_key && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    候选来源字段名 {confirmTarget.cluster_key} 将自动记为该标准的业务别名
                  </Typography.Text>
                )}
            </div>

            <Space size="middle" wrap>
              <div style={{ minWidth: 220 }}>
                <Typography.Text strong>标准类型（含长度，可自由填写）</Typography.Text>
                <AutoComplete
                  style={{ width: 220, marginTop: 8, fontFamily: "monospace" }}
                  value={selectedType}
                  onChange={(value) => {
                    setSelectedType(value);
                    setLogicalType(inferLogicalType(value, confirmTarget.logical_type));
                  }}
                  options={distributionEntries(confirmTarget).map(([type, count]) => ({
                    value: type,
                    label: `${type}（实际出现 ${count} 次）`,
                  }))}
                  placeholder="如：varchar(16)"
                />
              </div>
              <div style={{ minWidth: 140 }}>
                <Typography.Text strong>逻辑类型</Typography.Text>
                <Select
                  style={{ width: 140, marginTop: 8 }}
                  value={logicalType || undefined}
                  onChange={setLogicalType}
                  options={LOGICAL_TYPE_OPTIONS}
                  placeholder="随类型自动推导"
                />
              </div>
            </Space>

            <div>
              <Typography.Text strong>中文释义 / 业务含义</Typography.Text>
              <Input.TextArea
                style={{ marginTop: 8 }}
                rows={2}
                value={meaning}
                onChange={(event) => setMeaning(event.target.value)}
                placeholder="如：运单号，全局唯一"
              />
            </div>
          </Space>
        )}
      </Modal>

      <Modal
        title="关联到已有标准"
        open={mergeTarget !== null}
        onCancel={() => setMergeTarget(null)}
        onOk={() =>
          mergeTarget &&
          mergeMutation.mutate({ sourceId: mergeTarget.source.id, targetId: mergeTarget.targetId })
        }
        okText="确认关联"
        cancelText="取消"
        confirmLoading={mergeMutation.isPending}
        destroyOnHidden
      >
        {mergeTarget && (
          <Space direction="vertical" size="small">
            <Typography.Text>
              候选「{mergeTarget.source.cluster_key ?? mergeTarget.source.standard_name}」
              {mergeTarget.source.sub_key
                ? `（${mergeTarget.source.business_meaning ?? "无释义"}）`
                : ""}
              的
              {mergeTarget.source.candidate_count > 0
                ? ` ${mergeTarget.source.candidate_count} 个存量字段将关联到标准「${mergeTarget.targetName}」`
                : "证据将并入标准"}
              ，本候选不再作为独立标准（标记为已合并）。
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {mergeTarget.source.sub_key
                ? "本候选是按释义拆出的通用名分组，原字段名不记为业务别名（否则会误引所有同名字段）；"
                : "原字段名会记为目标标准的业务别名；"}
              存量字段中名称或类型与标准不一致的，会标记为「不符合」并进入治理度量。
            </Typography.Text>
          </Space>
        )}
      </Modal>

      <StandardFieldDrawer standardId={detailId} onClose={() => setDetailId(null)} />
    </Card>
  );
}
