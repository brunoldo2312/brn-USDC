# BRN-P2P — Manual do Projeto

## Visão geral
Servidor assíncrono (aiohttp) que serve um frontend estático e expõe
uma API REST + WebSocket para um mercado P2P "off-chain" (ordens ficam
em memória, sem blockchain). O túnel público é feito via ngrok.

## Estrutura
# BRN P2P v2.0 — Mural Híbrido

P2P de USDC ↔ BRL com **dois murais rodando em paralelo**:

- **Off-chain** — instantâneo, grátis, persistido em SQLite.
- **On-chain** — ancorado na Polygon via evento, imune a qualquer queda do servidor.

## 🚀 Setup em 6 passos

### 1. Deploy do contrato
- Abra https://remix.ethereum.org
- Cole `contracts/EscrowP2POffChain.sol`
- Compiler: **0.8.20+**, EVM **paris**
- Deploy na Polygon com:
  - `_usdcToken`: `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174`
  - `_admin`: seu endereço
- Copie o endereço do contrato

### 2. Configurar variáveis
```bash
export CONTRACT_ADDRESS=0xSeuContratoAqui
export BLOCO_INICIAL=<bloco do deploy>      # opcional, acelera indexação
export POLYGON_RPC=https://polygon-rpc.com  # opcional
```

Ou edite `CONFIG.CONTRACT_ADDRESS` no topo de `app.js`.

### 3. Token ngrok
```bash
echo "SEU_TOKEN_NGROK" > ngrok_token.txt
```

### 4. Instalar
```bash
pip install -r requirements.txt
```

### 5. Rodar
```bash
python server.py
```

### 6. Abrir
- Local: http://localhost:8080
- Público: veja `/health` para pegar a URL do ngrok

## 📊 Como os dois murais convivem

| Ação | Off-chain | On-chain |
|------|-----------|----------|
| Publicar | Grátis, instantâneo | Paga gas (~$0.005) |
| Sobrevive a restart | ✅ (SQLite) | ✅ (blockchain) |
| Cancelar | Grátis via WS | Requer tx on-chain |
| Executar | — | Sempre on-chain |
| Visível offline | Não | Sim (via RPC) |

Uma ordem pode estar nos dois murais ao mesmo tempo. A UI mostra badge **OC+ON** nesse caso.

## 🔍 Endpoints

| Rota | Descrição |
|------|-----------|
| `GET /` | UI |
| `GET /api/mural` | JSON dos dois murais mesclados |
| `GET /health` | Status + último bloco indexado + URL ngrok |
| `WS /ws` | Mural em tempo real |

## 📡 Protocolo WebSocket

**Cliente → Servidor:**
- `publicar_ordem` `{ordem}`
- `cancelar_ordem` `{hash}`
- `ordem_executada` `{hash, txHash}`
- `pedir_snapshot` `{}`
- `ping` `{}`

**Servidor → Cliente:**
- `snapshot` `{ordens: []}`
- `nova_ordem` `{ordem}` (com `fontes: ["off-chain"]` ou `["on-chain"]`)
- `ordem_cancelada` `{hash}`
- `ordem_executada` `{hash, txHash}`
- `ordem_expirada` `{hash}`
- `erro` `{msg}`

## 🛡️ Produção — checklist

- [x] EIP-2 (malleability check) no `_recover`
- [x] Effects antes de interações (reentrancy-safe)
- [x] Persistência SQLite (mural off-chain sobrevive restart)
- [x] Indexador on-chain com checkpoint em SQLite
- [x] Rate limit por IP
- [x] Validação de campos obrigatórios
- [x] Allowance infinita (evita approve a cada ordem)
- [x] Auto-reconexão WS
- [x] Auto-reconexão RPC
- [x] Tratamento de `user rejected` (4001)
- [ ] Auditoria externa do contrato (recomendada antes de mainnet)
- [ ] HTTPS obrigatório em produção (ngrok já fornece)
- [ ] Backup periódico do `mural.db`

## 🔧 Manutenção

**Reindexar do zero:**
```sql
DELETE FROM estado WHERE chave='ultimo_bloco';
```

**Ver ordens persistidas:**
```bash
sqlite3 mural.db "SELECT hash, criador, expiracao FROM ordens_offchain;"
```

**Forçar reindexação de um bloco específico:**
```bash
export BLOCO_INICIAL=65000000
rm mural.db   # apaga estado
python server.py
```
📘 MANUAL DO PROJETO — CARTEIRA BRN P2P
Versão: 1.0
Rede: Polygon Mainnet (Chain ID 137)
Última atualização: 2026

📑 ÍNDICE
O que é o projeto

Arquitetura

Requisitos do sistema

Estrutura de arquivos

Instalação

Configuração

Como iniciar o programa

Manual de uso — usuário final

Manual técnico — manutenção

Solução de problemas

Segurança

Contratos inteligentes

Perguntas frequentes

1. O que é o projeto
Carteira BRN P2P é um sistema descentralizado de troca peer-to-peer entre dois tokens na rede Polygon:

BRN — token interno do projeto (ERC-20, 18 decimais)

USDC — stablecoin da Circle (ERC-20, 6 decimais)

O sistema permite que dois usuários troquem BRN por USDC sem intermediário, usando um contrato inteligente de escrow (custódia):

O vendedor deposita BRN no contrato.

O comprador paga USDC ao contrato.

O contrato entrega BRN ao comprador.

Se ninguém comprar, o vendedor cancela e recebe o BRN de volta.

Ninguém pode roubar os fundos: o contrato é imutável e só executa a troca se ambas as partes tiverem os tokens disponíveis.

2. Arquitetura
text
┌─────────────────────────────────────────────────────────┐
│                    NAVEGADOR (Chrome)                    │
│  ┌───────────────────────────────────────────────────┐  │
│  │  index.html  +  app.js                            │  │
│  │  - Interface visual                                │  │
│  │  - MetaMask (assinatura de transações)             │  │
│  │  - WebSocket (sincronização P2P)                   │  │
│  └───────────────────────────────────────────────────┘  │
└──────────────┬─────────────────────┬────────────────────┘
               │                     │
               │ HTTP/WS             │ JSON-RPC
               │                     │
               ▼                     ▼
┌──────────────────────────┐  ┌────────────────────────┐
│   SERVIDOR LOCAL         │  │   POLYGON MAINNET      │
│   (server.py)            │  │                        │
│   - Serve HTML/JS        │  │   - EscrowFactory      │
│   - WebSocket /ws        │  │   - EscrowIndividual   │
│   - Túnel Ngrok          │  │   - BRN (ERC-20)       │
└──────────────────────────┘  │   - USDC (ERC-20)      │
               │              └────────────────────────┘
               │
               ▼
        ┌─────────────┐
        │   NGROK     │
        │  (URL pub.) │
        └─────────────┘
Fluxo resumido:

O COMEÇAR.bat roda o server.py.

O server.py sobe um servidor HTTP na porta 8080 e abre um túnel Ngrok.

O Chrome é aberto automaticamente na URL pública do Ngrok.

O app.js conecta na MetaMask, no WebSocket e lê os contratos direto da Polygon.

3. Requisitos do sistema
Mínimos
Item	Requisito
SO	Windows 10 / 11
Python	3.10 ou superior
Navegador	Chrome, Edge ou Brave
MetaMask	Extensão instalada no navegador
Internet	Conexão ativa (para Polygon + Ngrok)
Conta Ngrok	Gratuita (para o túnel)
Recomendados
4 GB de RAM

Conexão estável de 5 Mbps+

Carteira com pelo menos 0,5 POL para taxas de gas

4. Estrutura de arquivos
text
📁 carteira-brn-p2p/
├── COMEÇAR.bat            ← Script principal (dê duplo-clique aqui)
├── CONFIGURAR.BAT         ← Executado na primeira vez
├── _abrir.bat             ← Temporário (criado automaticamente)
│
├── server.py              ← Servidor HTTP + WebSocket + Ngrok
├── ngrok_tunnel.py        ← Módulo do túnel Ngrok
├── app.js                 ← Lógica Web3 do navegador
├── index.html             ← Interface visual
├── README.md              ← Documentação (era brn0001.py)
│
├── navegador.txt          ← Caminho do Chrome salvo
├── ngrok_token.txt        ← Token de autenticação Ngrok
├── ngrok_domain.txt       ← Domínio fixo Ngrok
│
└── 📁 contracts/          ← (Opcional) Código Solidity
    └── EscrowFactory.sol
5. Instalação
Passo 1 — Instalar Python
Acesse https://www.python.org/downloads/

Baixe o instalador Python 3.12+

IMPORTANTE: na primeira tela, marque:

☑️ Add Python to PATH

☑️ Install launcher for all users

Clique em Install Now

Aguarde e feche

Verifique a instalação: abra o Prompt de Comando (Win+R → cmd) e digite:

cmd
python --version
Deve aparecer algo como Python 3.12.x.

Passo 2 — Baixar o projeto
Copie toda a pasta do projeto para um local simples, por exemplo:

text
C:\carteira-brn-p2p\
⚠️ Evite Área de Trabalho, Documentos ou caminhos com acentos/espaços — o Ngrok pode falhar.

Passo 3 — Instalar MetaMask
Abra o Chrome

Vá em https://metamask.io/download/

Instale a extensão

Crie ou importe uma carteira

Configure a rede Polygon Mainnet:

Nome: Polygon Mainnet

RPC: https://polygon-rpc.com

Chain ID: 137

Símbolo: POL

Explorer: https://polygonscan.com

Passo 4 — Primeira execução
Dê duplo-clique em COMEÇAR.bat

Se for a primeira vez, ele executa CONFIGURAR.BAT

Será pedido o navegador (aperte Enter para aceitar o padrão padrao)

Aguarde — ele instala aiohttp e pyngrok sozinho (~1 min)

O Chrome abrirá automaticamente na URL do Ngrok

6. Configuração
navegador.txt
Caminho completo do executável do navegador.

Padrão (Chrome):

text
C:\Program Files\Google\Chrome\Application\chrome.exe
Se usar Edge:

text
C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe
Para usar o padrão do sistema (basta deixar vazio ou apagar o arquivo):

text
padrao
ngrok_token.txt
Seu token de autenticação do Ngrok.

Como obter:

Crie conta em https://dashboard.ngrok.com/signup

Vá em https://dashboard.ngrok.com/get-started/your-authtoken

Copie o token (algo como 3J8xHeVX46aXrOZeXnKrVVFMLTr_6tcrWjc6EaxX218rXJwJ4)

Cole dentro do arquivo ngrok_token.txt (sem espaços, sem quebras de linha)

ngrok_domain.txt
Domínio fixo reservado na sua conta Ngrok.

Como obter:

Em https://dashboard.ngrok.com/cloud-edge/domains

Clique em New Domain

Copie o domínio gerado (ex.: seventy-rigging-ploy.ngrok-free.dev)

Cole no arquivo ngrok_domain.txt

Endereços on-chain (em app.js)
Só altere se você mesmo fizer deploy dos contratos:

javascript
const ESCROW_FACTORY_ADDRESS = "0x5C305aCFF5cDFAee90276c2acEA4Aa841f7062d8";
const TOKEN_BRN_ADDRESS      = "0xdBc1c747B1D4c27113F65A4620b8fEaC74e2A210";
const TOKEN_USDC_ADDRESS     = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174";
7. Como iniciar o programa
Método normal
Dê duplo-clique em COMEÇAR.bat

Aguarde a janela preta mostrar:

text
[1/4] Verificando Python...
[2/4] Verificando aiohttp...
[3/4] Verificando pyngrok...
[4/4] Verificando arquivos...
Iniciando servidor...
Em ~10 segundos, o Chrome abre sozinho

A página Carteira BRN P2P carrega

Para parar o programa
Feche a janela preta OU

Pressione Ctrl + C dentro dela

Se o Chrome fechar mas o servidor continuar rodando, o Ngrok cai — sempre pare pelo Ctrl + C.

O que a janela do servidor mostra
text
2026-01-15 10:30:45 [INFO] Servidor iniciando em http://localhost:8080
2026-01-15 10:30:45 [INFO] [STARTUP] Tasks iniciadas
2026-01-15 10:30:46 [INFO] [NGROK] URL publica: https://seventy-rigging-ploy.ngrok-free.dev
2026-01-15 10:30:50 [INFO] [WS] Conectado: 189.45.12.7 (total=1)
Cada [WS] Conectado significa um usuário novo abrindo a página.

8. Manual de uso — usuário final
8.1. Abrir a carteira
Ao abrir o programa, a página mostra "Sincronizador P2P: ONLINE" (verde)

O mural de ordens já carrega sozinho, sem precisar conectar carteira

Para agir (criar/liquidar ordem), clique em "Conectar Carteira"

Ao clicar em Conectar Carteira:

MetaMask abre pedindo permissão → clique em Conectar

Se você estiver em outra rede, aparecerá um aviso pedindo para trocar para Polygon → clique em OK

Seu endereço aparece no topo (ex.: 0xab12...9f3c)

Os saldos de BRN, USDC e POL aparecem no painel Meus Saldos

8.2. Ver saldos
O painel Meus Saldos mostra em tempo real:

Campo	O que é
BRN	Seu saldo do token BRN
USDC	Seu saldo de stablecoin
POL (gas)	Taxa para transações na Polygon
Clique em "Atualizar Saldos" para reconsultar.

8.3. Criar uma ordem de venda (quem tem BRN)
Você tem BRN e quer USDC:

Role até "Criar Ordem de Troca P2P"

Em Quantidade oferecida (BRN): digite quanto BRN quer vender (ex.: 100)

Em Quantidade desejada (USDC): digite quanto USDC quer receber (ex.: 50)

Clique em "Criar Ordem On-Chain"

O que acontece:

1ª transação — MetaMask pede approve do BRN (autoriza a factory a usar seu token)

2ª transação — MetaMask pede criarNovoContratoEscrow (o escrow é criado e o BRN é depositado nele)

Depois disso, sua ordem aparece no Mural e qualquer pessoa pode comprá-la.

⚠️ Enquanto a ordem estiver aberta, seu BRN fica preso no contrato. Só volta se:

alguém comprar, ou

você clicar em Cancelar

8.4. Comprar uma ordem (quem tem USDC)
Você vê no mural alguém oferecendo BRN e quer comprar:

No card da ordem, clique em "Liquidar Troca"

Confirme na MetaMask

O que acontece:

1ª transação — MetaMask pede approve do USDC (autoriza aquele escrow a usar seu USDC)

2ª transação — MetaMask pede executarTroca

Ao final: você recebe o BRN, o vendedor recebe o USDC

8.5. Cancelar sua ordem
Se você criou uma ordem e mudou de ideia:

No seu card (o que diz "(você)"), clique em "Cancelar"

Confirme na MetaMask

Seu BRN volta para sua carteira

8.6. Enviar BRN diretamente para outro endereço
Se você só quer transferir BRN para alguém (fora do sistema de escrow):

Painel "Enviar BRN com Segurança"

Cole o endereço de destino (ex.: 0x1234...abcd)

Digite a quantidade de BRN

Clique em "Validar e Enviar"

Confirme na MetaMask

⚠️ Atenção: essa transferência é irreversível. Se errar o endereço, perde os BRN.

8.7. Receber BRN
Para alguém te enviar BRN:

Painel "Receber BRN"

Copie seu endereço (botão "Copiar Endereço")

Compartilhe (botão "Compartilhar" abre o compartilhamento nativo do celular, ou copia)

A pessoa pode escanear o QR Code exibido

9. Manual técnico — manutenção
Logs
Todos os logs vão para o terminal onde o server.py roda:

Prefixo	Significa
[STARTUP]	Inicialização
[NGROK]	Estado do túnel
[WS]	Cliente WebSocket conectado/desconectado
[MURAL]	Ordem adicionada/cancelada/executada
[LIMPEZA]	Remoção de ordens expiradas
[SHUTDOWN]	Encerramento
Endpoints HTTP
URL	Função
GET /	Retorna index.html
GET /app.js	Retorna o JavaScript
GET /api/mural	JSON com ordens ativas
GET /health	Status do servidor
WS /ws	Canal WebSocket
Teste rápido no navegador: http://localhost:8080/health

Resposta esperada:

json
{
  "status": "ok",
  "clientes_ws": 1,
  "ordens_ativas": 3,
  "public_url": "https://...ngrok-free.dev",
  "timestamp": 1736934000
}
Protocolo WebSocket
Cliente → Servidor:

json
{ "tipo": "publicar_ordem", "ordem": {...} }
{ "tipo": "cancelar_ordem", "hash": "0x..." }
{ "tipo": "ordem_executada", "hash": "0x...", "txHash": "0x..." }
{ "tipo": "pedir_snapshot" }
{ "tipo": "ping" }
Servidor → Cliente:

json
{ "tipo": "snapshot", "ordens": [...] }
{ "tipo": "nova_ordem", "ordem": {...} }
{ "tipo": "ordem_cancelada", "hash": "0x..." }
{ "tipo": "ordem_executada", "hash": "0x...", "txHash": "0x..." }
{ "tipo": "ordem_expirada", "hash": "0x..." }
{ "tipo": "erro", "msg": "..." }
{ "tipo": "pong", "ts": 1736934000 }
Variáveis de ambiente
Variável	Padrão	Uso
PORT	8080	Porta HTTP local
Exemplo:

cmd
set PORT=3000
python server.py
Fluxo interno
text
COMEÇAR.bat
  ├─ lê navegador.txt
  ├─ lê ngrok_token.txt e ngrok_domain.txt
  ├─ verifica Python, aiohttp, pyngrok
  ├─ cria _abrir.bat (que abre o navegador em 10s)
  └─ executa: python server.py
       ├─ sobe aiohttp na porta 8080
       ├─ inicia NgrokTunnel
       └─ começa tarefa de limpeza (60s)
10. Solução de problemas
❌ "Python nao encontrado"
Causa: Python não está instalado ou não está no PATH.

Solução:

Reinstale Python marcando Add Python to PATH

Reinicie o computador

Verifique com python --version

❌ "server.py nao encontrado" (ou outro arquivo)
Causa: Você rodou o COMEÇAR.bat de fora da pasta do projeto.

Solução: Mova o .bat para dentro da pasta onde estão os arquivos e rode novamente.

❌ "Falha ao consultar a blockchain. Tentando novamente..."
Causa mais provável: RPC público da Polygon (polygon-rpc.com) está limitando requisições (HTTP 429).

Solução: O código atual já tem fallback automático para 5 RPCs. Se ainda falhar:

Abra DevTools (F12) → aba Console

Veja qual RPC falhou. Exemplo esperado:

text
[bruno] RPC falhou (https://polygon-rpc.com): 429
[bruno] RPC ativo: https://polygon-bor-rpc.publicnode.com
Se todos falharam, seu IP pode estar bloqueado temporariamente. Aguarde 5 min.

Se o Console mostrar call revert exception, o endereço da factory está errado → confira em https://polygonscan.com/address/0x5C30...62d8

❌ MetaMask abre mas a transação sempre reverte
Possíveis causas:

Erro no MetaMask	Causa	Solução
insufficient funds for gas	Sem POL	Compre POL e envie para a carteira
ERC20: insufficient allowance	Approve não foi feito	Recarregue a página e tente de novo
transfer amount exceeds balance	Saldo insuficiente	Confira seus saldos no painel
execution reverted: Ja executado	Ordem já foi comprada	Recarregue o mural
Criador nao pode comprar	Você tentou comprar sua própria ordem	Use outra carteira
❌ Ngrok não sobe / URL não abre
Causa: Token inválido ou domínio errado.

Solução:

Abra ngrok_token.txt — deve ter só o token, sem espaços

Abra ngrok_domain.txt — deve ter só o domínio (algumacoisa.ngrok-free.dev)

Confirme que o domínio existe em https://dashboard.ngrok.com/cloud-edge/domains

Reinicie o programa

❌ Chrome abre na URL errada ou não abre
Causa: navegador.txt com caminho inválido.

Solução:

Abra navegador.txt

Substitua por padrao (assim usará o navegador padrão do sistema)

Rode novamente

❌ "Sincronizador P2P: OFFLINE"
Causa: WebSocket não conectou.

Verificações:

O terminal mostra [WS] Conectado?

Sim → o problema é no navegador. Recarregue a página.

Não → o servidor pode estar bloqueando o /ws. Verifique o firewall.

Já rodou http://localhost:8080/health? Deve retornar "status": "ok".

❌ Mural vazio mas você sabe que há ordens
Confirme na blockchain: https://polygonscan.com/address/0x5C30...62d8#readContract

Clique em obterContratosGerados → veja se retorna endereços

Se retornar vazio → ninguém criou ordem ainda

Se retornar endereços mas o mural fica vazio → alguma ordem está executado ou cancelado (não aparecem)

❌ O programa fecha sozinho
Causa provável: Erro no server.py (arquivo truncado).

Solução: teste com:

cmd
python -c "import ast; ast.parse(open('server.py', encoding='utf-8').read()); print('OK')"
Se não imprimir OK, o arquivo está corrompido — substitua pela versão completa.

11. Segurança
O que o sistema protege
✅ Chaves privadas — nunca saem da MetaMask
✅ Fundos em escrow — só liberam com troca executada ou cancelamento
✅ Assinaturas — validadas pela blockchain, não pelo servidor
✅ Contratos imutáveis — ninguém (nem o admin) pode roubar fundos em escrow

O que o sistema NÃO protege
⚠️ Enviar para endereço errado — transferência direta de BRN é irreversível
⚠️ Phishing da URL do Ngrok — qualquer um com o link acessa a página
⚠️ MetaMask comprometida — se alguém tiver acesso à sua seed, perde tudo
⚠️ Servidor local comprometido — o server.py não é autenticado, ideal para uso pessoal

Boas práticas
Nunca compartilhe sua seed (as 12 palavras da MetaMask)

Nunca digite a seed em sites — a MetaMask nunca pede isso fora da extensão

Desconfie de links — sempre confira se a URL termina em .ngrok-free.dev do seu domínio

Comece com valores pequenos nos primeiros testes

Faça backup da seed em papel físico, guardado em local seguro

Use uma carteira separada para testes (não a sua carteira principal)

Sobre o domínio Ngrok
O domínio seventy-rigging-ploy.ngrok-free.dev é público. Qualquer pessoa com o link consegue abrir a página. Se quiser restringir:

Adicione autenticação básica no server.py

Ou use um domínio com regra de IP no Ngrok

Ou prefira rodar apenas local (localhost:8080) e não expor

12. Contratos inteligentes
EscrowFactory
Endereço: 0x5C305aCFF5cDFAee90276c2acEA4Aa841f7062d8
Polygonscan: https://polygonscan.com/address/0x5C305aCFF5cDFAee90276c2acEA4Aa841f7062d8

Funções principais:

Função	Descrição
criarNovoContratoEscrow(...)	Cria um escrow novo e deposita o token
obterContratosGerados()	Retorna a lista de todos os escrows já criados
EscrowIndividual
Cada ordem gera um contrato próprio com estas funções:

Função	Descrição
obterDados()	Retorna (tokenOferecido, tokenDesejado, criador, valorOferecido, valorDesejado, executado, cancelado)
executarTroca()	Comprador chama; paga tokenDesejado, recebe tokenOferecido
cancelar()	Criador chama; recebe tokenOferecido de volta
Tokens
Token	Endereço	Decimais
BRN	0xdBc1c747B1D4c27113F65A4620b8fEaC74e2A210	18
USDC (Polygon)	0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174	6
Como fazer deploy (se for trocar de contrato)
Abra https://remix.ethereum.org

Cole o conteúdo de EscrowFactory.sol

Compile com Solidity 0.8.20+

Em Deploy & Run, escolha Injected Provider - MetaMask

Confirme na MetaMask (na Polygon Mainnet)

Copie o endereço gerado

Cole no app.js na constante ESCROW_FACTORY_ADDRESS

13. Perguntas frequentes
1. Preciso pagar alguma taxa para usar?

Só o gas da Polygon (uns centavos de POL por transação). O sistema em si é gratuito.

2. O que acontece se eu fechar o navegador com ordens abertas?

Nada. As ordens ficam na blockchain. Ao reabrir, elas reaparecem no mural.

3. Posso rodar em outro computador?

Sim. Copie a pasta inteira, instale Python e pyngrok/ngrok, e rode novamente. Os contratos são globais (na Polygon).

4. E se eu perder minha seed da MetaMask?

Perde todos os fundos. Não há recuperação. Guarde a seed em local seguro.

5. Preciso manter o computador ligado?

Só se quiser servir o site. Como as ordens ficam na blockchain, outros usuários podem acessar a mesma URL do Ngrok apenas se o servidor estiver rodando. Para uso pessoal, não precisa.

6. Dá para aumentar a taxa de ordens?

Sim. Edite em app.js:

javascript
const ESCROW_FACTORY_ADDRESS = "...";
Mas isso exige novo deploy do contrato com a taxa alterada.

7. O mural é atualizado em tempo real?

Sim. Ele:

recarrega a cada 30 segundos automaticamente

recarrega imediatamente quando o WebSocket recebe uma notificação

recarrega quando você cria/liquida/cancela

8. Como sei que estou na Polygon correta?

No topo da MetaMask deve aparecer "Polygon Mainnet". Se aparecer "Ethereum" ou "Mumbai", clique na rede → troque para Polygon Mainnet.

9. Posso usar no celular?

A interface funciona em celular, mas a MetaMask móvel não se integra bem com window.ethereum do navegador. O ideal é usar MetaMask Browser dentro do app da MetaMask.

10. Quanto tempo demora uma transação?

Normalmente 2 a 5 segundos na Polygon. Se estiver congestionada, até 30 segundos. Pode aumentar o gas na MetaMask se quiser prioridade.

📞 Suporte
Se algo não funcionar:

Releia a seção 10. Solução de problemas

Abra o Console (F12) e copie as mensagens

Verifique o terminal onde o server.py roda

Confirme os endereços dos contratos no Polygonscan

Fim do manual.
Versão 1.0 — Projeto Carteira BRN P2P.


