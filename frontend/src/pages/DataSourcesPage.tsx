import { CloudServerOutlined, PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useState } from "react";

import {
  createDataSource,
  listDataSources,
  testDataSourceConnection,
  triggerDataSourceSync,
  updateDataSource,
  type DataSource,
  type DataSourcePayload,
  type ScopeRule,
} from "@/api/datasources";
import { EmptyState, ErrorState } from "@/components/QueryStates";

const ENV_OPTIONS = [
  { value: "prod", label: "生产" },
  { value: "pre", label: "预发" },
  { value: "test", label: "测试" },
];

const DB_TYPE_OPTIONS = [
  { value: "mysql", label: "MySQL（含 TiDB / StarRocks）" },
  { value: "postgresql", label: "PostgreSQL" },
];

const ENV_TAG_COLOR: Record<string, string> = { prod: "red", pre: "orange", test: "blue" };

// 采集范围规则：每行一条，`库模式` 或 `库模式:表模式`，支持 fnmatch 通配符。
function rulesToLines(rules: ScopeRule[]): string {
  return rules
    .map((rule) => (rule.table ? `${rule.db ?? "*"}:${rule.table}` : (rule.db ?? "*")))
    .join("\n");
}

function linesToRules(text: string | undefined): ScopeRule[] {
  return (text ?? "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const idx = line.indexOf(":");
      if (idx === -1) return { db: line };
      return { db: line.slice(0, idx), table: line.slice(idx + 1) };
    });
}

interface FormValues {
  code: string;
  name: string;
  db_type: string;
  env: string;
  host: string;
  port: number;
  default_db?: string;
  username: string;
  password?: string;
  sync_cron: string;
  group_name?: string;
  enabled: boolean;
  include_rules_text?: string;
  exclude_rules_text?: string;
}

export default function DataSourcesPage() {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<DataSource | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [testingId, setTestingId] = useState<number | null>(null);
  const [syncingId, setSyncingId] = useState<number | null>(null);
  const [form] = Form.useForm<FormValues>();

  const listQuery = useQuery({
    queryKey: ["datasources"],
    queryFn: () => listDataSources(),
  });

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ["datasources"] });

  const saveMutation = useMutation({
    mutationFn: (vars: { id: number | null; payload: DataSourcePayload }) =>
      vars.id === null
        ? createDataSource(vars.payload)
        : updateDataSource(vars.id, vars.payload),
    onSuccess: (_, vars) => {
      message.success(vars.id === null ? "数据源已创建" : "数据源已更新");
      setModalOpen(false);
      invalidate();
    },
    onError: (err) => message.error(err instanceof Error ? err.message : "保存失败"),
  });

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({
      db_type: "mysql",
      env: "prod",
      port: 3306,
      sync_cron: "0 2 * * *",
      enabled: true,
    });
    setModalOpen(true);
  };

  const openEdit = (row: DataSource) => {
    setEditing(row);
    form.setFieldsValue({
      code: row.code,
      name: row.name,
      db_type: row.db_type,
      env: row.env,
      host: row.host,
      port: row.port,
      default_db: row.default_db ?? undefined,
      username: row.username,
      password: undefined,
      sync_cron: row.sync_cron ?? "0 2 * * *",
      group_name: row.group_name ?? undefined,
      enabled: row.enabled,
      include_rules_text: rulesToLines(row.include_rules),
      exclude_rules_text: rulesToLines(row.exclude_rules),
    });
    setModalOpen(true);
  };

  const submit = async () => {
    const values = await form.validateFields();
    saveMutation.mutate({
      id: editing?.id ?? null,
      payload: {
        code: values.code,
        name: values.name,
        db_type: values.db_type,
        env: values.env,
        host: values.host,
        port: values.port,
        default_db: values.default_db || null,
        username: values.username,
        password: values.password || null,
        include_rules: linesToRules(values.include_rules_text),
        exclude_rules: linesToRules(values.exclude_rules_text),
        sync_cron: values.sync_cron,
        group_name: values.group_name || null,
        enabled: values.enabled,
      },
    });
  };

  const onTest = async (row: DataSource) => {
    setTestingId(row.id);
    try {
      const result = await testDataSourceConnection(row.id);
      if (result.ok) {
        message.success(`${row.name}：${result.message}`);
      } else {
        message.error(`${row.name}：${result.message}`, 6);
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : "连接测试失败");
    } finally {
      setTestingId(null);
    }
  };

  const onSync = async (row: DataSource) => {
    setSyncingId(row.id);
    try {
      await triggerDataSourceSync(row.id);
      message.success(`已触发「${row.name}」同步，后台执行中`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "触发同步失败");
    } finally {
      setSyncingId(null);
    }
  };

  const onToggleEnabled = async (row: DataSource, enabled: boolean) => {
    try {
      await updateDataSource(row.id, {
        code: row.code,
        name: row.name,
        db_type: row.db_type,
        env: row.env,
        host: row.host,
        port: row.port,
        default_db: row.default_db,
        username: row.username,
        include_rules: row.include_rules,
        exclude_rules: row.exclude_rules,
        sync_cron: row.sync_cron ?? "0 2 * * *",
        group_name: row.group_name,
        enabled,
      });
      message.success(enabled ? `已启用「${row.name}」` : `已停用「${row.name}」（元数据保留）`);
      invalidate();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "操作失败");
    }
  };

  const columns: ColumnsType<DataSource> = [
    {
      title: "编码",
      dataIndex: "code",
      width: 170,
      render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
    },
    { title: "名称", dataIndex: "name", width: 160, ellipsis: true },
    {
      title: "类型",
      dataIndex: "db_type",
      width: 110,
      render: (value: string) => <Tag>{value}</Tag>,
    },
    {
      title: "环境",
      dataIndex: "env",
      width: 80,
      render: (value: string) => (
        <Tag color={ENV_TAG_COLOR[value] ?? "default"}>
          {ENV_OPTIONS.find((o) => o.value === value)?.label ?? value}
        </Tag>
      ),
    },
    {
      title: "地址",
      key: "address",
      width: 200,
      ellipsis: true,
      render: (_, row) => (
        <Typography.Text style={{ fontFamily: "monospace", fontSize: 12 }}>
          {row.host}:{row.port}
          {row.default_db ? ` / ${row.default_db}` : ""}
        </Typography.Text>
      ),
    },
    { title: "同步周期", dataIndex: "sync_cron", width: 100 },
    {
      title: "最近同步",
      dataIndex: "last_sync_at",
      width: 160,
      render: (value: string | null) =>
        value ? (
          new Date(value).toLocaleString("zh-CN", { hour12: false })
        ) : (
          <Typography.Text type="secondary">未同步</Typography.Text>
        ),
    },
    {
      title: "启用",
      dataIndex: "enabled",
      width: 70,
      render: (value: boolean, row) => (
        <Switch size="small" checked={value} onChange={(next) => onToggleEnabled(row, next)} />
      ),
    },
    {
      title: "操作",
      key: "actions",
      width: 230,
      render: (_, row) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => openEdit(row)}>
            编辑
          </Button>
          <Button
            type="link"
            size="small"
            loading={testingId === row.id}
            onClick={() => void onTest(row)}
          >
            测试连接
          </Button>
          <Button
            type="link"
            size="small"
            loading={syncingId === row.id}
            disabled={!row.enabled}
            onClick={() => void onSync(row)}
          >
            立即同步
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <Card>
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Space style={{ justifyContent: "space-between", width: "100%" }}>
          <Typography.Text type="secondary">
            采集账号只需元数据只读权限（严禁业务表 SELECT）；密码加密存储、永不回显。
          </Typography.Text>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建数据源
          </Button>
        </Space>

        {listQuery.isError ? (
          <ErrorState
            error={listQuery.error}
            onRetry={() => void listQuery.refetch()}
            forbiddenMessage="无权限管理数据源"
            errorMessage="数据源列表加载失败"
          />
        ) : (
          <Table<DataSource>
            rowKey="id"
            size="middle"
            columns={columns}
            dataSource={listQuery.data?.items ?? []}
            loading={listQuery.isLoading}
            locale={{
              emptyText: <EmptyState simple={false} description="还没有数据源，点击右上角新建" />,
            }}
            pagination={{ pageSize: 20, showSizeChanger: false, showTotal: (t) => `共 ${t} 个` }}
          />
        )}
      </Space>

      <Modal
        title={
          editing ? (
            <Space>
              <CloudServerOutlined />
              编辑数据源 · {editing.code}
            </Space>
          ) : (
            <Space>
              <CloudServerOutlined />
              新建数据源
            </Space>
          )
        }
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void submit()}
        okText="保存"
        cancelText="取消"
        confirmLoading={saveMutation.isPending}
        width={640}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
          <Space.Compact block>
            <Form.Item
              name="code"
              label="编码（参与 URN，创建后不可改）"
              rules={[
                { required: true, message: "请输入编码" },
                { pattern: /^[a-z0-9_\-]+$/, message: "仅小写字母、数字、下划线、连字符" },
              ]}
              style={{ flex: 1, marginRight: 12 }}
            >
              <Input placeholder="prod_tidb_operdb" disabled={editing !== null} />
            </Form.Item>
            <Form.Item
              name="name"
              label="名称"
              rules={[{ required: true, message: "请输入名称" }]}
              style={{ flex: 1 }}
            >
              <Input placeholder="运营库（TiDB）" />
            </Form.Item>
          </Space.Compact>

          <Space.Compact block>
            <Form.Item name="db_type" label="类型" rules={[{ required: true }]} style={{ flex: 1, marginRight: 12 }}>
              <Select options={DB_TYPE_OPTIONS} />
            </Form.Item>
            <Form.Item name="env" label="环境" rules={[{ required: true }]} style={{ flex: 1, marginRight: 12 }}>
              <Select options={ENV_OPTIONS} />
            </Form.Item>
            <Form.Item name="group_name" label="分组" style={{ flex: 1 }}>
              <Input placeholder="运营" />
            </Form.Item>
          </Space.Compact>

          <Space.Compact block>
            <Form.Item
              name="host"
              label="主机"
              rules={[{ required: true, message: "请输入主机地址" }]}
              style={{ flex: 2, marginRight: 12 }}
            >
              <Input placeholder="10.0.0.1" />
            </Form.Item>
            <Form.Item name="port" label="端口" rules={[{ required: true }]} style={{ flex: 1, marginRight: 12 }}>
              <InputNumber min={1} max={65535} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item name="default_db" label="默认库" style={{ flex: 1 }}>
              <Input placeholder="operdb" />
            </Form.Item>
          </Space.Compact>

          <Space.Compact block>
            <Form.Item
              name="username"
              label="只读账号"
              rules={[{ required: true, message: "请输入账号" }]}
              style={{ flex: 1, marginRight: 12 }}
            >
              <Input placeholder="datadict_ro" autoComplete="off" />
            </Form.Item>
            <Form.Item
              name="password"
              label={editing ? "密码（留空不修改）" : "密码"}
              rules={editing ? [] : [{ required: true, message: "请输入密码" }]}
              style={{ flex: 1 }}
            >
              <Input.Password placeholder="加密存储，永不回显" autoComplete="new-password" />
            </Form.Item>
          </Space.Compact>

          <Form.Item
            name="include_rules_text"
            label="采集白名单（每行一条：库模式 或 库模式:表模式，支持 * 通配；留空采集全部）"
          >
            <Input.TextArea rows={2} placeholder={"operdb\nsales:t_order_*"} />
          </Form.Item>

          <Form.Item
            name="exclude_rules_text"
            label="采集黑名单（同上格式）"
          >
            <Input.TextArea rows={2} placeholder={"*:*_bak\n*:tmp_*"} />
          </Form.Item>

          <Space.Compact block>
            <Form.Item
              name="sync_cron"
              label="同步周期（cron）"
              rules={[{ required: true, message: "请输入 cron 表达式" }]}
              style={{ flex: 1, marginRight: 12 }}
            >
              <Input placeholder="0 2 * * *" />
            </Form.Item>
            <Form.Item name="enabled" label="启用" valuePropName="checked" style={{ flex: 1 }}>
              <Switch />
            </Form.Item>
          </Space.Compact>
        </Form>
      </Modal>
    </Card>
  );
}
