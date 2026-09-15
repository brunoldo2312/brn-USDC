[Vendedor]                              [Comprador]
   │                                        │
   │ 1. Coloca ordem: VENDO 100 BRN        │
   │    por 0.50 USDC/BRN                   │
   │    + endereço USDC de recebimento      │
   │                                        │
   │ → 100 BRN são TRAVADOS (escrow)        │
   │   no banco local                       │
   │                                        │
   │                         2. Vê a ordem │
   │                         3. Envia USDC │
   │                            (50 USDC)  │
   │                            no MetaMask│
   │                            para o      │
   │                            endereço do │
   │                            vendedor    │
   │                                        │
   │                         4. Cola o hash │
   │                            da tx no GUI│
   │                                        │
   │        5. Nó consulta o RPC da Polygon │
   │           confere se o Transfer USDC   │
   │           foi pago corretamente        │
   │                                        │
   │        6. Libera os 100 BRN travados   │
   │           → crédita no comprador       │
   │                                        │
   │        7. Ordem marcada como FILLED    │




[Vendedor]                          [VOCÊ - OPERADOR]              [Comprador]
    │                                      │                            │
    │ 1. Coloca ordem: 100 BRN a 0.5      │                            │
    │    + endereço USDC dele             │                            │
    │                                      │                            │
    │ ── BRN vai pro SEU wallet ─────────►│                            │
    │                                      │                            │
    │                                      │◄── 2. Comprador envia ────│
    │                                      │    USDC pro SEU wallet    │
    │                                      │                            │
    │                                      │ 3. Você confirma e:      │
    │◄── 4. USDC vai pro vendedor ────────│                            │
    │                                      │──── 5. BRN vai pro ──────►│
    │                                      │       comprador            │
