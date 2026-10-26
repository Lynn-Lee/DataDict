import { ThunderboltOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Input,
  Modal,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useState } from "react";

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
};

export default function GovernanceTodosPage() {
  const queryClient = useQueryClient();
  const [exemptTarget, setExemptTarget] = useState<GovernanceTodo | null>(null);
  const [exemptReason, setExemptReason] = useState("");
  const [openPage, setOpenPage] = useState(1);
  const [closedPage, setClosedPage] = useState(1);

  const openQuery = useQuery({
    queryKey: ["governance-todos", "OPEN", openPage],
    queryFn: () => listGovernanceTodos({ status: "OPEN", page: openPage, pageSize: PAGE_SIZE }),
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
          `conforms 修正 ${summary.conforms_updated}，新待办 ${summary.todos_created}`,
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
      message.success(`${todo.table_name}.${todo.column_name}：${label}`);
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
      title: "字段",
      key: "column",
      width: 260,
      render: (_, row) => (
        <Space direction="vertical" size={0}>
          <Typography.Text code>
            {row.table_name}.{row.column_name}
          </Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {row.db_name}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: "实际类型",
      dataIndex: "actual_type",
      width: 130,
      render: (value: string | null) => <Tag color="red">{value}</Tag>,
    },
    {
      title: "已定版标准",
      key: "standard",
      width: 300,
      render: (_, row) => (
        <Space direction="vertical" size={0}>
          <Space size={4}>
            <Typography.Text code strong>
              {row.standard_name}
            </Typography.Text>
            <Tag color="green">{row.expected_type}</Tag>
          </Space>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {row.business_meaning}
          </Typography.Text>
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
      width: 220,
      render: (_, row) => (
        <Space size={4}>
          <Button
            type="primary"
            size="small"
            loading={resolveMutation.isPending}
            onClick={() => resolveMutation.mutate({ id: row.id, action: "ADOPT" })}
          >
            采纳标准
          </Button>
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
      title: "字段",
      key: "column",
      render: (_, row) => (
        <Typography.Text code>
          {row.table_name}.{row.column_name}
        </Typography.Text>
      ),
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
            每次同步后自动比对新增/变更字段与已定版标准；不一致的在此处理，豁免须填原因留痕。
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
          message="采纳标准 = 认可按标准改造（记入存量改造建议）；豁免 = 有正当理由维持现状（原因留痕、看板仍可见）；忽略 = 暂不处理。"
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
        title={
          exemptTarget
            ? `豁免 · ${exemptTarget.table_name}.${exemptTarget.column_name}`
            : "豁免"
        }
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
              实际类型 <Typography.Text code>{exemptTarget.actual_type}</Typography.Text>
              ，标准定义 <Typography.Text code>{exemptTarget.expected_type}</Typography.Text>
              。豁免后不再重复提醒，但会保留在豁免清单与治理看板中。
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
