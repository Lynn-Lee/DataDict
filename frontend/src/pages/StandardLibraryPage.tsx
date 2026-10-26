import { PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Input,
  Popover,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useEffect, useState } from "react";

import {
  attachTag,
  detachTag,
  listStandardLibrary,
  listTagOptions,
  type StandardFieldLibraryItem,
} from "@/api/standardFields";
import { EmptyState, ErrorState } from "@/components/QueryStates";
import StandardFieldDrawer from "@/components/StandardFieldDrawer";

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

// 业务标签编辑：同一标准释义在不同业务域的叫法，可打多个。
function TagsCell({ row }: { row: StandardFieldLibraryItem }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);

  const optionsQuery = useQuery({
    queryKey: ["standard-field-tag-options"],
    queryFn: listTagOptions,
    enabled: open,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["standard-library"] });
    void queryClient.invalidateQueries({ queryKey: ["standard-field-tag-options"] });
  };

  const attachMutation = useMutation({
    mutationFn: (name: string) => attachTag(row.id, name),
    onSuccess: () => {
      invalidate();
      setOpen(false);
    },
    onError: () => message.error("添加业务标签失败"),
  });

  const detachMutation = useMutation({
    mutationFn: (tagId: number) => detachTag(row.id, tagId),
    onSuccess: invalidate,
    onError: () => message.error("移除业务标签失败"),
  });

  return (
    <Space size={4} wrap>
      {row.tags.map((tag) => (
        <Tag
          key={tag.id}
          color="purple"
          closable
          onClose={(event) => {
            event.preventDefault();
            detachMutation.mutate(tag.id);
          }}
        >
          {tag.name}
        </Tag>
      ))}
      <Popover
        open={open}
        onOpenChange={setOpen}
        trigger="click"
        destroyOnHidden
        content={
          <Select
            mode="tags"
            autoFocus
            style={{ width: 220 }}
            placeholder="输入业务域叫法，回车添加"
            loading={optionsQuery.isLoading}
            options={(optionsQuery.data ?? []).map((name) => ({ value: name, label: name }))}
            onChange={(values: string[]) => {
              const next = values.find((v) => !row.tags.some((t) => t.name === v));
              if (next) attachMutation.mutate(next.trim());
            }}
          />
        }
      >
        <Button type="dashed" size="small" icon={<PlusOutlined />}>
          标签
        </Button>
      </Popover>
    </Space>
  );
}

export default function StandardLibraryPage() {
  const [keywordInput, setKeywordInput] = useState("");
  const [page, setPage] = useState(1);
  const [detailId, setDetailId] = useState<number | null>(null);

  const keyword = useDebouncedValue(keywordInput, DEBOUNCE_MS).trim() || undefined;
  useEffect(() => {
    setPage(1);
  }, [keyword]);

  const libraryQuery = useQuery({
    queryKey: ["standard-library", keyword, page],
    queryFn: () => listStandardLibrary({ q: keyword, page, pageSize: PAGE_SIZE }),
    placeholderData: (previous) => previous,
  });

  const columns: ColumnsType<StandardFieldLibraryItem> = [
    {
      title: "字段名",
      dataIndex: "standard_name",
      width: 180,
      render: (value: string, row) => (
        <Typography.Text
          strong
          code
          style={{ cursor: "pointer" }}
          onClick={() => setDetailId(row.id)}
        >
          {value}
        </Typography.Text>
      ),
    },
    {
      title: "标准类型",
      dataIndex: "raw_type",
      width: 140,
      render: (value: string | null) => (
        <Tag color="blue" style={{ fontFamily: "monospace" }}>
          {value}
        </Tag>
      ),
    },
    {
      title: "逻辑类型",
      dataIndex: "logical_type",
      width: 100,
      render: (value: string) => <Tag>{value}</Tag>,
    },
    {
      title: "标准释义",
      dataIndex: "business_meaning",
      ellipsis: true,
      render: (value: string | null) =>
        value || <Typography.Text type="secondary">—</Typography.Text>,
    },
    {
      title: "业务标签（各业务域叫法）",
      key: "tags",
      width: 280,
      render: (_, row) => <TagsCell row={row} />,
    },
    { title: "覆盖表数", dataIndex: "candidate_count", width: 90, align: "right" },
    {
      title: "操作",
      key: "actions",
      width: 120,
      render: (_, row) => (
        <Button type="link" size="small" onClick={() => setDetailId(row.id)}>
          存量字段
        </Button>
      ),
    },
  ];

  return (
    <Card>
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Space wrap style={{ justifyContent: "space-between", width: "100%" }}>
          <Input.Search
            allowClear
            placeholder="按业务释义或字段名查询，如：手机号 / waybill"
            style={{ width: 320 }}
            value={keywordInput}
            onChange={(event) => setKeywordInput(event.target.value)}
          />
          <Typography.Text type="secondary">
            终版标准定义供新表建模与 AI/MCP 查询：GET /api/v1/standard-fields/library
          </Typography.Text>
        </Space>

        {libraryQuery.isError ? (
          <ErrorState
            error={libraryQuery.error}
            onRetry={() => void libraryQuery.refetch()}
            forbiddenMessage="无权限访问标准定义库"
            errorMessage="标准定义库加载失败"
          />
        ) : (
          <Table<StandardFieldLibraryItem>
            rowKey="id"
            size="middle"
            columns={columns}
            dataSource={libraryQuery.data?.items ?? []}
            loading={libraryQuery.isLoading}
            locale={{
              emptyText: (
                <EmptyState
                  simple={false}
                  description="还没有已定版的标准定义，请先在标准定义工作台确认候选"
                />
              ),
            }}
            pagination={{
              current: libraryQuery.data?.page ?? page,
              pageSize: PAGE_SIZE,
              total: libraryQuery.data?.total ?? 0,
              showSizeChanger: false,
              showTotal: (total) => `共 ${total} 个标准定义`,
              onChange: setPage,
            }}
          />
        )}
      </Space>

      <StandardFieldDrawer standardId={detailId} onClose={() => setDetailId(null)} />
    </Card>
  );
}
