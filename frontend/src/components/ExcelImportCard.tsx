import { InboxOutlined } from "@ant-design/icons";
import { useMutation } from "@tanstack/react-query";
import { Alert, Button, Card, Checkbox, Descriptions, Space, Typography, Upload, message } from "antd";
import { useState } from "react";

import { importExcel, type ExcelImportReport } from "@/api/imports";

// Excel 历史数据字典种子导入（T-S5b）：上传 → 解析 →（可选仅预览）→ 写候选队列。
// 导入产生 PENDING/IMPORT 标注与 IMPORT 字典，不直接生效、不覆盖人工标注。
export default function ExcelImportCard() {
  const [file, setFile] = useState<File | null>(null);
  const [dryRun, setDryRun] = useState(true);
  const [report, setReport] = useState<ExcelImportReport | null>(null);

  const importMutation = useMutation({
    mutationFn: (vars: { file: File; dryRun: boolean }) => importExcel(vars.file, vars.dryRun),
    onSuccess: (result) => {
      setReport(result);
      message.success(
        result.dry_run
          ? `预览完成：${result.column_docs} 条字段文档 / ${result.dicts_parsed} 个字典（未写库）`
          : `导入完成：新增候选标注 ${result.annotations_created} 条，字典 ${result.dicts_imported} 个`,
      );
    },
    onError: (err) => message.error(err instanceof Error ? err.message : "导入失败"),
  });

  return (
    <Card size="small" title="Excel 种子导入（历史数据字典）">
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Typography.Text type="secondary">
          上传历史数据字典 .xlsx（≤20MB）。字段描述按「表名+字段名」匹配已同步字段，写为
          待确认（PENDING）候选标注，不覆盖人工标注；枚举字典进字典库。未匹配的部分在对应
          数据源同步后重新上传即可增量导入。
        </Typography.Text>

        <Upload.Dragger
          accept=".xlsx"
          maxCount={1}
          beforeUpload={(selected) => {
            setFile(selected);
            setReport(null);
            return false; // 阻止自动上传，由下方按钮统一提交
          }}
          onRemove={() => setFile(null)}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">点击或拖拽 .xlsx 文件到此处</p>
          <p className="ant-upload-hint">建议先勾选「仅预览」查看解析结果，再正式导入</p>
        </Upload.Dragger>

        <Space wrap>
          <Checkbox checked={dryRun} onChange={(event) => setDryRun(event.target.checked)}>
            仅预览（解析不写库）
          </Checkbox>
          <Button
            type="primary"
            disabled={!file}
            loading={importMutation.isPending}
            onClick={() => file && importMutation.mutate({ file, dryRun })}
          >
            {dryRun ? "解析预览" : "确认导入"}
          </Button>
        </Space>

        {report && (
          <>
            <Descriptions size="small" column={3} bordered>
              <Descriptions.Item label="Sheet 数">{report.sheets}</Descriptions.Item>
              <Descriptions.Item label="字段文档">{report.column_docs}</Descriptions.Item>
              <Descriptions.Item label="涉及表">{report.distinct_tables}</Descriptions.Item>
              <Descriptions.Item label="枚举字典">{report.dicts_parsed}</Descriptions.Item>
              {!report.dry_run && (
                <>
                  <Descriptions.Item label="匹配字段">{report.matched_columns}</Descriptions.Item>
                  <Descriptions.Item label="新增候选标注">
                    {report.annotations_created}
                  </Descriptions.Item>
                  <Descriptions.Item label="跳过（保护人工标注）">
                    {report.annotations_skipped_existing}
                  </Descriptions.Item>
                  <Descriptions.Item label="字典已导入">{report.dicts_imported}</Descriptions.Item>
                  <Descriptions.Item label="未匹配文档" span={2}>
                    {report.unmatched_docs}
                  </Descriptions.Item>
                </>
              )}
            </Descriptions>
            {report.dry_run ? (
              <Alert
                type="info"
                showIcon
                message="预览未写库。确认解析结果无误后，取消勾选「仅预览」再导入。"
              />
            ) : (
              report.unmatched_tables.length > 0 && (
                <Alert
                  type="warning"
                  showIcon
                  message={`有 ${report.unmatched_docs} 条文档未匹配到已同步字段`}
                  description={`未匹配表示例：${report.unmatched_tables.slice(0, 8).join("、")}${report.unmatched_tables.length > 8 ? " 等" : ""}。多因这些数据源尚未接入，同步后重新上传即可增量导入。`}
                />
              )
            )}
          </>
        )}
      </Space>
    </Card>
  );
}
