// ============================================================
// BRN P2P — Cliente híbrido (Ethers v5) + WebSocket
// ============================================================
const CONFIG = {
  CONTRACT_ADDRESS: "0x0000000000000000000000000000000000000000", // ← COLE AQUI
  CHAIN_ID: 137,
  USDC_ADDRESS: "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
  DEC_USDC: 6,
  DEC_COTACAO: 8,
  EXPLORER: "https://polygonscan.com",
};

const ABI_CONTRACT = [
  "function publicarOrdemOnChain((address criador,uint256 valorUSDC,uint256 cotacao,uint256 nonce,uint256 expiracao) _ordem, bytes _assinatura) external",
  "function executarOrdem((address criador,uint256 valorUSDC,uint256 cotacao,uint256 nonce,uint256 expiracao) _ordem, bytes _assinatura, address _comprador) external",
  "function cancelarOrdemOffChain(uint256 _nonce) external",
  "function nonceUtilizado(address,uint256) view returns (bool)",
];

const ABI_ERC20 = [
  "function balanceOf(address) view returns (uint256)",
  "function allowance(address,address) view returns (uint256)",
  "function approve(address,uint256) returns (bool)",
];

let provider, signer, endereco, contrato, usdcContrato;
let ws, wsReconnectTimer;
let ordensMural = {};
const MAX_UINT = "0x" + "f".repeat(64);

const $ = (id) => document.getElementById(id);

// ============================================================
// Utils
// ============================================================
function paraWei(str, decimals) {
  const s = String(str).trim().replace(",", ".");
  if (!/^\d+(\.\d+)?$/.test(s)) throw new Error("Valor invalido: " + str);
  const [i, f = ""] = s.split(".");
  const fp = (f + "0".repeat(decimals)).slice(0, decimals);
  return ethers.BigNumber.from(i + fp);
}

function deWei(big, decimals, casas = 6) {
  const s = ethers.utils.formatUnits(big, decimals);
  return Number(s).toLocaleString("pt-BR", {
    minimumFractionDigits: 2, maximumFractionDigits: casas,
  });
}

function msgErro(t) { $("mensagem").innerHTML = `<div class="msg msg-erro">❌ ${t}</div>`;
  setTimeout(() => $("mensagem").innerHTML = "", 7000); }
function msgOk(t)   { $("mensagem").innerHTML = `<div class="msg msg-ok">✅ ${t}</div>`;
  setTimeout(() => $("mensagem").innerHTML = "", 5000); }
function msgAviso(t){ $("mensagem").innerHTML = `<div class="msg msg-aviso">⏳ ${t}</div>`; }

function shortAddr(a) { return a.slice(0, 6) + "..." + a.slice(-4); }

// ============================================================
// Init
// ============================================================
async function init() {
  if (!window.ethereum) {
    msgErro("Instale a MetaMask: https://metamask.io");
    return;
  }
  if (CONFIG.CONTRACT_ADDRESS === "0x0000000000000000000000000000000000000000") {
    msgAviso("⚠️ Configure CONFIG.CONTRACT_ADDRESS no app.js");
  }

  provider = new ethers.providers.Web3Provider(window.ethereum, "any");

  window.ethereum.on("accountsChanged", async (contas) => {
    if (contas.length === 0) { location.reload(); return; }
    endereco = contas[0];
    signer = provider.getSigner();
    contrato = new ethers.Contract(CONFIG.CONTRACT_ADDRESS, ABI_CONTRACT, signer);
    usdcContrato = new ethers.Contract(CONFIG.USDC_ADDRESS, ABI_ERC20, signer);
    $("endereco-carteira").textContent = shortAddr(endereco);
    await atualizarSaldos();
    renderizarMural();
    renderizarMinhas();
  });
  window.ethereum.on("chainChanged", () => location.reload());

  const contas = await provider.listAccounts();
  if (contas.length > 0) await conectar();
  conectarWS();
  setInterval(renderizarMural, 1000);
}

// ============================================================
// Conectar
// ============================================================
async function conectar() {
  try {
    await provider.send("eth_requestAccounts", []);
    const net = await provider.getNetwork();
    if (Number(net.chainId) !== CONFIG.CHAIN_ID) {
      msgErro(`Rede errada (chainId ${net.chainId}). Use Polygon Mainnet.`);
      return;
    }
    signer = provider.getSigner();
    endereco = await signer.getAddress();
    contrato = new ethers.Contract(CONFIG.CONTRACT_ADDRESS, ABI_CONTRACT, signer);
    usdcContrato = new ethers.Contract(CONFIG.USDC_ADDRESS, ABI_ERC20, signer);

    $("btn-conectar").style.display = "none";
    $("endereco-carteira").textContent = shortAddr(endereco);
    $("endereco-carteira").style.display = "inline-block";

    await atualizarSaldos();
    renderizarMural();
    renderizarMinhas();
  } catch (e) {
    if (e.code === 4001) return;
    msgErro("Falha ao conectar: " + (e.message || e));
  }
}

async function atualizarSaldos() {
  if (!usdcContrato || !endereco) return;
  try {
    const [b, m] = await Promise.all([
      usdcContrato.balanceOf(endereco),
      provider.getBalance(endereco),
    ]);
    $("saldo-usdc").textContent = deWei(b, CONFIG.DEC_USDC) + " USDC";
    $("saldo-matic").textContent = ethers.utils.formatEther(m).slice(0, 8) + " MATIC";
  } catch (e) { console.error(e); }
}

// ============================================================
// Assinatura EIP-712
// ============================================================
function _domain() {
  return {
    name: "CarteiraBRN_P2P",
    version: "1",
    chainId: CONFIG.CHAIN_ID,
    verifyingContract: CONFIG.CONTRACT_ADDRESS,
  };
}
function _types() {
  return {
    Ordem: [
      { name: "criador",   type: "address" },
      { name: "valorUSDC", type: "uint256" },
      { name: "cotacao",   type: "uint256" },
      { name: "nonce",     type: "uint256" },
      { name: "expiracao", type: "uint256" },
    ],
  };
}

// ============================================================
// Criar ordem
// ============================================================
async function criarOrdem() {
  if (!signer) { await conectar(); return; }
  if (!signer) return;

  const usdcStr = $("venda-usdc").value.trim();
  const cotStr  = $("venda-cotacao").value.trim();
  const expMin  = Number($("venda-expiracao").value);
  const ancorar = $("ancorar-onchain").checked;

  if (!usdcStr || !cotStr) { msgErro("Preencha todos os campos"); return; }

  let valorUSDC, cotacao;
  try {
    valorUSDC = paraWei(usdcStr, CONFIG.DEC_USDC);
    cotacao   = paraWei(cotStr, CONFIG.DEC_COTACAO);
  } catch (e) { msgErro("Valor invalido"); return; }

  if (valorUSDC.lte(0) || cotacao.lte(0)) { msgErro("Valores devem ser positivos"); return; }

  const saldo = await usdcContrato.balanceOf(endereco);
  if (saldo.lt(valorUSDC)) {
    msgErro(`Saldo USDC insuficiente. Voce tem ${deWei(saldo, CONFIG.DEC_USDC)} USDC`);
    return;
  }

  // approve infinito (1 tx só)
  msgAviso("Verificando allowance USDC...");
  const allowance = await usdcContrato.allowance(endereco, CONFIG.CONTRACT_ADDRESS);
  if (allowance.lt(valorUSDC)) {
    try {
      msgAviso("Aprovando USDC (1x)...");
      const tx = await usdcContrato.approve(CONFIG.CONTRACT_ADDRESS, MAX_UINT);
      await tx.wait();
      msgOk("Aprovacao confirmada.");
    } catch (e) {
      if (e.code === 4001) { msgErro("Aprovacao cancelada"); return; }
      msgErro("Falha na aprovacao: " + (e.message || e));
      return;
    }
  }

  const nonce = Math.floor(Date.now() / 1000) * 1000 + Math.floor(Math.random() * 1000);
  const expiracao = Math.floor(Date.now() / 1000) + expMin * 60;

  const value = {
    criador: endereco,
    valorUSDC: valorUSDC.toString(),
    cotacao: cotacao.toString(),
    nonce: nonce.toString(),
    expiracao: expiracao.toString(),
  };

  try {
    msgAviso("Aguardando assinatura EIP-712 na carteira...");
    const assinatura = await signer._signTypedData(_domain(), _types(), value);
    const hash = ethers.utils._TypedDataEncoder.hash(_domain(), _types(), value);

    const ordem = {
      hash,
      criador: endereco,
      contratoAddress: CONFIG.CONTRACT_ADDRESS,
      valorOferecido: valorUSDC.toString(),
      valorDesejado: cotacao.toString(),
      valorUSDC: valorUSDC.toString(),
      cotacao: cotacao.toString(),
      nonce: nonce.toString(),
      expiracao,
      assinatura,
      chainId: CONFIG.CHAIN_ID,
    };

    msgAviso("Publicando no mural off-chain...");
    enviarWS({ tipo: "publicar_ordem", ordem });

    if (ancorar) {
      try {
        msgAviso("Ancorando on-chain (aguarde confirmacao)...");
        const struct = {
          criador: ordem.criador,
          valorUSDC: ordem.valorUSDC,
          cotacao: ordem.cotacao,
          nonce: ordem.nonce,
          expiracao: ordem.expiracao,
        };
        const tx = await contrato.publicarOrdemOnChain(struct, assinatura);
        msgAviso(`Tx: ${tx.hash.slice(0, 12)}...`);
        await tx.wait();
        msgOk("Ordem ancorada on-chain.");
      } catch (e) {
        if (e.code === 4001) { msgErro("Ancoragem cancelada (ordem off-chain segue ativa)"); }
        else { msgErro("Falha on-chain: " + (e.message || e)); }
      }
    }

    $("venda-usdc").value = "";
    $("venda-cotacao").value = "";
    $("ancorar-onchain").checked = false;
    $("total-estimado").textContent = "— BRL";
    if (!ancorar) msgOk("Ordem publicada off-chain.");
  } catch (e) {
    if (e.code === 4001) { msgErro("Assinatura cancelada"); return; }
    msgErro("Erro ao assinar: " + (e.message || e));
  }
}

// ============================================================
// Executar
// ============================================================
async function executarOrdem(hash) {
  const ordem = ordensMural[hash];
  if (!ordem) { msgErro("Ordem nao encontrada"); return; }
  if (!signer) { await conectar(); return; }
  if (!signer) return;
  if (ordem.criador.toLowerCase() === endereco.toLowerCase()) {
    msgErro("Voce nao pode comprar sua propria ordem"); return;
  }

  const usdcN = Number(ordem.valorUSDC) / 1e6;
  const cotN  = Number(ordem.cotacao) / 1e8;
  const total = usdcN * cotN;

  if (!confirm(
    `Confirmar compra?\n\n` +
    `USDC recebido: ${usdcN.toFixed(2)}\n` +
    `Cotacao: ${cotN.toFixed(2)} BRL/USDC\n` +
    `Total: ~R$ ${total.toFixed(2)}\n\n` +
    `⚠️ Combine o pagamento em BRL com o vendedor ANTES.`
  )) return;

  try {
    msgAviso("Enviando tx executarOrdem...");
    const struct = {
      criador: ordem.criador,
      valorUSDC: ordem.valorUSDC,
      cotacao: ordem.cotacao,
      nonce: ordem.nonce,
      expiracao: ordem.expiracao,
    };
    const tx = await contrato.executarOrdem(struct, ordem.assinatura, endereco);
    msgAviso(`Tx: ${tx.hash.slice(0, 12)}...`);
    await tx.wait();
    msgOk("Ordem executada! USDC recebido.");
    enviarWS({ tipo: "ordem_executada", hash, txHash: tx.hash });
    await atualizarSaldos();
  } catch (e) {
    if (e.code === 4001) { msgErro("Transacao cancelada"); return; }
    let d = e.message || String(e);
    if (e.data && e.data.message) d = e.data.message;
    msgErro("Falha: " + d);
  }
}

// ============================================================
// Cancelar
// ============================================================
async function cancelarOrdem(hash) {
  const ordem = ordensMural[hash];
  if (!ordem) { msgErro("Ordem nao encontrada"); return; }
  if (!signer) return;
  if (ordem.criador.toLowerCase() !== endereco.toLowerCase()) {
    msgErro("So o criador pode cancelar"); return;
  }
  if (!confirm("Cancelar esta ordem? A nonce sera marcada on-chain.")) return;

  try {
    msgAviso("Cancelando on-chain...");
    const tx = await contrato.cancelarOrdemOffChain(ordem.nonce);
    await tx.wait();
    msgOk("Ordem cancelada on-chain.");
    enviarWS({ tipo: "cancelar_ordem", hash });
  } catch (e) {
    if (e.code === 4001) { msgErro("Transacao cancelada"); return; }
    msgErro("Erro: " + (e.message || e));
  }
}

// ============================================================
// WebSocket
// ============================================================
function enviarWS(payload) {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    msgErro("Sem conexao com o servidor. Reconectando...");
    conectarWS();
    return;
  }
  ws.send(JSON.stringify(payload));
}

function conectarWS() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${proto}//${location.host}/ws`;
  try { ws = new WebSocket(url); } catch { agendarReconexao(); return; }

  ws.onopen = () => {
    $("ws-dot").className = "dot dot-on";
    $("ws-status").textContent = "Conectado";
    $("status-info").textContent = "Mural sincronizado";
  };
  ws.onclose = () => {
    $("ws-dot").className = "dot dot-off";
    $("ws-status").textContent = "Desconectado";
    agendarReconexao();
  };
  ws.onerror = () => { try { ws.close(); } catch {} };

  ws.onmessage = (ev) => {
    let msg; try { msg = JSON.parse(ev.data); } catch { return; }
    switch (msg.tipo) {
      case "snapshot":
        ordensMural = {};
        (msg.ordens || []).forEach(o => ordensMural[o.hash] = o);
        renderizarMural(); renderizarMinhas();
        break;
      case "nova_ordem": {
        const h = msg.ordem.hash;
        if (ordensMural[h]) {
          const fontes = new Set([...(ordensMural[h].fontes || []), ...(msg.ordem.fontes || [])]);
          ordensMural[h] = { ...ordensMural[h], ...msg.ordem, fontes: [...fontes] };
        } else {
          ordensMural[h] = msg.ordem;
        }
        renderizarMural(); renderizarMinhas();
        break;
      }
      case "ordem_cancelada":
      case "ordem_executada":
      case "ordem_expirada":
        delete ordensMural[msg.hash];
        renderizarMural(); renderizarMinhas();
        break;
      case "erro": msgErro("Servidor: " + msg.msg); break;
    }
  };
}

function agendarReconexao() {
  if (wsReconnectTimer) clearTimeout(wsReconnectTimer);
  wsReconnectTimer = setTimeout(conectarWS, 3000);
}

// ============================================================
// Render
// ============================================================
function _badgeFontes(fontes) {
  const set = new Set(fontes || []);
  const oc = set.has("off-chain");
  const on = set.has("on-chain");
  if (oc && on) return `<span class="tag tag-both">OC+ON</span>`;
  if (on)       return `<span class="tag tag-on">ON-CHAIN</span>`;
  if (oc)       return `<span class="tag tag-oc">OFF-CHAIN</span>`;
  return "";
}

function renderizarMural() {
  const tbody = $("lista-ordens");
  const agora = Math.floor(Date.now() / 1000);
  const lista = Object.values(ordensMural)
    .filter(o => Number(o.expiracao) > agora)
    .sort((a, b) => Number(b.cotacao) - Number(a.cotacao));

  $("stat-total").textContent = lista.length;
  $("stat-oc").textContent = lista.filter(o => (o.fontes||[]).includes("off-chain")).length;
  $("stat-on").textContent = lista.filter(o => (o.fontes||[]).includes("on-chain")).length;

  if (lista.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="vazio">
      Nenhuma ordem ativa. Seja o primeiro! 🚀</td></tr>`;
    return;
  }

  tbody.innerHTML = lista.map(o => {
    const usdcN = Number(o.valorUSDC) / 1e6;
    const cotN  = Number(o.cotacao) / 1e8;
    const total = usdcN * cotN;
    const seg   = Number(o.expiracao) - agora;
    const mm    = String(Math.floor(seg / 60)).padStart(2, "0");
    const ss    = String(seg % 60).padStart(2, "0");
    const eu    = endereco && o.criador.toLowerCase() === endereco.toLowerCase();
    const acao  = eu
      ? `<button class="btn btn-danger" onclick="cancelarOrdem('${o.hash}')">Cancelar</button>`
      : `<button class="btn btn-success" onclick="executarOrdem('${o.hash}')">Comprar</button>`;

    return `<tr>
      <td>${_badgeFontes(o.fontes)}</td>
      <td><span class="mono">${shortAddr(o.criador)}</span>
          ${eu ? '<div style="font-size:10px;color:#38bdf8;">você</div>' : ""}</td>
      <td><strong>${usdcN.toFixed(2)}</strong></td>
      <td>${cotN.toFixed(2)} BRL</td>
      <td style="color:#38bdf8;">R$ ${total.toFixed(2)}</td>
      <td style="color:#fbbf24;">${mm}:${ss}</td>
      <td style="text-align:right;">${acao}</td>
    </tr>`;
  }).join("");
}

function renderizarMinhas() {
  if (!endereco) { $("minhas-lista").innerHTML = "Conecte a carteira."; return; }
  const agora = Math.floor(Date.now() / 1000);
  const minhas = Object.values(ordensMural)
    .filter(o => o.criador.toLowerCase() === endereco.toLowerCase() && Number(o.expiracao) > agora);

  if (minhas.length === 0) { $("minhas-lista").innerHTML = "Você não tem ordens ativas."; return; }

  $("minhas-lista").innerHTML = minhas.map(o => {
    const usdcN = Number(o.valorUSDC) / 1e6;
    const cotN  = Number(o.cotacao) / 1e8;
    const total = usdcN * cotN;
    const seg   = Number(o.expiracao) - agora;
    const mm    = String(Math.floor(seg / 60)).padStart(2, "0");
    const ss    = String(seg % 60).padStart(2, "0");
    return `<div style="background:#0f172a;border:1px solid #334155;border-radius:6px;padding:12px;margin-bottom:8px;">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div>
          <div style="margin-bottom:4px;">${_badgeFontes(o.fontes)}</div>
          <div style="font-weight:600;">${usdcN.toFixed(2)} USDC @ ${cotN.toFixed(2)}</div>
          <div style="font-size:11px;color:#94a3b8;">R$ ${total.toFixed(2)} • expira em ${mm}:${ss}</div>
        </div>
        <button class="btn btn-danger" onclick="cancelarOrdem('${o.hash}')"
                style="padding:6px 10px;font-size:12px;">✕</button>
      </div>
    </div>`;
  }).join("");
}

function atualizarTotal() {
  const u = Number($("venda-usdc").value);
  const c = Number($("venda-cotacao").value);
  $("total-estimado").textContent = (u > 0 && c > 0) ? "R$ " + (u * c).toFixed(2) : "— BRL";
}

// ============================================================
// Eventos
// ============================================================
document.addEventListener("DOMContentLoaded", () => {
  $("btn-conectar").addEventListener("click", conectar);
  $("btn-criar").addEventListener("click", criarOrdem);
  $("venda-usdc").addEventListener("input", atualizarTotal);
  $("venda-cotacao").addEventListener("input", atualizarTotal);

  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.dataset.tab;
      $("tab-criar").style.display  = tab === "criar"  ? "block" : "none";
      $("tab-minhas").style.display = tab === "minhas" ? "block" : "none";
      if (tab === "minhas") renderizarMinhas();
    });
  });

  init();
});

window.executarOrdem = executarOrdem;
window.cancelarOrdem = cancelarOrdem;
