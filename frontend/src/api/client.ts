// 统一 API 客户端：注入 Bearer 令牌，解析后端 {code, message} 错误体。
// 后端错误码见 app/core/exceptions.py（DATADICT-xxxx）。

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";

const TOKEN_KEY = "datadict_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: Record<string, unknown>;

  constructor(
    status: number,
    code: string,
    message: string,
    detail: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  params?: Record<string, string | number | boolean | undefined>;
  auth?: boolean;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, params, auth = true } = options;

  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) {
        url.searchParams.set(key, String(value));
      }
    }
  }

  const headers: Record<string, string> = {};
  // FormData（文件上传）不设 Content-Type，交给浏览器带 boundary
  if (body !== undefined && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  if (auth) {
    const token = getToken();
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  }

  const response = await fetch(url.toString(), {
    method,
    headers,
    body:
      body === undefined
        ? undefined
        : body instanceof FormData
          ? body
          : JSON.stringify(body),
  });

  if (!response.ok) {
    let code = `HTTP-${response.status}`;
    let message = response.statusText;
    let detail: Record<string, unknown> = {};
    try {
      const payload = (await response.json()) as {
        code?: string;
        message?: string;
        detail?: Record<string, unknown>;
      };
      code = payload.code ?? code;
      message = payload.message ?? message;
      detail = payload.detail ?? {};
    } catch {
      // 非 JSON 错误体，保留状态码信息
    }
    throw new ApiError(response.status, code, message, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
