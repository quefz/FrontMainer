import "style.css";
import { api, errorText } from "./api";
import type {
  Action, Block, ChainResponse, Deal, DiskInfo, MempoolResponse, MineResult, NodeInfo,
  Report, SendResult, Tx, WalletInfo,
} from "./types";

type Tab = "wallet" | "mempool" | "mining" | "chain" | "deals" | "node";

const TABS: { id: Tab; title: string; hint: string }[] = [
  { id: "wallet", title: "Кошелёк", hint: "ключи, баланс, перевод" },
  { id: "mempool", title: "Мемпул", hint: "необработанные транзакции" },
  { id: "mining", title: "Майнинг", hint: "сборка блока, PoW" },
  { id: "chain", title: "Цепочка", hint: "блоки и целостность" },
  { id: "deals", title: "Сделки", hint: "смарт-контракт" },
  { id: "node", title: "Узел", hint: "настройки и диск" },
];

const S = {
  tab: "wallet" as Tab,
  node: null as NodeInfo | null,
  wallet: null as WalletInfo | null,
  mempool: null as MempoolResponse | null,
  chain: null as ChainResponse | null,
  deals: null as Deal[] | null,
  disk: null as DiskInfo | null,
  reports: new Map<string, Report>(),
  lastSend: null as SendResult | null,
  lastMine: null as MineResult | null,
  selected: new Set<string>(),
  fromDisk: false,
  openBlock: null as number | null,
  busy: "" as string,
  form: { action: "BUY" as Action, recipient_address: "", item_id: "", amount: "", fee: "0.1" },
  voterName: "",
  extTx: "",
  minerAddress: "",
  cfg: { node_name: "", api_base: "" },
};

const esc = (v: unknown) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
const short = (s: string | null | undefined, n = 8) =>
  !s ? "—" : s.length <= n * 2 + 1 ? s : `${s.slice(0, n)}…${s.slice(-n)}`;
const money = (n: number) => (Math.round(n * 1e8) / 1e8).toLocaleString("ru-RU", { maximumFractionDigits: 8 });
const when = (ts: number) =>
  ts ? new Date(ts * 1000).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";
const myAddr = () => S.wallet?.address ?? S.node?.wallet.address ?? "";
const quorum = () => S.mempool?.quorum ?? S.node?.quorum ?? 2;

function hashHtml(hash: string, difficulty = 3, n = 10) {
  const zeros = hash.slice(0, difficulty);
  const rest = hash.length > n * 2 ? `${hash.slice(difficulty, n)}…${hash.slice(-6)}` : hash.slice(difficulty);
  return `<span class="hash"><b>${esc(zeros)}</b>${esc(rest)}</span>`;
}

function addrHtml(addr: string) {
  const mine = addr === myAddr();
  return `<span class="addr${mine ? " mine" : ""}" title="${esc(addr)}">${mine ? "вы · " : ""}${esc(short(addr, 6))}</span>`;
}

function toast(text: string, kind: "ok" | "err" | "info" = "info") {
  const box = document.getElementById("toasts")!;
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = text;
  box.appendChild(el);
  setTimeout(() => el.classList.add("gone"), 4200);
  setTimeout(() => el.remove(), 4800);
}

async function run<T>(label: string, fn: () => Promise<T>): Promise<T | undefined> {
  S.busy = label;
  render();
  try {
    return await fn();
  } catch (err) {
    toast(errorText(err), "err");
    return undefined;
  } finally {
    S.busy = "";
    render();
  }
}

async function load(tab: Tab = S.tab) {
  const jobs: Promise<unknown>[] = [api.node().then((n) => {
    S.node = n;
    if (!S.cfg.node_name) S.cfg = { node_name: n.node_name, api_base: n.api_base };
    if (!S.minerAddress) S.minerAddress = n.wallet.address;
  })];
  if (tab === "wallet") jobs.push(api.wallet().then((w) => (S.wallet = w)));
  if (tab === "mempool" || tab === "mining") jobs.push(api.mempool().then((m) => (S.mempool = m)));
  if (tab === "chain") jobs.push(api.chain(S.fromDisk).then((c) => (S.chain = c)));
  if (tab === "deals") jobs.push(api.deals().then((d) => (S.deals = d)));
  if (tab === "node") jobs.push(api.disk().then((d) => (S.disk = d)));
  await Promise.all(jobs);
}

function reportHtml(rep: Report) {
  const icon = { ok: "✓", warn: "!", fail: "✗" };
  return `<ol class="receipt ${rep.valid ? "valid" : "invalid"}">
    ${rep.checks.map((c) => `<li class="${c.status}"><i>${icon[c.status]}</i><b>${esc(c.name)}</b><span>${esc(c.detail)}</span></li>`).join("")}
    <li class="verdict">${rep.valid ? "Транзакция корректна" : "Транзакция отклонена"}${rep.valid ? ` · спишется ${money(rep.cost)}` : ""}</li>
  </ol>`;
}

function stamp(text: string, kind: string) {
  return `<span class="stamp ${kind}">${esc(text)}</span>`;
}

function sourceLine(source?: string, error?: string | null) {
  if (error) return `<div class="banner warn">${esc(error)} Показаны данные с локального диска (зеркало).</div>`;
  if (source === "local") return `<div class="banner">Автономная частная сеть: всё хранится на диске этого узла.</div>`;
  return "";
}

function txRow(tx: Tx, extra = "") {
  const b = tx.body;
  return `<td class="mono" title="${esc(tx.tx_id)}">${esc(short(tx.tx_id, 5))}</td>
    <td>${stamp(b.action, b.action.toLowerCase())}</td>
    <td>${b.is_coinbase ? "<span class='addr sys'>" + esc(b.sender_address) + "</span>" : addrHtml(b.sender_address)}</td>
    <td>${addrHtml(b.recipient_address)}</td>
    <td>«${esc(b.item_id)}»</td>
    <td class="num">${money(b.amount)}</td>
    <td class="num muted">${money(b.fee)}</td>
    <td class="muted">${when(b.timestamp)}</td>${extra}`;
}

function viewWallet() {
  const w = S.wallet;
  if (!w) return `<p class="muted">Загрузка кошелька…</p>`;
  const f = S.form;
  const res = S.lastSend;
  return `${sourceLine(w.source, w.error)}
  <div class="grid two">
    <article class="sheet">
      <h3>Счёт узла</h3>
      <div class="balance">
        <div><small>Баланс</small><strong>${money(w.balance)}</strong></div>
        <div><small>В ожидании</small><span>−${money(w.locked)}</span></div>
        <div><small>Доступно</small><span class="accent">${money(w.available)}</span></div>
      </div>
      <dl class="keys">
        <dt>Адрес в сети</dt><dd><code>${esc(w.address)}</code><button class="link" data-act="copy" data-copy="${esc(w.address)}">копировать</button></dd>
        <dt>Bitcoin P2PKH</dt><dd><code>${esc(w.btc_address)}</code></dd>
        <dt>Публичный ключ (сжатый)</dt><dd><code class="wrap">${esc(w.compressed_public_key)}</code></dd>
        ${w.login ? `<dt>Логин</dt><dd>${esc(w.login)}</dd>` : ""}
      </dl>
      <div class="row">
        <label class="btn ghost">Загрузить keys.json<input type="file" accept=".json,application/json" data-act="import-keys" hidden></label>
        <button class="btn ghost" data-act="export-keys">Скачать ключи</button>
        <button class="btn ghost danger" data-act="gen-keys">Новые ключи</button>
      </div>
      <p class="note">Закрытый ключ хранится только на этом узле и подписывает транзакции локально (ECDSA, SECP256k1).</p>
    </article>

    <article class="sheet">
      <h3>Новая транзакция</h3>
      <form data-form="send" class="form">
        <div class="seg">${(["BUY", "SELL", "TRANSFER"] as Action[]).map((a) =>
          `<button type="button" class="${f.action === a ? "on" : ""}" data-act="set-action" data-v="${a}">${{ BUY: "Купить", SELL: "Продать", TRANSFER: "Перевод" }[a]}</button>`).join("")}</div>
        <label>Адрес контрагента<input data-field="recipient_address" value="${esc(f.recipient_address)}" placeholder="1… или адрес из сети" required></label>
        <label>ID конспекта (item_id)<input data-field="item_id" value="${esc(f.item_id)}" placeholder="math_from_Name" required></label>
        <div class="row">
          <label>Сумма<input data-field="amount" type="number" step="0.01" min="0.01" value="${esc(f.amount)}" required></label>
          <label>Комиссия<input data-field="fee" type="number" step="0.01" min="0" value="${esc(f.fee)}"></label>
        </div>
        <p class="note">${f.action === "SELL" ? "SELL — предложение продажи: списывается только комиссия, оплату пришлёт покупатель транзакцией BUY с тем же item_id." : f.action === "BUY" ? "BUY — оплата конспекта продавцу. Сделка исполнится, если у продавца есть SELL с тем же item_id и ценой." : "Простой перевод монет."}</p>
        <button class="btn" type="submit" ${S.busy ? "disabled" : ""}>Подписать и отправить</button>
      </form>
      ${res ? `<div class="result"><h4>${res.success ? "Отправлено" : "Не принято"} · <span class="mono">${esc(short(res.tx.tx_id, 8))}</span></h4>
        ${res.warning ? `<div class="banner warn">${esc(res.warning)}</div>` : ""}
        ${reportHtml(res.report)}
        <details><summary>Подписанная транзакция и ответ сервера</summary><pre>${esc(JSON.stringify({ tx: res.tx, server: res.server_response }, null, 2))}</pre></details></div>` : ""}
    </article>
  </div>

  <article class="sheet">
    <h3>История счёта</h3>
    ${w.history.length ? `<table class="ledger"><thead><tr><th>TxID</th><th>Тип</th><th>От</th><th>Кому</th><th>Предмет</th><th class="num">Сумма</th><th class="num">Ком.</th><th>Время</th><th>Статус</th></tr></thead>
    <tbody>${w.history.map((t) => `<tr>${txRow(t, `<td>${t.status === "confirmed" ? stamp(`блок #${t.block_index}`, "ok") : stamp("в мемпуле", "wait")}</td>`)}</tr>`).join("")}</tbody></table>`
      : `<p class="muted">Операций пока нет.</p>`}
  </article>`;
}

function viewMempool() {
  const m = S.mempool;
  if (!m) return `<p class="muted">Загрузка мемпула…</p>`;
  const q = m.quorum;
  const local = S.node?.mode === "local";
  return `${sourceLine(m.source, m.error)}
  <article class="sheet">
    <div class="sheet-head"><h3>Необработанные транзакции <small>${m.transactions.length}</small></h3>
      <label class="inline">Голосовать от имени узла
        <input data-field="voterName" value="${esc(S.voterName)}" placeholder="${esc(S.node?.node_name ?? "")}"></label></div>
    ${local ? `<p class="note">В частной сети валидаторов имитируют разными именами узлов: для кворума нужно ${q} разных голоса.</p>` : ""}
    ${m.transactions.length ? `<table class="ledger"><thead><tr><th>TxID</th><th>Тип</th><th>От</th><th>Кому</th><th>Предмет</th><th class="num">Сумма</th><th class="num">Ком.</th><th>Время</th><th>Голоса</th><th></th></tr></thead>
    <tbody>${m.transactions.map((t) => {
      const rep = S.reports.get(t.tx_id);
      const pct = Math.min(100, (t.votes / q) * 100);
      return `<tr class="${t.ready ? "ready" : ""}">${txRow(t, `
        <td><div class="votes" title="${esc(t.voters.join(", ") || "нет голосов")}"><span style="width:${pct}%"></span></div><small>${t.votes}/${q}</small></td>
        <td class="actions"><button class="btn tiny ghost" data-act="verify" data-id="${esc(t.tx_id)}">Проверить</button>
          <button class="btn tiny" data-act="vote" data-id="${esc(t.tx_id)}" ${S.busy ? "disabled" : ""}>Подтвердить</button></td>`)}</tr>
        ${rep ? `<tr class="report-row"><td colspan="10">${reportHtml(rep)}</td></tr>` : ""}`;
    }).join("")}</tbody></table>` : `<p class="muted">Мемпул пуст — новых транзакций нет.</p>`}
  </article>

  <article class="sheet">
    <h3>Принять подписанную транзакцию</h3>
    <p class="note">Вставьте JSON вида {"tx_id", "body", "signature"} от лёгкого узла — узел проверит подпись и средства и сохранит транзакцию в список необработанных.</p>
    <textarea data-field="extTx" rows="5" placeholder='{"tx_id": "...", "body": {...}, "signature": "..."}'>${esc(S.extTx)}</textarea>
    <button class="btn" data-act="submit-ext">Принять в мемпул</button>
  </article>`;
}

function viewMining() {
  const m = S.mempool;
  if (!m) return `<p class="muted">Загрузка…</p>`;
  const ready = m.transactions.filter((t) => t.ready);
  const fees = ready.filter((t) => !S.selected.size || S.selected.has(t.tx_id)).reduce((s, t) => s + Number(t.body.fee), 0);
  const r = S.lastMine;
  return `${sourceLine(m.source, m.error)}
  <div class="grid two">
    <article class="sheet">
      <h3>Готовы к включению в блок <small>кворум ≥ ${m.quorum}</small></h3>
      ${ready.length ? `<ul class="picklist">${ready.map((t) => `<li>
        <label><input type="checkbox" data-act="toggle-sel" data-id="${esc(t.tx_id)}" ${S.selected.has(t.tx_id) ? "checked" : ""}>
        <span class="mono">${esc(short(t.tx_id, 5))}</span> ${stamp(t.body.action, t.body.action.toLowerCase())}
        <span>${money(t.body.amount)}</span><span class="muted">+${money(t.body.fee)}</span><span>«${esc(t.body.item_id)}»</span></label></li>`).join("")}</ul>
        <p class="note">${S.selected.size ? `Выбрано ${S.selected.size}` : "Ничего не выбрано — войдут все готовые"}. Каждая транзакция будет заново проверена (подпись, средства, повтор).</p>`
        : `<p class="muted">Нет транзакций с кворумом. Подтвердите транзакции во вкладке «Мемпул».</p>`}
      <label>Адрес для награды (coinbase)<input data-field="minerAddress" value="${esc(S.minerAddress)}"></label>
      <div class="row between"><span>Награда: <b>${money(fees)}</b> · сложность ${S.node?.difficulty ?? 3}</span>
        <button class="btn" data-act="mine" ${ready.length && !S.busy ? "" : "disabled"}>${S.busy === "mine" ? "Перебираю nonce…" : "Смайнить блок"}</button></div>
    </article>

    <article class="sheet">
      <h3>Результат Proof-of-Work</h3>
      ${r ? `<div class="pow">
        <div><small>Блок</small><strong>#${r.block.index}</strong></div>
        <div><small>nonce</small><strong>${r.block.nonce.toLocaleString("ru-RU")}</strong></div>
        <div><small>попыток</small><strong>${r.attempts.toLocaleString("ru-RU")}</strong></div>
        <div><small>время</small><strong>${r.seconds} с</strong></div></div>
        <p>Хэш: ${hashHtml(r.block.hash, r.block.difficulty, 64)}</p>
        <p class="muted">prev_hash: <span class="mono">${esc(short(r.block.prev_hash, 12))}</span> · транзакций: ${r.block.transactions.length} (включая coinbase)</p>
        ${r.rejected.length ? `<h4>Отклонены при сборке</h4>${r.rejected.map(reportHtml).join("")}` : ""}
        ${r.serv_responce ? `<details><summary>Ответ сервера</summary><pre>${esc(JSON.stringify(r.serv_responce, null, 2))}</pre></details>` : ""}`
        : `<p class="muted">Здесь появится найденный nonce и хэш, начинающийся с «000».</p>`}
    </article>
  </div>`;
}

function viewChain() {
  const c = S.chain;
  if (!c) return `<p class="muted">Загрузка цепочки…</p>`;
  const v = c.validation;
  const blocks = [...c.chain].reverse();
  return `<div class="row between">
      <div class="banner ${v.valid ? "ok" : "warn"}">${v.valid ? `Целостность подтверждена: ${v.blocks} блок(ов), хэши, PoW и подписи верны.` : `Нарушена целостность: ${esc(v.errors.join("; "))}`}</div>
      <label class="inline"><input type="checkbox" data-act="toggle-disk" ${S.fromDisk ? "checked" : ""}> читать блоки из файлов на диске</label>
    </div>
    ${blocks.length ? `<ol class="chain">${blocks.map((b) => blockHtml(b)).join("")}</ol>` : `<p class="muted">Цепочка пуста.</p>`}`;
}

function blockHtml(b: Block) {
  const open = S.openBlock === b.index;
  const genesis = b.index === 0 && /^0+$/.test(b.prev_hash);
  return `<li class="block ${open ? "open" : ""}">
    <button class="block-head" data-act="open-block" data-index="${b.index}">
      <span class="idx">#${b.index}</span>
      ${genesis ? stamp("genesis", "gen") : ""}
      ${hashHtml(b.hash, b.difficulty)}
      <span class="muted">nonce ${b.nonce.toLocaleString("ru-RU")}</span>
      <span class="muted">${b.transactions.length} tx</span>
    </button>
    <div class="link-line">← prev <span class="mono">${esc(short(b.prev_hash, 10))}</span></div>
    ${open ? `<table class="ledger compact"><tbody>${b.transactions.map((t) => `<tr>${txRow(t)}</tr>`).join("")}</tbody></table>
      <details><summary>JSON блока</summary><pre>${esc(JSON.stringify(b, null, 2))}</pre></details>` : ""}
  </li>`;
}

function viewDeals() {
  const d = S.deals;
  if (!d) return `<p class="muted">Загрузка…</p>`;
  const label: Record<Deal["status"], [string, string]> = {
    completed: ["исполнена", "ok"], pending: ["ждёт блока", "wait"], awaiting_payment: ["ждёт оплаты BUY", "wait"],
    awaiting_offer: ["нет предложения SELL", "warn"], price_mismatch: ["цены не совпадают", "fail"],
  };
  const side = (s: Deal["sell"]) => (s ? `${money(s.amount)} ${s.confirmed ? "✓" : "…"}` : "—");
  return `<article class="sheet">
    <h3>Смарт-контракт «Сделка по конспекту»</h3>
    <p class="note">Условие исполнения: продавец публикует SELL покупателю, покупатель — BUY продавцу с тем же item_id и той же ценой; обе транзакции подтверждены в блоках.</p>
    ${d.length ? `<table class="ledger"><thead><tr><th>Конспект</th><th>Продавец</th><th>Покупатель</th><th class="num">SELL</th><th class="num">BUY</th><th>Состояние</th></tr></thead>
    <tbody>${d.map((x) => `<tr><td>«${esc(x.item_id)}»</td><td>${addrHtml(x.seller)}</td><td>${addrHtml(x.buyer)}</td>
      <td class="num">${side(x.sell)}</td><td class="num">${side(x.buy)}</td><td>${stamp(...label[x.status])}</td></tr>`).join("")}</tbody></table>`
      : `<p class="muted">Сделок BUY/SELL пока нет.</p>`}
  </article>`;
}

function viewNode() {
  const n = S.node;
  if (!n) return `<p class="muted">Загрузка…</p>`;
  const d = S.disk;
  return `<div class="grid two">
    <article class="sheet">
      <h3>Настройки узла</h3>
      <form data-form="config" class="form">
        <label>Имя узла (для голосования)<input data-field="cfg.node_name" value="${esc(S.cfg.node_name)}"></label>
        <label>Сервер владельца сети<input data-field="cfg.api_base" value="${esc(S.cfg.api_base)}"></label>
        <button class="btn" type="submit">Сохранить</button>
      </form>
      <dl class="keys">
        <dt>Правила консенсуса</dt><dd>кворум ${n.quorum} голоса · PoW «${"0".repeat(n.difficulty)}…» · комиссия по умолчанию ${n.default_fee}</dd>
        <dt>Высота частной сети</dt><dd>${n.local_height} блок(ов)</dd>
        <dt>Высота зеркала сети</dt><dd>${n.mirror_height} блок(ов)</dd>
      </dl>
      <div class="danger-zone"><p>Инициализировать частную сеть заново: удалить локальные блоки и создать новый Genesis block с эмиссией 1000 на адрес текущего кошелька.</p>
        <button class="btn ghost danger" data-act="reset-local">Создать Genesis заново</button></div>
    </article>
    <article class="sheet">
      <h3>Локальный диск</h3>
      ${d ? `<p class="muted mono">${esc(d.data_dir)}</p>
        <p>Прочитано из файлов: <b>${d.blocks_read_from_disk}</b> блок(ов), <b>${d.transactions_on_disk}</b> необработанных транзакций.</p>
        <table class="ledger compact"><tbody>${d.files.map((f) => `<tr><td class="mono">${esc(f.path)}</td><td class="num muted">${f.bytes.toLocaleString("ru-RU")} Б</td></tr>`).join("")}</tbody></table>`
        : `<p class="muted">Загрузка…</p>`}
    </article>
  </div>`;
}

function render() {
  const n = S.node;
  const app = document.getElementById("app")!;
  const active = document.activeElement as HTMLInputElement | null;
  const focusField = active?.dataset?.field;
  const caret = active && "selectionStart" in active ? active.selectionStart : null;
  const views: Record<Tab, () => string> = {
    wallet: viewWallet, mempool: viewMempool, mining: viewMining, chain: viewChain, deals: viewDeals, node: viewNode,
  };
  const counts: Partial<Record<Tab, string>> = {
    mempool: S.mempool ? String(S.mempool.transactions.length) : "",
    mining: S.mempool ? String(S.mempool.transactions.filter((t) => t.ready).length) : "",
  };
  const tab = TABS.find((t) => t.id === S.tab)!;
  app.innerHTML = `<div class="frame">
    <aside class="rail">
      <div class="brand"><span class="mark">₲</span><div><b>Гроссбух</b><small>полный узел · кошелёк</small></div></div>
      <div class="node-card">
        <small>узел</small><strong>${esc(n?.node_name ?? "…")}</strong>
        <div class="mode">
          <button class="${n?.mode === "remote" ? "on" : ""}" data-act="mode" data-v="remote">Сеть владельца</button>
          <button class="${n?.mode === "local" ? "on" : ""}" data-act="mode" data-v="local">Частная сеть</button>
        </div>
        <small class="addr-line" title="${esc(n?.wallet.address)}">${esc(short(n?.wallet.address, 7))}</small>
      </div>
      <nav>${TABS.map((t) => `<button class="${S.tab === t.id ? "on" : ""}" data-act="tab" data-v="${t.id}">
        <span>${t.title}${counts[t.id] ? `<em>${counts[t.id]}</em>` : ""}</span><small>${t.hint}</small></button>`).join("")}</nav>
      <footer>${n?.mode === "remote" ? esc(n.api_base) : "data/local — автономно"}</footer>
    </aside>
    <main>
      <header class="topline"><div><h1>${tab.title}</h1><p>${tab.hint}</p></div>
        <button class="btn ghost" data-act="refresh" ${S.busy ? "disabled" : ""}>${S.busy ? "Работаю…" : "Обновить"}</button></header>
      <section class="content">${views[S.tab]()}</section>
    </main>
  </div>`;
  if (focusField) {
    const el = app.querySelector<HTMLInputElement>(`[data-field="${focusField}"]`);
    if (el) {
      el.focus();
      if (caret !== null && el.type !== "number") el.setSelectionRange(caret, caret);
    }
  }
}

function setField(path: string, value: string) {
  if (path.startsWith("cfg.")) (S.cfg as Record<string, string>)[path.slice(4)] = value;
  else if (path in S.form) (S.form as Record<string, string>)[path] = value;
  else (S as unknown as Record<string, string>)[path] = value;
}

async function onAct(el: HTMLElement) {
  const act = el.dataset.act!;
  const id = el.dataset.id ?? "";
  switch (act) {
    case "tab":
      S.tab = el.dataset.v as Tab;
      render();
      await run("load", () => load());
      break;
    case "refresh":
      await run("load", () => load());
      break;
    case "mode":
      await run("mode", async () => {
        S.node = await api.config({ mode: el.dataset.v as "remote" | "local" });
        S.reports.clear();
        S.selected.clear();
        await load();
        toast(S.node.mode === "local" ? "Узел работает в частной сети" : "Узел подключён к сети владельца", "ok");
      });
      break;
    case "copy":
      await navigator.clipboard?.writeText(el.dataset.copy ?? "");
      toast("Адрес скопирован", "ok");
      break;
    case "set-action":
      S.form.action = el.dataset.v as Action;
      render();
      break;
    case "gen-keys":
      if (!confirm("Создать новую пару ключей? Текущие ключи будут заменены — сначала скачайте их.")) return;
      await run("keys", async () => {
        await api.generate();
        await load();
        toast("Созданы новые ключи SECP256k1", "ok");
      });
      break;
    case "export-keys":
      await run("keys", async () => {
        const keys = await api.exportKeys();
        const a = document.createElement("a");
        a.href = URL.createObjectURL(new Blob([JSON.stringify(keys, null, 2)], { type: "application/json" }));
        a.download = `${keys.login || "node"}_keys.json`;
        a.click();
      });
      break;
    case "verify":
      await run("verify", async () => {
        S.reports.set(id, await api.verify(id));
      });
      break;
    case "vote":
      await run("vote", async () => {
        const r = await api.vote(id, S.voterName.trim() || undefined);
        toast(r.votes !== undefined ? `Голос учтён: ${r.votes}/${quorum()}` : "Голос отправлен на сервер", "ok");
        S.mempool = await api.mempool();
      });
      break;
    case "submit-ext":
      await run("submit", async () => {
        let tx: Tx;
        try {
          tx = JSON.parse(S.extTx);
        } catch {
          throw new Error("Это не JSON");
        }
        const r = await api.submit(tx);
        S.reports.set(tx.tx_id, r.report);
        S.extTx = "";
        S.mempool = await api.mempool();
        toast("Транзакция проверена и принята", "ok");
      });
      break;
    case "toggle-sel":
      if (S.selected.has(id)) S.selected.delete(id);
      else S.selected.add(id);
      render();
      break;
    case "mine":
      await run("mine", async () => {
        S.lastMine = await api.mine([...S.selected], S.minerAddress.trim() || myAddr());
        S.selected.clear();
        S.mempool = await api.mempool();
        toast(`Блок #${S.lastMine.block.index} смайнен: ${S.lastMine.block.hash.slice(0, 10)}…`, "ok");
      });
      break;
    case "toggle-disk":
      S.fromDisk = !S.fromDisk;
      await run("load", () => load());
      break;
    case "open-block": {
      const idx = Number(el.dataset.index);
      S.openBlock = S.openBlock === idx ? null : idx;
      render();
      break;
    }
    case "reset-local":
      if (!confirm("Удалить блоки частной сети и создать новый Genesis block?")) return;
      await run("reset", async () => {
        await api.resetLocal();
        await load();
        toast("Создан новый Genesis block", "ok");
      });
      break;
  }
}

document.addEventListener("click", (e) => {
  const el = (e.target as HTMLElement).closest<HTMLElement>("[data-act]");
  if (!el || el.tagName === "INPUT" && (el as HTMLInputElement).type === "file") return;
  if (el.tagName === "INPUT" && (el as HTMLInputElement).type === "checkbox") {
    e.preventDefault();
  }
  void onAct(el);
});

document.addEventListener("input", (e) => {
  const el = e.target as HTMLInputElement;
  if (el.dataset.field) setField(el.dataset.field, el.value);
});

document.addEventListener("change", async (e) => {
  const el = e.target as HTMLInputElement;
  if (el.dataset.act !== "import-keys" || !el.files?.[0]) return;
  const text = await el.files[0].text();
  await run("keys", async () => {
    let keys: object;
    try {
      keys = JSON.parse(text);
    } catch {
      throw new Error("Файл ключей должен быть JSON");
    }
    const w = await api.importKeys(keys);
    await load();
    toast(`Ключи загружены: ${short(w.address, 6)}`, "ok");
  });
});

document.addEventListener("submit", async (e) => {
  const form = e.target as HTMLFormElement;
  e.preventDefault();
  if (form.dataset.form === "send") {
    const f = S.form;
    await run("send", async () => {
      S.lastSend = await api.send({
        action: f.action, recipient_address: f.recipient_address.trim(), item_id: f.item_id.trim(),
        amount: Number(f.amount), fee: Number(f.fee || 0),
      });
      toast("Транзакция подписана и отправлена", "ok");
      S.wallet = await api.wallet();
    });
  }
  if (form.dataset.form === "config") {
    await run("config", async () => {
      S.node = await api.config(S.cfg);
      toast("Настройки сохранены", "ok");
    });
  }
});

setInterval(() => {
  if (!S.busy && (S.tab === "mempool" || S.tab === "mining") && document.visibilityState === "visible") {
    api.mempool().then((m) => { S.mempool = m; render(); }).catch(() => undefined);
  }
}, 15_000);

render();
void run("load", () => load());