import axios, { AxiosError } from "axios";
import type {
  Action, ChainResponse, Deal, DiskInfo, MempoolResponse, MineResult, Mode, NodeInfo,
  Report, SendResult, Tx, WalletInfo, WalletPublic,
} from "./types";

const http = axios.create({
  baseURL: import.meta.env.VITE_NODE_URL ?? "",
  timeout: 60_000,
});

export function errorText(err: unknown): string {
  if (err instanceof AxiosError) {
    const detail = (err.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === "string") return detail;
    if (detail) return JSON.stringify(detail);
    if (!err.response) return "Узел не отвечает — запущен ли node.py?";
    return `${err.response.status}: ${err.message}`;
  }
  return String(err);
}

export const api = {
  node: () => http.get<NodeInfo>("/api/node").then((r) => r.data),
  config: (data: Partial<{ mode: Mode; node_name: string; api_base: string }>) =>
    http.post<NodeInfo>("/api/node/config", data).then((r) => r.data),
  resetLocal: () => http.post<{ genesis: unknown }>("/api/node/reset-local").then((r) => r.data),
  disk: () => http.get<DiskInfo>("/api/disk").then((r) => r.data),

  wallet: () => http.get<WalletInfo>("/api/wallet").then((r) => r.data),
  generate: () => http.post<WalletPublic>("/api/wallet/generate", {}).then((r) => r.data),
  importKeys: (keys: object) => http.post<WalletPublic>("/api/wallet/import", keys).then((r) => r.data),
  exportKeys: () => http.get<Record<string, string>>("/api/wallet/export").then((r) => r.data),
  send: (data: { recipient_address: string; item_id: string; action: Action; amount: number; fee: number }) =>
    http.post<SendResult>("/api/wallet/send", data).then((r) => r.data),

  mempool: () => http.get<MempoolResponse>("/api/mempool").then((r) => r.data),
  verify: (txId: string) =>
    http.get<Report>(`/api/mempool/${encodeURIComponent(txId)}/verify`).then((r) => r.data),
  submit: (tx: Tx) => http.post<SendResult>("/api/tx/submit", tx).then((r) => r.data),
  vote: (tx_id: string, node_name?: string) =>
    http.post<{ success: boolean; votes?: number; server_response?: unknown }>("/api/vote", { tx_id, node_name })
      .then((r) => r.data),
  mine: (tx_ids: string[], miner_address: string) =>
    http.post<MineResult>("/api/mine", { tx_ids, miner_address }).then((r) => r.data),

  chain: (fromDisk = false) =>
    http.get<ChainResponse>("/api/chain", { params: { from_disk: fromDisk } }).then((r) => r.data),
  deals: () => http.get<{ deals: Deal[] }>("/api/deals").then((r) => r.data.deals),
};
