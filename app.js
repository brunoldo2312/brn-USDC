// ============================================================
// APP.JS - Carteira BRN P2P (Versao Completa)
// ============================================================

// --- CONFIGURACOES (POLYGON MAINNET) ---
const ESCROW_FACTORY_ADDRESS = "0x5C305aCFF5cDFAee90276c2acEA4Aa841f7062d8";
const TOKEN_BRN_ADDRESS      = "0xdBc1c747B1D4c27113F65A4620b8fEaC74e2A210";
const TOKEN_USDT_ADDRESS     = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"; // USDC

// --- ABIs ---
const FACTORY_ABI = [
  "function criarNovoContratoEscrow(address _tokenOferecido, address _tokenDesejado, uint256 _valorOferecido, uint256 _valorDesejado) returns (address)",
  "function obterContratosGerados() view returns (address[])",
  "event ContratoCriado(address indexed enderecoContrato, address indexed criador, address tokenOferecido, address tokenDesejado, uint256 valorOferecido, uint256 valorDesejado)"
];

const ESCROW_INDIVIDUAL_ABI = [
  "function executarTroca() external",
  "function cancelar() external",
  "function obterDados() view returns (address, address, address, uint256, uint256, bool, bool)"
];

const ERC20_ABI = [
  "function name() view returns (string)",
  "function symbol() view returns (string)",
  "function decimals() view returns (uint8)",
  "function totalSupply() view returns (uint256)",
  "function balanceOf(address account) view returns (uint256)",
  "function approve(address spender, uint256 amount) returns (bool)",
  "function allowance(address owner, address spender) view returns (uint256)",
  "function transfer(address to, uint256 amount) returns (bool)",
  "event Transfer(address indexed from, address indexed to, uint256 value)"
];

// --- ESTADO GLOBAL ---
let provider = null;
let signer = null;
let userAddress = null;
let webSocket = null;
let tentativasReconexao = 0;
const MAX_TENTATIVAS = 10;
let pingInterval = null;

// ============================================================
// CONECTAR CARTEIRA
// ============================================================
async function conectarCarteira() {
  console.log("[bruno] Tentando conectar carteira...");
  if (!window.ethereum) { alert("MetaMask nao encontrado!"); return; }
  try {
    provider = new ethers.providers.Web3Provider(window.ethereum);
    await provider.send("eth_requestAccounts", []);
    signer = provider.getSigner();
    userAddress = await signer.getAddress();
    const network = await provider.getNetwork();
    if (network.chainId !== 137) alert("AVISO: Mude para Polygon Mainnet!");
    const el = document.getElementById("walletAddress");
    if (el) { el.innerText = `Conectado: ${userAddress.substring(0,6)}...${userAddress.substring(38)}`; el.style.color = "#38bdf8"; }
    const meuEnd = document.getElementById("meuEndereco");
    if (meuEnd) meuEnd.innerText = userAddress;
    gerarQRCode(userAddress);
    await carregarSaldos();
  } catch (error) { console.error(error); alert("Erro ao conectar."); }
}

// ============================================================
// CARREGAR SALDOS
// ============================================================
async function carregarSaldos() {
  if (!provider || !userAddress) return;
  try {
    const brn = new ethers.Contract(TOKEN_BRN_ADDRESS, ERC20_ABI, provider);
    const brnBalance = await brn.balanceOf(userAddress);
    const elBRN = document.getElementById("saldoBRN");
    if (elBRN) elBRN.innerText = `${parseFloat(ethers.utils.formatUnits(brnBalance, 18)).toFixed(4)} BRN`;

    const usdc = new ethers.Contract(TOKEN_USDT_ADDRESS, ERC20_ABI, provider);
    const usdcBalance = await usdc.balanceOf(userAddress);
    const elUSDT = document.getElementById("saldoUSDT");
    if (elUSDT) elUSDT.innerText = `${parseFloat(ethers.utils.formatUnits(usdcBalance, 6)).toFixed(2)} USDC`;

    const polBalance = await provider.getBalance(userAddress);
    const elPOL = document.getElementById("saldoPOL");
    if (elPOL) elPOL.innerText = `${parseFloat(ethers.utils.formatEther(polBalance)).toFixed(4)} POL`;
  } catch (err) { console.error(err); }
}

// ============================================================
// QR CODE
// ============================================================
function gerarQRCode(endereco) {
  const container = document.getElementById("qrcode");
  if (!container || typeof QRCode === "undefined") return;
  container.innerHTML = "";
  QRCode.toDataURL(endereco, { width: 180, margin: 1 }, (err, url) => {
    if (err) return;
    const img = document.createElement("img");
    img.src = url;
    container.appendChild(img);
  });
}

// ============================================================
// COPIAR / COMPARTILHAR
// ============================================================
function copiarEndereco() {
  if (!userAddress) { alert("Conecte a carteira primeiro!"); return; }
  navigator.clipboard.writeText(userAddress).then(() => alert("Endereco copiado!"))
    .catch(() => { const el = document.createElement("textarea"); el.value = userAddress;
      document.body.appendChild(el); el.select(); document.execCommand("copy");
      document.body.removeChild(el); alert("Endereco copiado!"); });
}

async function compartilharEndereco() {
  if (!userAddress) { alert("Conecte a carteira primeiro!"); return; }
  const texto = `Meu endereco BRN na Polygon: ${userAddress}`;
  if (navigator.share) { try { await navigator.share({ title: "Receber BRN", text: texto }); } catch(e){} }
  else copiarEndereco();
}

// ============================================================
// TRANSFERENCIA SEGURA
// ============================================================
function mostrarAviso(texto, tipo) {
  const el = document.getElementById("avisoTransferencia");
  if (!el) return;
  el.className = "aviso visivel " + (tipo || "");
  el.innerText = texto;
}
function esconderAviso() {
  const el = document.getElementById("avisoTransferencia");
  if (el) el.className = "aviso";
}

async function iniciarTransferencia() {
  esconderAviso();
  if (!signer) { alert("Conecte a carteira primeiro!"); return; }
  const destino = (document.getElementById("destinoInput").value || "").trim();
  const valorStr = (document.getElementById("valorEnvioInput").value || "").trim();
  if (!destino || !valorStr) { mostrarAviso("Preencha o endereco e a quantidade.", "erro"); return; }

  if (!ethers.utils.isAddress(destino)) { mostrarAviso("Endereco invalido.", "erro"); return; }
  let enderecoChecksum;
  try { enderecoChecksum = ethers.utils.getAddress(destino); }
  catch (err) { mostrarAviso("Checksum do endereco falhou.", "erro"); return; }

  if (enderecoChecksum.toLowerCase() === userAddress.toLowerCase()) {
    mostrarAviso("Voce nao pode enviar para o proprio endereco.", "erro"); return; }

  const codeAtDestino = await provider.getCode(enderecoChecksum);
  if (codeAtDestino !== "0x") {
    if (!confirm("ATENCAO: O destino e um CONTRATO. Continuar?")) {
      mostrarAviso("Envio cancelado.", "erro"); return; }
  }

  let valorWei;
  try { valorWei = ethers.utils.parseUnits(valorStr, 18); }
  catch (err) { mostrarAviso("Valor invalido.", "erro"); return; }
  if (valorWei.lte(0)) { mostrarAviso("Valor deve ser maior que zero.", "erro"); return; }

  const contratoBRN = new ethers.Contract(TOKEN_BRN_ADDRESS, ERC20_ABI, signer);
  const saldoBRN = await contratoBRN.balanceOf(userAddress);
  if (saldoBRN.lt(valorWei)) {
    mostrarAviso(`Saldo insuficiente. Voce tem ${ethers.utils.formatUnits(saldoBRN, 18)} BRN.`, "erro"); return; }

  const saldoPOL = await provider.getBalance(userAddress);
  const gasPrice = await provider.getGasPrice();
  const custoGasEstimado = gasPrice.mul(100000);
  if (saldoPOL.lt(custoGasEstimado)) {
    mostrarAviso(`POL insuficiente para gas.`, "erro"); return; }

  const valorFormatado = ethers.utils.formatUnits(valorWei, 18);
  const textoUsuario = prompt(
    "CONFIRMACAO DE TRANSFERENCIA\n\nDestino: " + enderecoChecksum +
    "\n\nQuantidade: " + valorFormatado + " BRN\n\nDigite CONFIRMAR:"
  );
  if (textoUsuario !== "CONFIRMAR") { mostrarAviso("Cancelado.", "erro"); return; }

  try {
    await contratoBRN.callStatic.transfer(enderecoChecksum, valorWei);
  } catch (err) { mostrarAviso("Simulacao falhou.", "erro"); return; }

  try {
    mostrarAviso("Aguardando MetaMask...", "");
    const tx = await contratoBRN.transfer(enderecoChecksum, valorWei);
    mostrarAviso("Transacao enviada. Aguardando...", "");
    const receipt = await tx.wait();
    if (receipt.status !== 1) { mostrarAviso("Falhou na blockchain.", "erro"); return; }
    mostrarAviso(`Transferencia confirmada! ${valorFormatado} BRN enviados.`, "ok");
    document.getElementById("destinoInput").value = "";
    document.getElementById("valorEnvioInput").value = "";
    await carregarSaldos();
    alert(`Transferencia concluida!\nHash: ${receipt.transactionHash}`);
  } catch (err) {
    if (err.code === 4001) mostrarAviso("Voce cancelou na MetaMask.", "erro");
    else mostrarAviso("Erro: " + (err.message || "desconhecido"), "erro");
  }
}

// ============================================================
// CRIAR ORDEM P2P
// ============================================================
async function gerarContratoAutomatico() {
  if (!signer) { alert("Conecte a carteira primeiro!"); return; }
  const inputValorOferecido = document.getElementById("valorOferecidoInput").value;
  const inputValorDesejado  = document.getElementById("valorDesejadoInput").value;
  if (!inputValorOferecido || !inputValorDesejado) { alert("Preencha os dois valores!"); return; }

  try {
    const valorOferecidoWei = ethers.utils.parseUnits(inputValorOferecido, 18); // BRN
    const valorDesejadoWei  = ethers.utils.parseUnits(inputValorDesejado, 6);   // USDC

    console.log("[bruno] Approve BRN...");
    const contratoBRN = new ethers.Contract(TOKEN_BRN_ADDRESS, ERC20_ABI, signer);
    const txApprove = await contratoBRN.approve(ESCROW_FACTORY_ADDRESS, valorOferecidoWei);
    await txApprove.wait();

    console.log("[bruno] Criando escrow...");
    const factory = new ethers.Contract(ESCROW_FACTORY_ADDRESS, FACTORY_ABI, signer);
    const tx = await factory.criarNovoContratoEscrow(
      TOKEN_BRN_ADDRESS, TOKEN_USDT_ADDRESS, valorOferecidoWei, valorDesejadoWei
    );
    const receipt = await tx.wait();

    let enderecoNovo = null;
    for (const log of receipt.logs) {
      try {
        const parsed = factory.interface.parseLog(log);
        if (parsed.name === "ContratoCriado") { enderecoNovo = parsed.args.enderecoContrato; break; }
      } catch (e) {}
    }

    enviarOrdemParaServidor(enderecoNovo, {
      tokenOferecido: TOKEN_BRN_ADDRESS, tokenDesejado: TOKEN_USDT_ADDRESS,
      valorOferecido: inputValorOferecido, valorDesejado: inputValorDesejado
    });
    await carregarSaldos();
    alert(`Ordem criada!\nContrato: ${enderecoNovo}`);
  } catch (error) { console.error(error); alert("Falha ao criar ordem."); }
}

// ============================================================
// EXECUTAR TROCA (COMPRADOR)
// ============================================================
async function executarTrocaNoContrato(enderecoEscrow) {
  if (!signer) { alert("Conecte a carteira primeiro!"); return; }
  try {
    const escrowRead = new ethers.Contract(enderecoEscrow, ESCROW_INDIVIDUAL_ABI, provider);
    const dados = await escrowRead.obterDados();
    const valorDesejado = dados[4];

    console.log("[bruno] Approve USDC...");
    const contratoUSDC = new ethers.Contract(TOKEN_USDT_ADDRESS, ERC20_ABI, signer);
    const txApprove = await contratoUSDC.approve(enderecoEscrow, valorDesejado);
    await txApprove.wait();

    console.log("[bruno] Executando troca...");
    const escrow = new ethers.Contract(enderecoEscrow, ESCROW_INDIVIDUAL_ABI, signer);
    const tx = await escrow.executarTroca();
    await tx.wait();

    alert("Troca efetuada com sucesso!");
    await carregarSaldos();
  } catch (error) { console.error(error); alert("Falha na troca."); }
}

// ============================================================
// WEBSOCKET
// ============================================================
function iniciarConexaoWebSocket() {
  try { webSocket = new WebSocket("ws://localhost:8080/ws"); }
  catch (err) { atualizarStatusConexao("ERRO", "#f87171"); return; }

  webSocket.onopen = () => {
    tentativasReconexao = 0;
    atualizarStatusConexao("ONLINE", "#4ade80");
    webSocket.send(JSON.stringify({ tipo: "ping" }));
    if (pingInterval) clearInterval(pingInterval);
    pingInterval = setInterval(() => {
      if (webSocket && webSocket.readyState === WebSocket.OPEN) {
        webSocket.send(JSON.stringify({ tipo: "ping" }));
      }
    }, 25000);
  };

  webSocket.onmessage = (event) => {
    try {
      const resposta = JSON.parse(event.data);
      if (resposta.tipo === "snapshot") renderizarMuralDeOrdens(resposta.ordens || []);
      else if (resposta.tipo === "nova_ordem") webSocket.send(JSON.stringify({ tipo: "ping" }));
      else if (resposta.tipo === "ordem_cancelada" || resposta.tipo === "ordem_executada") {
        // recarrega via snapshot no próximo ciclo
      }
    } catch (err) { console.error(err); }
  };

  webSocket.onclose = () => {
    atualizarStatusConexao("OFFLINE", "#f87171");
    if (pingInterval) { clearInterval(pingInterval); pingInterval = null; }
    if (tentativasReconexao < MAX_TENTATIVAS) {
      tentativasReconexao++;
      const delay = Math.min(3000 * tentativasReconexao, 15000);
      atualizarStatusConexao(`RECONECTANDO (${tentativasReconexao}/${MAX_TENTATIVAS})`, "#fbbf24");
      setTimeout(iniciarConexaoWebSocket, delay);
    }
  };
  webSocket.onerror = () => atualizarStatusConexao("ERRO", "#f87171");
}

function atualizarStatusConexao(texto, cor) {
  const el = document.getElementById("statusConexao");
  if (el) { el.innerText = `Sincronizador P2P: ${texto}`; el.style.color = cor; }
}

function enviarOrdemParaServidor(enderecoEscrow, dadosOrdem) {
  if (!webSocket || webSocket.readyState !== WebSocket.OPEN) return false;
  webSocket.send(JSON.stringify({
    tipo: "publicar_ordem",
    ordem: {
      hash: enderecoEscrow,
      contratoAddress: enderecoEscrow,
      criador: userAddress,
      tokenOferecido: dadosOrdem.tokenOferecido,
      tokenDesejado: dadosOrdem.tokenDesejado,
      valorOferecido: dadosOrdem.valorOferecido,
      valorDesejado: dadosOrdem.valorDesejado,
      expiracao: Math.floor(Date.now() / 1000) + 86400,
      timestamp: Date.now()
    }
  }));
  return true;
}

function renderizarMuralDeOrdens(ordens) {
  const mural = document.getElementById("muralOrdens");
  if (!mural) return;
  if (!ordens || ordens.length === 0) {
    mural.innerHTML = '<p style="color:#94a3b8;">Nenhuma ordem ativa no momento.</p>';
    return;
  }
  mural.innerHTML = "";
  ordens.forEach((item) => {
    const div = document.createElement("div");
    div.style.cssText = "background:#0f172a; padding:15px; border-radius:8px; margin-bottom:10px; border-left:4px solid #38bdf8;";
    div.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <div>
          <strong style="color:#f8fafc;">Ordem: ${item.contratoAddress ? item.contratoAddress.substring(0,10) : "?"}...</strong><br>
          <span style="color:#94a3b8; font-size:0.9rem;">
            Vende: ${item.valorOferecido || "?"} BRN | Pede: ${item.valorDesejado || "?"} USDC
          </span>
        </div>
        <button onclick="executarTrocaNoContrato('${item.contratoAddress}')">Comprar</button>
      </div>`;
    mural.appendChild(div);
  });
}

// ============================================================
// INICIALIZACAO
// ============================================================
window.onload = () => { iniciarConexaoWebSocket(); };