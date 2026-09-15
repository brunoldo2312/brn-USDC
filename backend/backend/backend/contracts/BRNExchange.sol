// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IERC20 {
    function transfer(address to, uint256 value) external returns (bool);
    function transferFrom(address from, address to, uint256 value)
        external returns (bool);
    function balanceOf(address who) external view returns (uint256);
}

/**
 * @title BRNExchange
 * @notice Exchange centralizada BRN/USDC.
 *
 * Fluxo:
 *   1. Vendedor: approve(BRN) + createSellOrder(brnAmount, priceUSDC, usdcAddr)
 *      → BRN fica em escrow no contrato.
 *   2. Comprador: paga USDC direto ao `operator` (hot wallet off-chain).
 *   3. Operador: fillOrder(orderId, buyer) → BRN vai pro comprador.
 *   4. Operador: envia USDC ao vendedor via hot wallet (fora do contrato).
 *
 * O contrato NÃO movimenta USDC — apenas BRN. USDC é tratado
 * off-chain pelo operador, o que simplifica e reduz gás.
 */
contract BRNExchange {
    struct Order {
        address seller;         // quem depositou BRN
        address usdcReceiver;   // endereço Polygon que recebe USDC
        uint256 brnAmount;      // BRN em escrow (wei)
        uint256 pricePerBRN;    // USDC por BRN (6 decimais)
        uint256 totalUSDC;      // brnAmount * pricePerBRN / 1e18
        uint8   status;         // 0=OPEN 1=FILLED 2=CANCELLED
        address buyer;          // preenchido ao fill
        uint64  createdAt;
        uint64  filledAt;
    }

    IERC20  public immutable brn;
    address public operator;    // hot wallet que libera ordens
    address public owner;       // admin (pode trocar operator)

    uint256 public nextOrderId = 1;
    mapping(uint256 => Order) public orders;
    uint256[] public openOrderIds;

    // ---------------- Eventos ----------------
    event OrderCreated(
        uint256 indexed id, address indexed seller,
        address usdcReceiver, uint256 brnAmount,
        uint256 pricePerBRN, uint256 totalUSDC
    );
    event OrderFilled(
        uint256 indexed id, address indexed buyer, address operator
    );
    event OrderCancelled(uint256 indexed id, address indexed seller);
    event OperatorChanged(address indexed prev, address indexed next);

    modifier onlyOperator() {
        require(msg.sender == operator, "EX: not operator");
        _;
    }
    modifier onlyOwner() {
        require(msg.sender == owner, "EX: not owner");
        _;
    }

    constructor(address brnToken, address operator_) {
        require(brnToken != address(0), "EX: brn zero");
        require(operator_ != address(0), "EX: op zero");
        brn = IERC20(brnToken);
        operator = operator_;
        owner = msg.sender;
    }

    // ---------------- Vendedor ----------------
    /**
     * @param brnAmount     quantidade de BRN (wei, 18 decimais)
     * @param pricePerBRN   preço em USDC por 1 BRN (6 decimais)
     * @param usdcReceiver  endereço Polygon que receberá USDC
     *
     * Requer approve(BRN, brnAmount) antes.
     */
    function createSellOrder(
        uint256 brnAmount,
        uint256 pricePerBRN,
        address usdcReceiver
    ) external returns (uint256 id) {
        require(brnAmount > 0, "EX: amount 0");
        require(pricePerBRN > 0, "EX: price 0");
        require(usdcReceiver != address(0), "EX: usdc zero");

        // puxa BRN pro contrato (escrow)
        require(
            brn.transferFrom(msg.sender, address(this), brnAmount),
            "EX: transferFrom failed"
        );

        uint256 totalUSDC = (brnAmount * pricePerBRN) / 1e18;

        id = nextOrderId++;
        orders[id] = Order({
            seller: msg.sender,
            usdcReceiver: usdcReceiver,
            brnAmount: brnAmount,
            pricePerBRN: pricePerBRN,
            totalUSDC: totalUSDC,
            status: 0,
            buyer: address(0),
            createdAt: uint64(block.timestamp),
            filledAt: 0
        });
        openOrderIds.push(id);

        emit OrderCreated(
            id, msg.sender, usdcReceiver,
            brnAmount, pricePerBRN, totalUSDC
        );
    }

    function cancelOrder(uint256 id) external {
        Order storage o = orders[id];
        require(o.status == 0, "EX: not open");
        require(o.seller == msg.sender, "EX: not seller");
        o.status = 2;
        require(brn.transfer(o.seller, o.brnAmount), "EX: refund failed");
        emit OrderCancelled(id, msg.sender);
    }

    // ---------------- Operador ----------------
    /**
     * Libera BRN ao comprador. Só o operador pode chamar.
     * O operador já confirmou o pagamento USDC off-chain.
     */
    function fillOrder(uint256 id, address buyer) external onlyOperator {
        Order storage o = orders[id];
        require(o.status == 0, "EX: not open");
        require(buyer != address(0), "EX: buyer zero");

        o.status = 1;
        o.buyer = buyer;
        o.filledAt = uint64(block.timestamp);

        require(brn.transfer(buyer, o.brnAmount), "EX: send failed");
        emit OrderFilled(id, buyer, msg.sender);
    }

    // ---------------- Admin ----------------
    function setOperator(address next) external onlyOwner {
        require(next != address(0), "EX: zero");
        emit OperatorChanged(operator, next);
        operator = next;
    }

    function transferOwnership(address next) external onlyOwner {
        require(next != address(0), "EX: zero");
        owner = next;
    }

    // ---------------- Views ----------------
    function getOrder(uint256 id) external view returns (Order memory) {
        return orders[id];
    }

    function openOrdersCount() external view returns (uint256) {
        return openOrderIds.length;
    }

    function getOpenOrders(uint256 offset, uint256 limit)
        external view returns (Order[] memory result, uint256[] memory ids)
    {
        uint256 n = openOrderIds.length;
        if (offset >= n) {
            return (new Order[](0), new uint256[](0));
        }
        uint256 end = offset + limit;
        if (end > n) end = n;

        uint256 count = 0;
        for (uint256 i = offset; i < end; i++) {
            if (orders[openOrderIds[i]].status == 0) count++;
        }

        result = new Order[](count);
        ids    = new uint256[](count);
        uint256 j = 0;
        for (uint256 i = offset; i < end; i++) {
            uint256 oid = openOrderIds[i];
            if (orders[oid].status == 0) {
                result[j] = orders[oid];
                ids[j]    = oid;
                j++;
            }
        }
    }
}
