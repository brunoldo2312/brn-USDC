// ============================================================
// APP.JS - Carteira BRN P2P
// Compatível com EscrowFactory JÁ DEPLOYADO (sem alterar .sol)
// - Mural lê direto da blockchain (não precisa conectar carteira)
// - Estado "Consultando..." + contador de ordens ativas
// - Approve automático de BRN (Factory) e USDC (Escrow)
// - Fallback de múltiplos RPCs + timeouts + leitura paralela
// - Saldos com auto-refresh a cada 20s + fallback de RPC
// ============================================================

// --- CONFIGURACOES (POLYGON MAINNET) ---
const ESCROW_FACTORY_ADDRESS = "0x5C305aCFF5cDFAee90276c2acEA4Aa841f7062d8";
const TOKEN_BRN_ADDRESS      = "0xdBc1c747B1D4c27113F65A4620b8fEaC74e2A210";
const TOKEN_USDC_ADDRESS     = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174";

const BRN_DECIMALS   = 18;
const USDC_DECIMALS  = 6;
const POLYGON_CHAIN_ID = 137;

const SALDOS_REFRESH_MS = 20000;  // 20s

// RPCs publicos de fallback (testados em ordem ate um responder)
const RPCS_FALLBACK = [
  "https://polygon-bor-rpc.publicnode.com",
  "https://polygon.llamarpc.com",
  "https://rpc.ankr.com/polygon",
  "https://1rpc.io/matic",
  "https://polygon-rpc.com",
];

// --- ABIs (compatíveis com o contrato já deployado) ---
const FACTORY_ABI = [
  "function criarNovoContratoEscrow(address _tokenOferecido, address _tokenDesejado, uint256 _valorOferecido, uint256 _valorDesejado) returns (address)",
  "function obterContratosGerados() view returns (address[])",
];

const ESCROW_INDIVIDUAL_ABI = [
  "function executarTroca() external",
  "function cancelar() external",
  "function obterDados() view returns (address tokenOferecido, address tokenDesejado, address criador, uint256 valorOferecido, uint256 valorDesejado, bool executado, bool cancelado)",
];

const ERC20_ABI = [
  "function balanceOf(address account) view returns (uint256)",
  "function approve(address spender, uint256 amount) returns (bool)",
  "function allowance(address owner, address spender) view returns (uint256)",
  "function transfer(address recipient, uint256 amount) returns (bool)",
];

// --- ESTADO GLOBAL ---
let provider = null;
let signer = null;
let userAddress = null;
let webSocket = null;
let tentativasReconexao = 0;
const MAX_TENTATIVAS = 10;
let pingInterval = null;
let blockchainSyncInterval = null;
let saldosInterval = null;
let rpcProviderCache = null; // RPC que funcionou, para reutilizar

// ============================================================
// Helpers
// ============================================================
function setLoading(botao, carregando, textoOriginal) {
  if (!botao) return;
  botao.disabled = carregando;
  botao.innerText = carregando ? "Processando..." : textoOriginal;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function shortAddr(a) {
  if (!a || a.length < 10) return a || "?";
  return `${a.substring(0, 6)}...${a.substring(a.length - 4)}`;
}

function mostrarAviso(id, msg, tipo) {
  const el = document.getElementById(id);
  if (!el) { alert(msg); return; }
  el.textContent = msg;
  el.className = "aviso visivel" + (tipo ? " " + tipo : "");
  if (tipo === "ok") setTimeout(() => { el.className = "aviso"; }, 5000);
}

// ------------------------------------------------------------
// Resolve qual RPC usar (prefere MetaMask, cai para publico)
// ------------------------------------------------------------
async function obterRpcProvider() {
  if (provider) return provider;                 // MetaMask conectado = melhor
  if (rpcProviderCache) return rpcProviderCache; // reusa o que já funcionou

  for (const url of RPCS_FALLBACK) {
    try {
      const p = new ethers.providers.JsonRpcProvider(url);
      await Promise.race([
        p.getBlockNumber(),
        new Promise((_, rej) =>
          setTimeout(() => rej(new Error("timeout")), 4000)
        ),
      ]);
      console.log(`[bruno] RPC ativo: ${url}`);
      rpcProviderCache = p;
      return p;
    } catch (e) {
      console.warn(`[bruno] RPC falhou (${url}):`, e.message);
    }
  }
  throw new Error("Todos os RPCs falharam");
}

// ------------------------------------------------------------
// Provider "somente leitura" dedicado a saldos
//   - Tenta MetaMask primeiro
//   - Se falhar, usa o cache publico
// ------------------------------------------------------------
async function obterProviderParaSaldos() {
  if (provider) {
    try {
      // Testa rapidamente se o MetaMask responde
      await Promise.race([
        provider.getBlockNumber(),
        new Promise((_, rej) =>
          setTimeout(() => rej(new Error("metamask timeout")), 3000)
        ),
      ]);
      return provider;
    } catch (e) {
      console.warn("[bruno] MetaMask lento, usando RPC publico p/ saldos");
    }
  }
  // Reaproveita o cache ou testa os publicos
  if (rpcProviderCache) return rpcProviderCache;
  return await obterRpcProvider();
}

// ============================================================
// Conectar MetaMask
// ============================================================
async function conectarCarteira() {
  console.log("[bruno] Conectando carteira...");
  if (!window.ethereum) { alert("MetaMask nao encontrado!"); return; }

  try {
    provider = new ethers.providers.Web3Provider(window.ethereum);
    await provider.send("eth_requestAccounts", []);
    signer = provider.getSigner();
    userAddress = await signer.getAddress();

    const network = await provider.getNetwork();
    if (network.chainId !== POLYGON_CHAIN_ID) {
      const trocar = confirm("Voce nao esta na Polygon Mainnet. Trocar agora?");
      if (!trocar) return;
      try {
        await window.ethereum.request({
          method: "wallet_switchEthereumChain",
          params: [{ chainId: "0x89" }],
        });
        provider = new ethers.providers.Web3Provider(window.ethereum);
        signer = provider.getSigner();
      } catch (e) {
        console.error(e);
        alert("Nao foi possivel trocar para Polygon. Abortando.");
        return;
      }
    }

    const el = document.getElementById("walletAddress");
    if (el) {
      el.innerText = `Conectado: ${shortAddr(userAddress)}`;
      el.style.color = "#38bdf8";
    }
    const meuEnd = document.getElementById("meuEndereco");
    if (meuEnd) meuEnd.innerText = userAddress;

    gerarQRCode(userAddress);
    await carregarSaldos();
    await sincronizarMuralDiretoDaBlockchain();

    // >>> Auto-refresh dos saldos <<<
    iniciarAutoRefreshSaldos();

    if (window.ethereum.removeAllListeners) {
      window.ethereum.removeAllListeners("accountsChanged");
      window.ethereum.removeAllListeners("chainChanged");
    }
    window.ethereum.on("accountsChanged", () => window.location.reload());
    window.ethereum.on("chainChanged",    () => window.location.reload());
  } catch (error) {
    console.error("[bruno] Falha ao conectar:", error);
    alert("Falha: " + (error.message || error));
  }
}

// ============================================================
// Auto-refresh dos saldos
// ============================================================
function iniciarAutoRefreshSaldos() {
  if (saldosInterval) clearInterval(saldosInterval);
  saldosInterval = setInterval(() => {
    if (userAddress) carregarSaldos();
  }, SALDOS_REFRESH_MS);
  console.log(`[bruno] Auto-refresh de saldos ativado (${SALDOS_REFRESH_MS}ms)`);
}

// ============================================================
// Saldos (com fallback de RPC + timeout + erro visivel)
// ============================================================
async function carregarSaldos() {
  if (!userAddress) return;

  const elBRN  = document.getElementById("saldoBRN");
  const elUSDC = document.getElementById("saldoUSDT");
  const elPOL  = document.getElementById("saldoPOL");

  // Mostra "..." durante carregamento se ainda nao tem valor
  if (elBRN  && elBRN.innerText  === "--") elBRN.innerText  = "...";
  if (elUSDC && elUSDC.innerText === "--") elUSDC.innerText = "...";
  if (elPOL  && elPOL.innerText  === "--") elPOL.innerText  = "...";

  let rpc;
  try {
    rpc = await obterProviderParaSaldos();
  } catch (e) {
    console.error("[bruno] Sem RPC para saldos:", e);
    if (elBRN)  elBRN.innerText  = "erro RPC";
    if (elUSDC) elUSDC.innerText = "erro RPC";
    if (elPOL)  elPOL.innerText  = "erro RPC";
    return;
  }

  // --- BRN ---
  try {
    const brn = new ethers.Contract(TOKEN_BRN_ADDRESS, ERC20_ABI, rpc);
    const brnBal = await Promise.race([
      brn.balanceOf(userAddress),
      new Promise((_, rej) => setTimeout(() => rej(new Error("timeout BRN")), 8000)),
    ]);
    if (elBRN) {
      elBRN.innerText =
        `${parseFloat(ethers.utils.formatUnits(brnBal, BRN_DECIMALS)).toFixed(4)} BRN`;
    }
  } catch (e) {
    console.warn("[bruno] Saldo BRN falhou:", e.message);
    if (elBRN && elBRN.innerText === "...") elBRN.innerText = "erro BRN";
  }

  // --- USDC ---
  try {
    const usdc = new ethers.Contract(TOKEN_USDC_ADDRESS, ERC20_ABI, rpc);
    const usdcBal = await Promise.race([
      usdc.balanceOf(userAddress),
      new Promise((_, rej) => setTimeout(() => rej(new Error("timeout USDC")), 8000)),
    ]);
    if (elUSDC) {
      elUSDC.innerText =
        `${parseFloat(ethers.utils.formatUnits(usdcBal, USDC_DECIMALS)).toFixed(2)} USDC`;
    }
  } catch (e) {
    console.warn("[bruno] Saldo USDC falhou:", e.message);
    if (elUSDC && elUSDC.innerText === "...") elUSDC.innerText = "erro USDC";
  }

  // --- POL ---
  try {
    const polBal = await Promise.race([
      rpc.getBalance(userAddress),
      new Promise((_, rej) => setTimeout(() => rej(new Error("timeout POL")), 8000)),
    ]);
    if (elPOL) {
      elPOL.innerText =
        `${parseFloat(ethers.utils.formatEther(polBal)).toFixed(4)} POL`;
    }
  } catch (e) {
    console.warn("[bruno] Saldo POL falhou:", e.message);
    if (elPOL && elPOL.innerText === "...") elPOL.innerText = "erro POL";
  }
}

// ============================================================
// Mural — render + estado de carregando
// ============================================================
function marcarMuralCarregando() {
  const muralEl = document.getElementById("muralOrdens");
  if (!muralEl) return;
  if (muralEl.querySelector("[data-escrow]")) return;
  muralEl.innerHTML =
    '<p style="color:#94a3b8;">Consultando a blockchain...</p>';
}

function renderizarMural(ordens) {
  const muralEl = document.getElementById("muralOrdens");
  if (!muralEl) return;

  if (!ordens || ordens.length === 0) {
    muralEl.innerHTML =
      '<p style="color:#94a3b8;">Nenhuma ordem ativa no momento.</p>';
    return;
  }

  const cabecalho = `
    <p style="color:#94a3b8;font-size:0.85rem;margin-top:0;">
      ${ordens.length} ordem(ns) ativa(s) na blockchain
    </p>`;

  let html = cabecalho;
  ordens.forEach((o) => {
    const addr    = escapeHtml(o.contratoAddress);
    const criador = escapeHtml(shortAddr(o.criador));
    const valorOf = escapeHtml(o.valorOferecido);
    const valorDe = escapeHtml(o.valorDesejado);
    const ehMeu   = userAddress &&
                    o.criador.toLowerCase() === userAddress.toLowerCase();

    html += `
      <div data-escrow="${addr}"
           style="background:#202024;border:1px solid #29292e;padding:15px;margin-bottom:10px;border-radius:6px;text-align:left;">
        <p style="margin:5px 0;"><b>Contrato:</b>
           <span style="font-size:11px;color:#38bdf8;">${addr}</span></p>
        <p style="margin:5px 0;"><b>Criador:</b>
           <span style="font-size:12px;color:#94a3b8;">${criador}${ehMeu ? ' (você)' : ''}</span></p>
        <p style="margin:5px 0;">Oferece:
           <b style="color:#04d361;">${valorOf} BRN</b>
           ➔ Quer:
           <b style="color:#38bdf8;">${valorDe} USDC</b></p>
        <button onclick="executarTrocaNoContrato('${addr}')"
          style="background:#04d361;color:#000;padding:6px 12px;border:none;border-radius:4px;font-weight:bold;cursor:pointer;margin-top:5px;">
          Liquidar Troca
        </button>
        ${ehMeu ? `<button onclick="cancelarOrdem('${addr}')"
          style="background:#b91c1c;color:#fff;padding:6px 12px;border:none;border-radius:4px;font-weight:bold;cursor:pointer;margin-top:5px;margin-left:6px;">
          Cancelar
        </button>` : ''}
      </div>`;
  });
  muralEl.innerHTML = html;
}

// ============================================================
// Sincronização com a blockchain (com fallback de RPC)
// ============================================================
async function sincronizarMuralDiretoDaBlockchain() {
  marcarMuralCarregando();

  let rpcProvider;
  try {
    rpcProvider = await obterRpcProvider();
  } catch (e) {
    console.error("[bruno] Sem RPC disponivel:", e);
    rpcProviderCache = null;
    return;
  }

  try {
    const factory = new ethers.Contract(
      ESCROW_FACTORY_ADDRESS, FACTORY_ABI, rpcProvider
    );

    const todos = await Promise.race([
      factory.obterContratosGerados(),
      new Promise((_, rej) =>
        setTimeout(() => rej(new Error("timeout obterContratosGerados")), 12000)
      ),
    ]);

    const ultimos = todos.slice(-100);
    const resultados = await Promise.all(
      ultimos.map(async (endereco) => {
        try {
          const escrow = new ethers.Contract(
            endereco, ESCROW_INDIVIDUAL_ABI, rpcProvider
          );
          const d = await Promise.race([
            escrow.obterDados(),
            new Promise((_, rej) =>
              setTimeout(() => rej(new Error("timeout obterDados")), 8000)
            ),
          ]);
          if (d.executado || d.cancelado) return null;
          return {
            contratoAddress: endereco,
            criador: d.criador,
            valorOferecido: ethers.utils.formatUnits(d.valorOferecido, BRN_DECIMALS),
            valorDesejado:  ethers.utils.formatUnits(d.valorDesejado,  USDC_DECIMALS),
          };
        } catch (e) {
          console.warn("[bruno] escrow ignorado", endereco, e.message);
          return null;
        }
      })
    );

    const ordensAtivas = resultados.filter(Boolean);
    renderizarMural(ordensAtivas);
  } catch (error) {
    console.error("[bruno] Falha ao ler mural:", error);
    const muralEl = document.getElementById("muralOrdens");
    if (muralEl && !muralEl.querySelector("[data-escrow]")) {
      muralEl.innerHTML =
        '<p style="color:#f87171;">Nao foi possivel ler a blockchain agora. ' +
        'Nova tentativa em 30s...</p>';
    }
    rpcProviderCache = null;
  }
}

// ============================================================
// Criar ordem (com approve do BRN para a Factory)
// ============================================================
async function gerarContratoAutomatico(botao) {
  if (!signer) { alert("Conecte a carteira primeiro."); return; }

  const vOf = parseFloat(document.getElementById("valorOferecidoInput").value);
  const vDe = parseFloat(document.getElementById("valorDesejadoInput").value);
  if (!vOf || vOf <= 0 || !vDe || vDe <= 0) {
    alert("Preencha valores positivos.");
    return;
  }

  setLoading(botao, true, "Criar Ordem On-Chain");
  try {
    const vOfWei = ethers.utils.parseUnits(vOf.toString(), BRN_DECIMALS);
    const vDeWei = ethers.utils.parseUnits(vDe.toString(), USDC_DECIMALS);

    const brn = new ethers.Contract(TOKEN_BRN_ADDRESS, ERC20_ABI, signer);
    const allow = await brn.allowance(userAddress, ESCROW_FACTORY_ADDRESS);
    if (allow.lt(vOfWei)) {
      console.log("[bruno] Aprovando BRN para a Factory...");
      const txA = await brn.approve(ESCROW_FACTORY_ADDRESS, vOfWei);
      await txA.wait();
    }

    const factory = new ethers.Contract(ESCROW_FACTORY_ADDRESS, FACTORY_ABI, signer);
    const tx = await factory.criarNovoContratoEscrow(
      TOKEN_BRN_ADDRESS, TOKEN_USDC_ADDRESS, vOfWei, vDeWei
    );
    await tx.wait();

    alert("Ordem criada com sucesso!");
    await carregarSaldos();
    await sincronizarMuralDiretoDaBlockchain();
  } catch (err) {
    console.error(err);
    alert("Erro: " + (err.reason || err.message || err));
  } finally {
    setLoading(botao, false, "Criar Ordem On-Chain");
  }
}

// ============================================================
// Executar troca (com approve do USDC para o escrow)
// ============================================================
async function executarTrocaNoContrato(enderecoEscrow) {
  if (!signer) { alert("Conecte a carteira primeiro."); return; }

  try {
    const escrowView = new ethers.Contract(
      enderecoEscrow, ESCROW_INDIVIDUAL_ABI, provider
    );
    const d = await escrowView.obterDados();

    const usdc = new ethers.Contract(TOKEN_USDC_ADDRESS, ERC20_ABI, signer);
    const allow = await usdc.allowance(userAddress, enderecoEscrow);
    if (allow.lt(d.valorDesejado)) {
      console.log("[bruno] Aprovando USDC para o escrow...");
      const txA = await usdc.approve(enderecoEscrow, d.valorDesejado);
      await txA.wait();
    }

    const escrow = new ethers.Contract(enderecoEscrow, ESCROW_INDIVIDUAL_ABI, signer);
    const tx = await escrow.executarTroca();
    await tx.wait();

    alert("Troca concluída!");
    await carregarSaldos();
    await sincronizarMuralDiretoDaBlockchain();
  } catch (err) {
    console.error(err);
    alert("Erro: " + (err.reason || err.message || err));
  }
}

// ============================================================
// Cancelar ordem
// ============================================================
async function cancelarOrdem(enderecoEscrow) {
  if (!signer) { alert("Conecte a carteira primeiro."); return; }
  if (!confirm("Cancelar essa ordem? Seus BRN voltarão para você.")) return;

  try {
    const escrow = new ethers.Contract(enderecoEscrow, ESCROW_INDIVIDUAL_ABI, signer);
    const tx = await escrow.cancelar();
    await tx.wait();
    alert("Ordem cancelada.");
    await carregarSaldos();
    await sincronizarMuralDiretoDaBlockchain();
  } catch (err) {
    console.error(err);
    alert("Erro: " + (err.reason || err.message || err));
  }
}

// ============================================================
// Transferência simples de BRN
// ============================================================
async function iniciarTransferencia() {
  if (!signer) { alert("Conecte a carteira primeiro."); return; }

  const destino = document.getElementById("destinoInput").value.trim();
  const valor = parseFloat(document.getElementById("valorEnvioInput").value);

  if (!ethers.utils.isAddress(destino)) {
    mostrarAviso("avisoTransferencia", "Endereco de destino invalido.", "erro");
    return;
  }
  if (!valor || valor <= 0) {
    mostrarAviso("avisoTransferencia", "Quantidade invalida.", "erro");
    return;
  }
  if (destino.toLowerCase() === userAddress.toLowerCase()) {
    mostrarAviso("avisoTransferencia", "Destino igual a sua carteira.", "erro");
    return;
  }

  try {
    const vWei = ethers.utils.parseUnits(valor.toString(), BRN_DECIMALS);
    const brn = new ethers.Contract(TOKEN_BRN_ADDRESS, ERC20_ABI, signer);
    const tx = await brn.transfer(destino, vWei);
    mostrarAviso("avisoTransferencia", "Enviando...", "");
    await tx.wait();
    mostrarAviso("avisoTransferencia",
                 `Enviado! TX: ${tx.hash.substring(0, 20)}...`, "ok");
    await carregarSaldos();
  } catch (err) {
    console.error(err);
    mostrarAviso("avisoTransferencia",
                 "Erro: " + (err.reason || err.message), "erro");
  }
}

// ============================================================
// Utilitários
// ============================================================
async function copiarEndereco() {
  if (!userAddress) { alert("Conecte a carteira primeiro."); return; }
  try {
    await navigator.clipboard.writeText(userAddress);
    alert("Endereco copiado!");
  } catch {
    prompt("Copie manualmente:", userAddress);
  }
}

async function compartilharEndereco() {
  if (!userAddress) { alert("Conecte a carteira primeiro."); return; }
  if (navigator.share) {
    try { await navigator.share({ title: "Meu endereco BRN", text: userAddress }); }
    catch (_) {}
  } else {
    copiarEndereco();
  }
}

function gerarQRCode(texto) {
  const el = document.getElementById("qrcode");
  if (!el || typeof QRCode === "undefined") return;
  el.innerHTML = "";
  new QRCode(el, { text: texto, width: 180, height: 180 });
}

// ============================================================
// WebSocket
// ============================================================
function atualizarIndicadorStatus(online) {
  const el = document.getElementById("statusConexao");
  if (!el) return;
  el.innerHTML = online
    ? 'Sincronizador P2P: <span style="color:#04d361;font-weight:bold;">ONLINE</span>'
    : 'Sincronizador P2P: <span style="color:#f87171;">OFFLINE</span>';
}

function iniciarConexaoWebSocket() {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${proto}//${window.location.host}/ws`;

  try { webSocket = new WebSocket(url); }
  catch (e) { console.error("[bruno] WS create fail:", e); return; }

  webSocket.onopen = () => {
    console.log("[bruno] WS conectado");
    tentativasReconexao = 0;
    atualizarIndicadorStatus(true);
    sincronizarMuralDiretoDaBlockchain();

    if (pingInterval) clearInterval(pingInterval);
    pingInterval = setInterval(() => {
      if (webSocket.readyState === WebSocket.OPEN) {
        webSocket.send(JSON.stringify({ tipo: "ping" }));
      }
    }, 25000);
  };

  webSocket.onmessage = (ev) => {
    let dados;
    try { dados = JSON.parse(ev.data); } catch { return; }

    switch (dados.tipo) {
      case "snapshot":
      case "nova_ordem":
      case "ordem_cancelada":
      case "ordem_executada":
      case "ordem_expirada":
        sincronizarMuralDiretoDaBlockchain();
        break;
      case "erro":
        console.warn("[bruno] erro servidor:", dados.msg);
        break;
      default:
        break;
    }
  };

  webSocket.onerror = (e) => console.warn("[bruno] WS erro:", e);

  webSocket.onclose = () => {
    atualizarIndicadorStatus(false);
    if (tentativasReconexao < MAX_TENTATIVAS) {
      tentativasReconexao++;
      const delay = Math.min(30000, 2000 * tentativasReconexao);
      setTimeout(iniciarConexaoWebSocket, delay);
    }
  };
}

// ============================================================
// Bootstrap
// ============================================================
window.addEventListener("DOMContentLoaded", () => {
  iniciarConexaoWebSocket();
  sincronizarMuralDiretoDaBlockchain();
  blockchainSyncInterval = setInterval(sincronizarMuralDiretoDaBlockchain, 30000);
});