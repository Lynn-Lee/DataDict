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
          : `导入完成：留档 ${result.docs_stored} 条字段文档，字典 ${result.dicts_imported} 个，请点「重新聚类」生成候选`,
      );
    },
    onError: (err) => message.error(err instanceof Error ? err.message : "导入失败"),
  });

  return (
    <Card size="small" title="Excel 种子导入（历史数据字典）">
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Typography.Text type="secondary">
          上传历史数据字典 .xlsx（≤20MB）。Excel 与源库同步是平级的两路输入来源：字段文档
          原文留档，枚举字典进字典库；随后点「重新聚类」即按字段名取两路并集生成候选标准
          定义。同一文件重复上传会覆盖旧留档（幂等）。
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
                  <Descriptions.Item label="已留档文档">{report.docs_stored}</Descriptions.Item>
                  <Descriptions.Item label="与已同步字段重合">
                    {report.matched_synced_columns}
                  </Descriptions.Item>
                  <Descriptions.Item label="字典已导入">{report.dicts_imported}</Descriptions.Item>
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
              <Alert
                type="success"
                showIcon
                message="已留档为候选来源。点上方「重新聚类」，Excel 文档会与源库字段按字段名并集生成候选标准定义。"
              />
            )}
          </>
        )}
      </Space>
    </Card>
  );
}
