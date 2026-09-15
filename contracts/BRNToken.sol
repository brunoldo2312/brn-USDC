// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title BRNToken
 * @notice Token ERC-20 nativo da rede BRN.
 *         Supply inicial cunhado para o operador.
 *         Mint adicional só pelo owner (para recompensas de mineração).
 */
contract BRNToken {
    string public constant name = "BRN Token";
    string public constant symbol = "BRN";
    uint8  public constant decimals = 18;

    uint256 public totalSupply;
    address public owner;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    event OwnershipTransferred(address indexed prev, address indexed next);

    modifier onlyOwner() {
        require(msg.sender == owner, "BRN: not owner");
        _;
    }

    constructor(uint256 initialSupply) {
        owner = msg.sender;
        _mint(msg.sender, initialSupply);
    }

    // ---------------- ERC-20 ----------------
    function transfer(address to, uint256 value) external returns (bool) {
        _transfer(msg.sender, to, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value)
        external returns (bool)
    {
        uint256 allowed = allowance[from][msg.sender];
        require(allowed >= value, "BRN: allowance");
        if (allowed != type(uint256).max) {
            allowance[from][msg.sender] = allowed - value;
        }
        _transfer(from, to, value);
        return true;
    }

    function approve(address spender, uint256 value) external returns (bool) {
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }

    // ---------------- Owner ----------------
    function mint(address to, uint256 value) external onlyOwner {
        _mint(to, value);
    }

    function transferOwnership(address next) external onlyOwner {
        require(next != address(0), "BRN: zero");
        emit OwnershipTransferred(owner, next);
        owner = next;
    }

    // ---------------- Internos ----------------
    function _transfer(address from, address to, uint256 value) internal {
        require(to != address(0), "BRN: to zero");
        uint256 bal = balanceOf[from];
        require(bal >= value, "BRN: balance");
        unchecked { balanceOf[from] = bal - value; }
        balanceOf[to] += value;
        emit Transfer(from, to, value);
    }

    function _mint(address to, uint256 value) internal {
        require(to != address(0), "BRN: mint zero");
        totalSupply += value;
        balanceOf[to] += value;
        emit Transfer(address(0), to, value);
    }
}
