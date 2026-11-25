export type Mode = "remote" | "local";
export type Action = "BUY" | "SELL" | "TRANSFER";

export interface TxBody {
  sender_address: string;
  sender_pubkey?: string;
  recipient_address: string;
  item_id: string;
  action: string;
  amount: number;
  fee: number;
  timestamp: number;
  nonce: string;
  is_coinbase?: boolean;
  message?: string;
}

export interface Tx {
  tx_id: string;
  body: TxBody;
  signature: string;
}

export interface MempoolTx extends Tx {
  votes: number;
  voters: string[];
  ready: boolean;
  voted_by_me: boolean;
}

export interface HistoryTx extends Tx {
  status: "confirmed" | "pending";
  block_index: number | null;
}

export interface Block {
  index: number;
  prev_hash: string;
  transactions: Tx[];
  difficulty: number;
  nonce: number;
  hash: string;
}

export interface Check {
  name: string;
  status: "ok" | "warn" | "fail";
  detail: string;
}

export interface Report {
  tx_id: string;
  valid: boolean;
  cost: number;
  checks: Check[];
}

export interface WalletPublic {
  login: string | null;
  address: string;
  public_key: string;
  btc_address: string;
  compressed_public_key: string;
}

export interface WalletInfo extends WalletPublic {
  balance: number;
  locked: number;
  available: number;
  history: HistoryTx[];
  source: string;
  error: string | null;
}

export interface NodeInfo {
  node_name: string;
  mode: Mode;
  api_base: string;
  quorum: number;
  difficulty: number;
  default_fee: number;
  wallet: WalletPublic;
  local_height: number;
  mirror_height: number;
  data_dir: string;
}

export interface MempoolResponse {
  source: string;
  error: string | null;
  quorum: number;
  transactions: MempoolTx[];
}

export interface SendResult {
  success: boolean;
  tx: Tx;
  report: Report;
  server_response: unknown;
  warning?: string;
}

export interface MineResult {
  success: boolean;
  source: string;
  block: Block;
  rejected: Report[];
  attempts: number;
  seconds: number;
  serv_responce?: unknown;
}

export interface ChainResponse {
  source: string;
  chain: Block[];
  validation: { valid: boolean; blocks: number; errors: string[] };
}

export interface DealSide {
  tx_id: string;
  amount: number;
  timestamp: number;
  confirmed: boolean;
}

export interface Deal {
  seller: string;
  buyer: string;
  item_id: string;
  sell: DealSide | null;
  buy: DealSide | null;
  status: "completed" | "pending" | "awaiting_payment" | "awaiting_offer" | "price_mismatch";
}

export interface DiskInfo {
  data_dir: string;
  files: { path: string; bytes: number }[];
  blocks_read_from_disk: number;
  transactions_on_disk: number;
}
