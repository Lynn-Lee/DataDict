import { apiRequest } from "@/api/client";

// Excel 种子导入接口，契约见后端 app/schemas/imports.py。
export interface ExcelImportReport {
  dry_run: boolean;
  sheets: number;
  column_docs: number;
  dicts_parsed: number;
  distinct_tables: number;
  matched_columns: number;
  annotations_created: number;
  annotations_skipped_existing: number;
  unmatched_docs: number;
  dicts_imported: number;
  unmatched_tables: string[];
}

export function importExcel(file: File, dryRun: boolean): Promise<ExcelImportReport> {
  const form = new FormData();
  form.append("file", file);
  return apiRequest<ExcelImportReport>("/imports/excel", {
    method: "POST",
    body: form,
    params: { dry_run: dryRun },
  });
}
