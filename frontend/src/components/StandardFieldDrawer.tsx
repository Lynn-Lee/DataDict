import { useQuery } from "@tanstack/react-query";
import { Drawer, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";

import { getStandardField, type StandardFieldItem } from "@/api/standardFields";
import { ErrorState } from "@/components/QueryStates";

const ITEM_COLUMNS: ColumnsType<StandardFieldItem> = [
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

interface Props {
  standardId: number | null;
  onClose: () => void;
}

// 标准定义详情抽屉：定版信息 + 存量源字段 conforms 清单。工作台与定义库共用。
export default function StandardFieldDrawer({ standardId, onClose }: Props) {
  const detailQuery = useQuery({
    queryKey: ["standard-field-detail", standardId],
    queryFn: () => getStandardField(standardId as number),
    enabled: standardId !== null,
  });

  const detail = detailQuery.data;

  return (
    <Drawer
      title={detail ? `标准定义 · ${detail.standard_name}` : "标准定义详情"}
      width={720}
      open={standardId !== null}
      onClose={onClose}
      destroyOnHidden
    >
      {detailQuery.isLoading ? (
        <Typography.Text type="secondary">加载中…</Typography.Text>
      ) : detailQuery.isError ? (
        <ErrorState error={detailQuery.error} onRetry={() => void detailQuery.refetch()} />
      ) : detail ? (
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Space wrap>
            <Tag color={detail.status === "CONFIRMED" ? "green" : "blue"}>
              {detail.status === "CONFIRMED" ? `已定版 v${detail.version}` : "待确认"}
            </Tag>
            {detail.raw_type && (
              <Tag style={{ fontFamily: "monospace" }}>{detail.raw_type}</Tag>
            )}
            <Tag>{detail.logical_type}</Tag>
            <Typography.Text>{detail.business_meaning ?? "—"}</Typography.Text>
          </Space>
          <Typography.Text type="secondary">
            存量源字段 {detail.items.length} 个
            {detail.status === "CONFIRMED" &&
              `，符合 ${detail.items.filter((i) => i.conforms === true).length} 个`}
          </Typography.Text>
          <Table<StandardFieldItem>
            rowKey="column_urn"
            size="small"
            columns={ITEM_COLUMNS}
            dataSource={detail.items}
            pagination={{ pageSize: 10, showSizeChanger: false }}
          />
        </Space>
      ) : null}
    </Drawer>
  );
}
