// data_size 后端以字节计，转人类可读。
export function formatBytes(value: number | null): string {
  if (value == null) {
    return "—";
  }
  if (value < 1024) {
    return `${value} B`;
  }
  const units = ["KB", "MB", "GB", "TB"];
  let size = value / 1024;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(1)} ${units[unit]}`;
}

export function formatCount(value: number | null): string {
  return value == null ? "—" : value.toLocaleString();
}
