import { ThunderboltOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Input,
  Modal,
  Segmented,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  listGovernanceTodos,
  resolveGovernanceTodo,
  sweepGovernance,
  type GovernanceTodo,
} from "@/api/governance";
import { EmptyState, ErrorState } from "@/components/QueryStates";

const PAGE_SIZE = 20;

const ACTION_TAG: Record<string, { color: string; label: string }> = {
  ADOPT: { color: "green", label: "已采纳标准" },
  EXEMPT: { color: "gold", label: "已豁免" },
  IGNORE: { color: "default", label: "已忽略" },
  AUTO_RESOLVED: { color: "blue", label: "缺口已清零" },
};

const TYPE_TAG: Record<GovernanceTodo["todo_type"], { color: string; label: string }> = {
  STANDARD_CONFLICT: { color: "red", label: "类型冲突" },
  STANDARD_MISSING: { color: "volcano", label: "未挂标准" },
};

type TypeFilter = "ALL" | GovernanceTodo["todo_type"];

const TYPE_FILTERS: { value: TypeFilter; label: string }[] = [
  { value: "ALL", label: "全部待办" },
  { value: "STANDARD_CONFLICT", label: "类型冲突" },
  { value: "STANDARD_MISSING", label: "未挂标准" },
];

function rowLabel(todo: GovernanceTodo): string {
  if (todo.todo_type === "STANDARD_MISSING") {
    return `${todo.table_name ?? "未知表"}（${todo.missing_count ?? 0} 个字段未挂标准）`;
  }
  return `${todo.table_name ?? ""}.${todo.column_name ?? ""}`;
}

export default function GovernanceTodosPage() {
  const queryClient = useQueryClient();
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("ALL");
  const [exemptTarget, setExemptTarget] = useState<GovernanceTodo | null>(null);
  const [exemptReason, setExemptReason] = useState("");
  const [openPage, setOpenPage] = useState(1);
  const [closedPage, setClosedPage] = useState(1);

  const openQuery = useQuery({
    queryKey: ["governance-todos", "OPEN", typeFilter, openPage],
    queryFn: () =>
      listGovernanceTodos({
        status: "OPEN",
        todoType: typeFilter === "ALL" ? undefined : typeFilter,
        page: openPage,
        pageSize: PAGE_SIZE,
      }),
    placeholderData: (previous) => previous,
  });

  const closedQuery = useQuery({
    queryKey: ["governance-todos", "IGNORED", closedPage],
    queryFn: () => listGovernanceTodos({ status: "IGNORED", page: closedPage, pageSize: PAGE_SIZE }),
    placeholderData: (previous) => previous,
  });

  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey: ["governance-todos"] });

  const sweepMutation = useMutation({
    mutationFn: sweepGovernance,
    onSuccess: (summary) => {
      message.success(
        `扫描完成：挂入符合 ${summary.attached_conforming}，冲突 ${summary.attached_conflicting}，` +
          `conforms 修正 ${summary.conforms_updated}，注释变更重挂 ${summary.reattached}，` +
          `新冲突待办 ${summary.todos_created}，缺口待办 新增 ${summary.missing_todos_created} / ` +
          `更新 ${summary.missing_todos_updated} / 自动关闭 ${summary.missing_todos_closed}`,
      );
      invalidate();
    },
    onError: () => message.error("扫描失败，请稍后重试"),
  });

  const resolveMutation = useMutation({
    mutationFn: (vars: { id: number; action: "ADOPT" | "EXEMPT" | "IGNORE"; reason?: string }) =>
      resolveGovernanceTodo(vars.id, vars.action, vars.reason),
    onSuccess: (todo) => {
      const label = ACTION_TAG[todo.action ?? ""]?.label ?? "已处理";
      message.success(`${rowLabel(todo)}：${label}`);
      setExemptTarget(null);
      invalidate();
    },
    onError: (err) => message.error(err instanceof Error ? err.message : "处理失败"),
  });

  const submitExempt = () => {
    if (!exemptTarget) return;
    if (!exemptReason.trim()) {
      message.warning("豁免必须填写原因（留痕，供治理复盘）");
      return;
    }
    resolveMutation.mutate({
      id: exemptTarget.id,
      action: "EXEMPT",
      reason: exemptReason.trim(),
    });
  };

  const openColumns: ColumnsType<GovernanceTodo> = [
    {
      title: "类型",
      dataIndex: "todo_type",
      width: 110,
      render: (value: GovernanceTodo["todo_type"]) => (
        <Tag color={TYPE_TAG[value].color}>{TYPE_TAG[value].label}</Tag>
      ),
    },
    {
      title: "对象",
      key: "target",
      width: 240,
      render: (_, row) => (
        <Space direction="vertical" size={0}>
          <Typography.Text code>
            {row.todo_type === "STANDARD_MISSING"
              ? row.table_name
              : `${row.table_name}.${row.column_name}`}
          </Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {row.db_name}
            {row.todo_type === "STANDARD_MISSING" && (
              <> · {row.missing_count} 个字段未关联已定版标准</>
            )}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: "比对结果",
      key: "detail",
      width: 320,
      render: (_, row) =>
        row.todo_type === "STANDARD_MISSING" ? (
          <Space direction="vertical" size={2}>
            {row.missing_columns.slice(0, 4).map((column) => (
              <Space key={column.column_name} size={4}>
                <Typography.Text code style={{ fontSize: 12 }}>
                  {column.column_name}
                </Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {column.raw_type}
                </Typography.Text>
                <Tag color={column.has_draft_candidate ? "blue" : "default"}>
                  {column.has_draft_candidate ? "有候选待定版" : "需新建标准"}
                </Tag>
              </Space>
            ))}
            {row.missing_columns.length === 0 && (
              <Typography.Text type="secondary">—</Typography.Text>
            )}
            {row.preview_truncated && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                仅展示前 {row.missing_columns.length} 个，展开查看全部
              </Typography.Text>
            )}
          </Space>
        ) : (
          <Space direction="vertical" size={0}>
            <Space size={4}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                实际
              </Typography.Text>
              <Tag color="red">{row.actual_type}</Tag>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                标准
              </Typography.Text>
              <Tag color="green">{row.expected_type}</Tag>
            </Space>
            <Space size={4}>
              <Typography.Text code strong>
                {row.standard_name}
              </Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {row.business_meaning}
              </Typography.Text>
            </Space>
          </Space>
        ),
    },
    {
      title: "产生时间",
      dataIndex: "created_at",
      width: 160,
      render: (value: string | null) =>
        value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—",
    },
    {
      title: "操作",
      key: "actions",
      width: 260,
      render: (_, row) => (
        <Space size={4} wrap>
          {row.todo_type === "STANDARD_MISSING" ? (
            <>
              <Link to="/standard-fields">
                <Button type="primary" size="small">
                  去定标
                </Button>
              </Link>
              <Link to={`/tables/${encodeURIComponent(row.column_urn)}`}>
                <Button size="small">查看该表</Button>
              </Link>
            </>
          ) : (
            <Button
              type="primary"
              size="small"
              loading={resolveMutation.isPending}
              onClick={() => resolveMutation.mutate({ id: row.id, action: "ADOPT" })}
            >
              采纳标准
            </Button>
          )}
          <Button
            size="small"
            onClick={() => {
              setExemptTarget(row);
              setExemptReason("");
            }}
          >
            豁免
          </Button>
          <Button
            type="text"
            size="small"
            onClick={() => resolveMutation.mutate({ id: row.id, action: "IGNORE" })}
          >
            忽略
          </Button>
        </Space>
      ),
    },
  ];

  const closedColumns: ColumnsType<GovernanceTodo> = [
    {
      title: "类型",
      dataIndex: "todo_type",
      width: 110,
      render: (value: GovernanceTodo["todo_type"]) => (
        <Tag color={TYPE_TAG[value].color}>{TYPE_TAG[value].label}</Tag>
      ),
    },
    {
      title: "对象",
      key: "target",
      render: (_, row) => <Typography.Text code>{rowLabel(row)}</Typography.Text>,
    },
    {
      title: "处理结果",
      dataIndex: "action",
      width: 120,
      render: (value: string | null) => {
        const tag = ACTION_TAG[value ?? ""];
        return tag ? <Tag color={tag.color}>{tag.label}</Tag> : <Tag>—</Tag>;
      },
    },
    {
      title: "原因 / 备注",
      dataIndex: "reason",
      ellipsis: true,
      render: (value: string | null) =>
        value || <Typography.Text type="secondary">—</Typography.Text>,
    },
    {
      title: "处理时间",
      dataIndex: "done_at",
      width: 160,
      render: (value: string | null) =>
        value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—",
    },
  ];

  return (
    <Card>
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Space wrap style={{ justifyContent: "space-between", width: "100%" }}>
          <Typography.Text type="secondary">
            每次同步后自动按变更字段增量聚类并比对标准；不一致与缺口在此处理，豁免须填原因留痕。
          </Typography.Text>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            loading={sweepMutation.isPending}
            onClick={() => sweepMutation.mutate()}
          >
            立即扫描比对
          </Button>
        </Space>

        <Alert
          type="info"
          showIcon
          message="两类待办：类型冲突=字段的类型与已定版标准不一致（按字段，采纳/豁免/忽略）；未挂标准=该表仍有字段没关联任何已定版标准（按表聚合，缺口清零后自动关闭；豁免整表只写一次原因，缺口变大才会重新提醒）。"
        />

        <Segmented
          options={TYPE_FILTERS}
          value={typeFilter}
          onChange={(value) => {
            setTypeFilter(value as TypeFilter);
            setOpenPage(1);
          }}
        />

        <Typography.Title level={5} style={{ margin: 0 }}>
          待处理（{openQuery.data?.total ?? 0}）
        </Typography.Title>
        {openQuery.isError ? (
          <ErrorState
            error={openQuery.error}
            onRetry={() => void openQuery.refetch()}
            errorMessage="待办加载失败"
          />
        ) : (
          <Table<GovernanceTodo>
            rowKey="id"
            size="middle"
            columns={openColumns}
            dataSource={openQuery.data?.items ?? []}
            loading={openQuery.isLoading}
            locale={{ emptyText: <EmptyState simple description="没有待处理的比对项" /> }}
            expandable={{
              rowExpandable: (row) =>
                row.todo_type === "STANDARD_MISSING" && row.missing_columns.length > 0,
              expandedRowRender: (row) => (
                <Table
                  size="small"
                  rowKey="column_name"
                  pagination={false}
                  dataSource={row.missing_columns}
                  columns={[
                    { title: "字段名", dataIndex: "column_name", width: 200 },
                    { title: "类型", dataIndex: "raw_type", width: 140 },
                    {
                      title: "源库注释",
                      dataIndex: "raw_comment",
                      render: (value: string | null) =>
                        value || <Typography.Text type="secondary">（无注释）</Typography.Text>,
                    },
                    {
                      title: "出路",
                      dataIndex: "has_draft_candidate",
                      width: 160,
                      render: (value: boolean) => (
                        <Tag color={value ? "blue" : "default"}>
                          {value ? "已有候选，去工作台定版" : "需新建标准或人工归组"}
                        </Tag>
                      ),
                    },
                  ]}
                />
              ),
            }}
            pagination={{
              current: openQuery.data?.page ?? openPage,
              pageSize: PAGE_SIZE,
              total: openQuery.data?.total ?? 0,
              showSizeChanger: false,
              onChange: setOpenPage,
            }}
          />
        )}

        <Typography.Title level={5} style={{ margin: 0 }}>
          已处理 / 豁免清单（{closedQuery.data?.total ?? 0}）
        </Typography.Title>
        <Table<GovernanceTodo>
          rowKey="id"
          size="small"
          columns={closedColumns}
          dataSource={closedQuery.data?.items ?? []}
          loading={closedQuery.isLoading}
          locale={{ emptyText: <EmptyState simple description="暂无记录" /> }}
          pagination={{
            current: closedQuery.data?.page ?? closedPage,
            pageSize: PAGE_SIZE,
            total: closedQuery.data?.total ?? 0,
            showSizeChanger: false,
            onChange: setClosedPage,
          }}
        />
      </Space>

      <Modal
        title={exemptTarget ? `豁免 · ${rowLabel(exemptTarget)}` : "豁免"}
        open={exemptTarget !== null}
        onCancel={() => setExemptTarget(null)}
        onOk={submitExempt}
        okText="提交豁免"
        cancelText="取消"
        confirmLoading={resolveMutation.isPending}
        destroyOnHidden
      >
        {exemptTarget && (
          <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            <Typography.Text type="secondary">
              {exemptTarget.todo_type === "STANDARD_MISSING"
                ? `该表仍有 ${exemptTarget.missing_count} 个字段没关联已定版标准。豁免整表后不再重复提醒，只有缺口变大才会重新开单；仍会保留在豁免清单与治理看板中。`
                : `实际类型 ${exemptTarget.actual_type}，标准定义 ${exemptTarget.expected_type}。豁免后不再重复提醒，但会保留在豁免清单与治理看板中。`}
            </Typography.Text>
            <div>
              <Typography.Text strong>豁免原因（必填）</Typography.Text>
              <Input.TextArea
                style={{ marginTop: 8 }}
                rows={3}
                value={exemptReason}
                onChange={(event) => setExemptReason(event.target.value)}
                placeholder="如：外部供应商接口约定，不可修改；或 历史遗留表，改造排期在 Q1"
              />
            </div>
          </Space>
        )}
      </Modal>
    </Card>
  );
}
