import { parseSseBuffer } from "./answer";

export interface Source {
  number: number;
  title: string;
  section: string | null;
  source_type: string;
  source: string;
  snippet: string;
}

export interface Claim {
  text: string;
  verdict: "supported" | "partial" | "unsupported";
  sources: number[];
}

export interface Step {
  step: string;
  ms: number;
  detail: string;
}

export interface Result {
  question: string;
  answer: string;
  sources: Source[];
  citations: Source[];
  invalid_citations: number[];
  citation_coverage: number;
  // careful mode
  confidence?: "high" | "medium" | "low" | "unverified" | "none";
  support_rate?: number | null;
  claims?: Claim[];
  analysis?: { category?: string; summary?: string };
  search_query?: string;
  revisions?: number;
  models_used?: string[];
  trace?: Step[];
  total_ms?: number;
  // fast mode
  grounded?: boolean;
  provider?: string | null;
  model?: string | null;
  timings?: { retrieval_ms: number; generation_ms: number; total_ms: number };
}

export type StreamEvent =
  | ({ type: "step" } & Step)
  | { type: "sources"; sources: Source[] }
  | { type: "token"; text: string }
  | { type: "result"; result: Result }
  | { type: "saved"; conversation_id: string; message_id: string }
  | { type: "error"; detail: string };

export interface StoredMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  mode: "agent" | "fast" | null;
  result: Result | null;
  rating: "up" | "down" | null;
  fixed: boolean | null;
}

export interface ConversationSummary {
  id: string;
  title: string;
  created: number;
  updated: number;
}

export interface User {
  username: string;
  role: string;
}

export interface UploadedDocument {
  id: string;
  filename: string;
  uploaded_by: string;
  uploaded_at: number;
  access: string;
  characters: number;
}

export interface MetricsSummary {
  total_queries: number;
  errors: number;
  latency_ms: { p50: number | null; p95: number | null };
  mean_support_rate: number | null;
  by_endpoint: Record<string, number>;
  by_confidence: Record<string, number>;
  by_model: Record<string, number>;
  by_user: Record<string, number>;
  feedback: { answers: number; up: number; down: number; fixed: number; not_fixed: number };
  recent: {
    id: number;
    ts: number;
    username: string;
    endpoint: string;
    question: string;
    model: string | null;
    confidence: string | null;
    support_rate: number | null;
    total_ms: number | null;
    error: string | null;
  }[];
}

const TOKEN_KEY = "opsmind-token";
const USER_KEY = "opsmind-user";

function storage(): Storage | null {
  try {
    return sessionStorage;
  } catch {
    return null;
  }
}

export function savedUser(): User | null {
  try {
    const raw = storage()?.getItem(USER_KEY);
    return raw && storage()?.getItem(TOKEN_KEY) ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

export function clearSession(): void {
  storage()?.removeItem(TOKEN_KEY);
  storage()?.removeItem(USER_KEY);
}

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

export class ApiError extends Error {}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const token = storage()?.getItem(TOKEN_KEY);
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let response: Response;
  try {
    response = await fetch(path, { ...init, headers });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError("Can't reach the OpsMind server. Check that it's running.");
  }
  if (response.status === 401 && !path.startsWith("/auth/login")) {
    onUnauthorized();
    throw new ApiError("Your session expired. Log in again.");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : `Request failed (${response.status})`;
    throw new ApiError(detail);
  }
  return response;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  return (await request(path, init)).json() as Promise<T>;
}

const jsonBody = (body: unknown): RequestInit => ({
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export async function login(username: string, password: string): Promise<User> {
  const r = await json<{ access_token: string; username: string; role: string }>("/auth/login", {
    method: "POST",
    ...jsonBody({ username, password }),
  });
  const user = { username: r.username, role: r.role };
  storage()?.setItem(TOKEN_KEY, r.access_token);
  storage()?.setItem(USER_KEY, JSON.stringify(user));
  return user;
}

export const listConversations = () => json<ConversationSummary[]>("/conversations");
export const getConversation = (id: string) =>
  json<ConversationSummary & { messages: StoredMessage[] }>(`/conversations/${id}`);
export const deleteConversation = (id: string) => request(`/conversations/${id}`, { method: "DELETE" });
export const sendFeedback = (messageId: string, rating: "up" | "down" | null, fixed: boolean | null) =>
  request(`/conversations/messages/${messageId}/feedback`, { method: "PUT", ...jsonBody({ rating, fixed }) });

export const listUploads = () => json<UploadedDocument[]>("/documents/uploads");
export const documentStats = () => json<{ total: number; by_source_type: Record<string, number> }>("/documents/stats");
export const deleteUpload = (id: string) => request(`/documents/uploads/${id}`, { method: "DELETE" });
export function uploadDocument(file: File, access: string): Promise<UploadedDocument> {
  const form = new FormData();
  form.append("file", file);
  form.append("access", access);
  return json<UploadedDocument>("/documents/uploads", { method: "POST", body: form });
}

export const metricsSummary = (hours: number) => json<MetricsSummary>(`/metrics/summary?hours=${hours}&recent=25`);

export interface StreamRequest {
  question: string;
  conversation_id: string | null;
  mode: "agent" | "fast";
  provider: "openai_compat" | "ollama";
}

export async function streamAnswer(
  body: StreamRequest,
  onEvent: (event: StreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await request("/conversations/stream", { method: "POST", ...jsonBody(body), signal });
  const reader = response.body!.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    const { events, rest } = parseSseBuffer<StreamEvent>(buffer + value);
    buffer = rest;
    events.forEach(onEvent);
  }
}
