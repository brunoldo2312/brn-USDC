// ============================================================
// BRN ↔ USDC — DEX P2P (Sem servidor próprio!)
// Conecta DIRETO na Polygon via RPC pública
// ============================================================

// 🔧 CONFIGURAÇÕES — Seus contratos já implantados!
const CONFIG = {
  POLYGON_RPC: "https://polygon-rpc.com",
  CHAIN_ID: 137,
  CONTRATO_FACTORY: "0x5C305aCFF5cDFAee90276c2acEA4Aa841f7062d8",
  CONTRATO_BRN: "0xdBc1c747B1D4c27113F65A4620b8fEaC74e2A210",
  CONTRATO_USDC: "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
  EXPLORER: "https://polygonscan.com"
};

// ABI do EscrowFactory — só o essencial
const ABI_FACTORY = [
  "function getAllEscrows() view returns (address[])",
  "function escrows(address) view returns (tuple(address vendedor, address comprador, uint256 valorBrn, uint256 valorUsdc, bool ativo, bool executado))",
  "function criarOrdem(uint256 valorBrn, uint256 valorUsdc) external",
  "function liquidarOrdem(address enderecoOrdem) external",
  "function cancelarOrdem(address enderecoOrdem) external"
];

// ABI padrão ERC20
const ABI_ERC20 = [
  "function balanceOf(address owner) view returns (uint256)",
  "function approve(address spender, uint256 amount) external returns (bool)",
  "function allowance(address owner, address spender) view returns (uint256)",
  "function decimals() view returns (uint8)"
];

// Estado global
let web3 = null, contratoFactory = null, carteira = null;

// ========================================================
// INICIALIZAÇÃO
// ========================================================

async function inicializar() {
  atualizarStatus("🔌 Conectando à rede Polygon...");
  
  // Verificar MetaMask
  if (!window.ethereum) {
    mostrarErro("❌ Instale a MetaMask para usar: https://metamask.io");
    return;
  }

  // Conectar Web3
  web3 = new Web3(window.ethereum);
  
  // Verificar rede
  const chainId = await web3.eth.getChainId();
  if (chainId !== CONFIG.CHAIN_ID) {
    await trocarParaRedePolygon();
  }

  // Inicializar contratos
  contratoFactory = new web3.eth.Contract(ABI_FACTORY, CONFIG.CONTRATO_FACTORY);
  
  atualizarStatus("✅ Conectado à Polygon Mainnet");
  await carregarOrdens();
}

async function trocarParaRedePolygon() {
  try {
    await window.ethereum.request({
      method: "wallet_switchEthereumChain",
      params: [{ chainId: "0x89" }] // 137 em hex
    });
  } catch (e) {
    if (e.code === 4902) {
      await window.ethereum.request({
        method: "wallet_addEthereumChain",
        params: [{
          chainId: "0x89",
          chainName: "Polygon Mainnet",
          rpcUrls: ["https://polygon-rpc.com"],
          nativeCurrency: { name: "MATIC", symbol: "MATIC", decimals: 18 },
          blockExplorerUrls: ["https://polygonscan.com"]
        }]
      });
    } else {
      throw e;
    }
  }
}

// ========================================================
// CONECTAR CARTEIRA DO USUÁRIO
// ========================================================

async function conectarCarteira() {
  if (!web3) await inicializar();
  
  try {
    const contas = await window.ethereum.request({ method: "eth_requestAccounts" });
    carteira = contas[0];
    
    document.getElementById("btn-conectar").style.display = "none";
    document.getElementById("endereco-carteira").textContent = 
      carteira.slice(0, 6) + "..." + carteira.slice(-4);
    document.getElementById("endereco-carteira").style.display = "inline-block";
    
    await atualizarSaldos();
    await carregarOrdens();
    
  } catch (e) {
    mostrarErro("Erro ao conectar: " + e.message);
  }
}

async function atualizarSaldos() {
  if (!carteira) return;
  
  const brn = new web3.eth.Contract(ABI_ERC20, CONFIG.CONTRATO_BRN);
  const usdc = new web3.eth.Contract(ABI_ERC20, CONFIG.CONTRATO_USDC);
  
  const saldoBrn = await brn.methods.balanceOf(carteira).call();
  const saldoUsdc = await usdc.methods.balanceOf(carteira).call();
  
  document.getElementById("saldo-brn").textContent = 
    (saldoBrn / 1e8).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 8 }) + " BRN";
  document.getElementById("saldo-usdc").textContent = 
    (saldoUsdc / 1e6).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 6 }) + " USDC";
}

// ========================================================
// CARREGAR ORDENS — DIRETO DA BLOCKCHAIN!
// ========================================================

async function carregarOrdens() {
  atualizarStatus("📋 Buscando ordens na blockchain...");
  
  try {
    const enderecosOrdens = await contratoFactory.methods.getAllEscrows().call();
    const tabela = document.getElementById("lista-ordens");
    tabela.innerHTML = "";
    
    if (enderecosOrdens.length === 0) {
      tabela.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:30px; color:#94a3b8;">
        Nenhuma ordem aberta no momento. Seja o primeiro a criar uma! 🚀
      </td></tr>`;
      atualizarStatus("✅ " + new Date().toLocaleString("pt-BR"));
      return;
    }

    for (const endereco of enderecosOrdens) {
      const ordem = await contratoFactory.methods.escrows(endereco).call();
      
      // Filtrar só ordens ativas e não executadas
      if (!ordem.ativo || ordem.executado) continue;
      
      const valorBrn = Number(ordem.valorBrn) / 1e8;
      const valorUsdc = Number(ordem.valorUsdc) / 1e6;
      const precoUnitario = valorUsdc / valorBrn;
      const ehVendedor = carteira && ordem.vendedor.toLowerCase() === carteira.toLowerCase();
      
      const linha = document.createElement("tr");
      linha.innerHTML = `
        <td>
          <div style="font-weight:500">${valorBrn.toFixed(2)} BRN</div>
          <div style="font-size:11px; color:#64748b">${precoUnitario.toFixed(4)} USDC/BRN</div>
        </td>
        <td>${valorUsdc.toFixed(2)} USDC</td>
        <td>
          <span style="font-size:11px; font-family:monospace; color:#34d399;">
            ${endereco.slice(0, 8)}...${endereco.slice(-6)}
          </span>
        </td>
        <td>
          <span style="font-size:11px; color:#94a3b8;">
            ${ordem.vendedor.slice(0, 6)}...
          </span>
        </td>
        <td style="text-align:right;">
          ${ehVendedor 
            ? `<button onclick="cancelarOrdem('${endereco}')" style="background:#f97316; color:white; border:none; padding:6px 12px; border-radius:4px; cursor:pointer;">❌ Cancelar</button>`
            : `<button onclick="comprarOrdem('${endereco}', ${valorUsdc})" style="background:#22c55e; color:white; border:none; padding:6px 12px; border-radius:4px; cursor:pointer; font-weight:bold;">💵 Comprar</button>`
          }
        </td>
      `;
      tabela.appendChild(linha);
    }
    
    atualizarStatus(`✅ ${enderecosOrdens.length} ordem(ns) • ${new Date().toLocaleString("pt-BR")}`);
    
  } catch (e) {
    mostrarErro("Erro ao carregar ordens: " + e.message);
    atualizarStatus("❌ Erro ao carregar");
  }
}

// ========================================================
// CRIAR ORDEM DE VENDA
// ========================================================

async function criarOrdem() {
  if (!carteira) { await conectarCarteira(); return; }
  
  const valorBrn = document.getElementById("venda-brn").value;
  const valorUsdc = document.getElementById("venda-usdc").value;
  
  if (!valorBrn || !valorUsdc || Number(valorBrn) <= 0) {
    mostrarErro("Preencha valores válidos");
    return;
  }
  
  const brn = new web3.eth.Contract(ABI_ERC20, CONFIG.CONTRATO_BRN);
  const valorBrnWei = BigInt(Math.floor(Number(valorBrn) * 1e8));
  const valorUsdcWei = BigInt(Math.floor(Number(valorUsdc) * 1e6));
  
  try {
    // 1. Aprovar BRN para o contrato
    mostrarAviso("⏳ Aprovando BRN...");
    await brn.methods.approve(CONFIG.CONTRATO_FACTORY, valorBrnWei)
      .send({ from: carteira });
    
    // 2. Criar ordem
    mostrarAviso("⏳ Criando ordem na blockchain...");
    await contratoFactory.methods.criarOrdem(valorBrnWei, valorUsdcWei)
      .send({ from: carteira });
    
    mostrarSucesso("✅ Ordem criada! Aparece em instantes.");
    document.getElementById("venda-brn").value = "";
    document.getElementById("venda-usdc").value = "";
    
    setTimeout(carregarOrdens, 2000);
    
  } catch (e) {
    mostrarErro("Erro: " + (e.message || "Transação cancelada"));
  }
}

// ========================================================
// COMPRAR ORDEM
// ========================================================

async function comprarOrdem(enderecoOrdem, valorUsdc) {
  if (!carteira) { await conectarCarteira(); return; }
  
  if (!confirm(`Confirmar compra?\nValor: ${valorUsdc.toFixed(2)} USDC`)) return;
  
  const usdc = new web3.eth.Contract(ABI_ERC20, CONFIG.CONTRATO_USDC);
  const valorUsdcWei = BigInt(Math.floor(valorUsdc * 1e6));
  
  try {
    // 1. Aprovar USDC
    mostrarAviso("⏳ Aprovando USDC...");
    await usdc.methods.approve(CONFIG.CONTRATO_FACTORY, valorUsdcWei)
      .send({ from: carteira });
    
    // 2. Liquidar ordem
    mostrarAviso("⏳ Executando troca...");
    await contratoFactory.methods.liquidarOrdem(enderecoOrdem)
      .send({ from: carteira });
    
    mostrarSucesso("✅ Troca concluída! Verifique sua carteira.");
    setTimeout(carregarOrdens, 3000);
    setTimeout(atualizarSaldos, 1000);
    
  } catch (e) {
    mostrarErro("Erro: " + (e.message || "Transação cancelada"));
  }
}

// ========================================================
// CANCELAR ORDEM
// ========================================================

async function cancelarOrdem(enderecoOrdem) {
  if (!carteira) return;
  
  if (!confirm("Cancelar esta ordem? Seu BRN será devolvido.")) return;
  
  try {
    mostrarAviso("⏳ Cancelando...");
    await contratoFactory.methods.cancelarOrdem(enderecoOrdem)
      .send({ from: carteira });
    
    mostrarSucesso("✅ Ordem cancelada. BRN devolvido.");
    setTimeout(carregarOrdens, 2000);
    setTimeout(atualizarSaldos, 1000);
    
  } catch (e) {
    mostrarErro("Erro: " + e.message);
  }
}

// ========================================================
// UTILITÁRIOS
// ========================================================

function atualizarStatus(texto) {
  document.getElementById("status").textContent = texto;
}

function mostrarErro(texto) {
  const el = document.getElementById("mensagem");
  el.innerHTML = `<div style="background:#7f1d1d; color:#fca5a5; padding:12px; border-radius:6px; margin:10px 0;">❌ ${texto}</div>`;
  setTimeout(() => el.innerHTML = "", 6000);
}

function mostrarSucesso(texto) {
  const el = document.getElementById("mensagem");
  el.innerHTML = `<div style="background:#064e3b; color:#6ee7b7; padding:12px; border-radius:6px; margin:10px 0;">✅ ${texto}</div>`;
  setTimeout(() => el.innerHTML = "", 5000);
}

function mostrarAviso(texto) {
  const el = document.getElementById("mensagem");
  el.innerHTML = `<div style="background:#78350f; color:#fcd34d; padding:12px; border-radius:6px; margin:10px 0;">⏳ ${texto}</div>`;
}

// Atualizar ordens a cada 30 segundos
setInterval(carregarOrdens, 30000);

// Expor funções globais
window.conectarCarteira = conectarCarteira;
window.criarOrdem = criarOrdem;
window.comprarOrdem = comprarOrdem;
window.cancelarOrdem = cancelarOrdem;

// Iniciar ao carregar
document.addEventListener("DOMContentLoaded", inicializar);