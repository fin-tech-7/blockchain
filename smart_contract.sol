// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/*
 * DonationSettlement
 * - 오프체인(KakaoPay) 결제 후, 백엔드가 환전한 자금을 온체인에서 수령자(B)에게 즉시 전달하고 영수증을 남김
 * - ETH / ERC20 둘 다 지원
 * - writer(백엔드)만 정산 함수 호출 가능
 */

import {Ownable} from "https://github.com/OpenZeppelin/openzeppelin-contracts/blob/v5.0.2/contracts/access/Ownable.sol";
import {Pausable} from "https://github.com/OpenZeppelin/openzeppelin-contracts/blob/v5.0.2/contracts/utils/Pausable.sol";
import {ReentrancyGuard} from "https://github.com/OpenZeppelin/openzeppelin-contracts/blob/v5.0.2/contracts/utils/ReentrancyGuard.sol";
import {IERC20} from "https://github.com/OpenZeppelin/openzeppelin-contracts/blob/v5.0.2/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "https://github.com/OpenZeppelin/openzeppelin-contracts/blob/v5.0.2/contracts/token/ERC20/utils/SafeERC20.sol";

contract DonationSettlement is Ownable, Pausable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    // ===== Errors =====
    error NotWriter();
    error OrderIdUsed();
    error ZeroAddress();
    error ZeroAmount();
    error MemoTooLong();

    // ===== Config =====
    uint256 public constant MEMO_MAX_LEN = 256;

    // fee = amount * feeBps / 10_000
    uint16  public feeBps;
    address public feeRecipient;

    // writer 권한 (백엔드)
    address public writer;
    address public pendingWriter;

    // ===== Storage =====
    struct Receipt {
        address donor;
        address beneficiary;
        address asset;  // address(0)=ETH, ERC20 주소
        uint256 amount; // 원금(수수료 포함 입력 금액)
        uint256 fee;
        string  memo;
        uint256 timestamp;
    }

    mapping(bytes32 => bool) private usedOrderIds;   // orderId 중복 방지
    mapping(bytes32 => Receipt) public receipts;     // orderId → 영수증

    // [호환 어댑터] 단순 기록용 노트 (orderId 없이 amount/memo만 저장)
    struct Note { uint256 amount; string memo; uint256 timestamp; address writerAddr; }
    uint256 public noteSeq;
    mapping(uint256 => Note) public notes;

    // ===== Events =====
    event WriterProposed(address indexed currentWriter, address indexed proposedWriter);
    event WriterUpdated(address indexed oldWriter, address indexed newWriter);

    event DonatedETH(
        bytes32 indexed orderId,
        address indexed donor,
        address indexed beneficiary,
        uint256 grossAmount,
        uint256 feeAmount,
        uint256 netAmount,
        string memo,
        uint256 timestamp
    );

    event DonatedERC20(
        bytes32 indexed orderId,
        address indexed donor,
        address indexed beneficiary,
        address token,
        uint256 grossAmount,
        uint256 feeAmount,
        uint256 netAmount,
        string memo,
        uint256 timestamp
    );

    // 
    event DonationRecordedCompat(
        address indexed writer,
        uint256 amount,
        string memo,
        uint256 timestamp,
        uint256 noteId
    );

    event FeeConfigUpdated(uint16 feeBps, address feeRecipient);
    event Paused();
    event Unpaused();

    // ===== Modifiers =====
    modifier onlyWriter() {
        if (msg.sender != writer) revert NotWriter();
        _;
    }

    // ===== Constructor =====
    constructor(address _owner, address _writer, address _feeRecipient, uint16 _feeBps) Ownable(_owner) {
        if (_writer == address(0) || _feeRecipient == address(0)) revert ZeroAddress();
        writer       = _writer;
        feeRecipient = _feeRecipient;
        feeBps       = _feeBps; // 0 가능
    }

    // ===== Admin =====
    function proposeWriter(address _pending) external onlyOwner {
        if (_pending == address(0)) revert ZeroAddress();
        pendingWriter = _pending;
        emit WriterProposed(writer, _pending);
    }

    function acceptWriter() external {
        if (msg.sender != pendingWriter) revert NotWriter();
        address old = writer;
        writer = pendingWriter;
        pendingWriter = address(0);
        emit WriterUpdated(old, writer);
    }

    function forceSetWriter(address _new) external onlyOwner {
        if (_new == address(0)) revert ZeroAddress();
        address old = writer;
        writer = _new;
        pendingWriter = address(0);
        emit WriterUpdated(old, _new);
    }

    function setFee(uint16 _feeBps, address _feeRecipient) external onlyOwner {
        if (_feeRecipient == address(0)) revert ZeroAddress();
        feeBps = _feeBps;
        feeRecipient = _feeRecipient;
        emit FeeConfigUpdated(_feeBps, _feeRecipient);
    }

    function pause() external onlyOwner { _pause(); emit Paused(); }
    function unpause() external onlyOwner { _unpause(); emit Unpaused(); }

    // ===== Views =====
    function hasOrderId(bytes32 orderId) external view returns (bool) {
        return usedOrderIds[orderId];
    }

    // ===== Core: ETH path =====
    function donateEthAndForward(
        bytes32 orderId,
        address donor,
        address beneficiary,
        string calldata memo
    ) external payable onlyWriter nonReentrant whenNotPaused {
        if (usedOrderIds[orderId]) revert OrderIdUsed();
        if (donor == address(0) || beneficiary == address(0)) revert ZeroAddress();
        if (msg.value == 0) revert ZeroAmount();
        if (bytes(memo).length > MEMO_MAX_LEN) revert MemoTooLong();

        usedOrderIds[orderId] = true;

        uint256 fee = (msg.value * feeBps) / 10_000;
        uint256 net = msg.value - fee;

        (bool ok1, ) = beneficiary.call{value: net}("");
        require(ok1, "beneficiary transfer failed");

        if (fee > 0) {
            (bool ok2, ) = feeRecipient.call{value: fee}("");
            require(ok2, "fee transfer failed");
        }

        receipts[orderId] = Receipt({
            donor: donor,
            beneficiary: beneficiary,
            asset: address(0),
            amount: msg.value,
            fee: fee,
            memo: memo,
            timestamp: block.timestamp
        });

        emit DonatedETH(orderId, donor, beneficiary, msg.value, fee, net, memo, block.timestamp);
    }

    // ===== Core: ERC20 path =====
    function donateTokenAndForward(
        bytes32 orderId,
        address donor,
        address beneficiary,
        IERC20 token,
        uint256 amount,
        string calldata memo
    ) external onlyWriter nonReentrant whenNotPaused {
        if (usedOrderIds[orderId]) revert OrderIdUsed();
        if (address(token) == address(0) || donor == address(0) || beneficiary == address(0)) revert ZeroAddress();
        if (amount == 0) revert ZeroAmount();
        if (bytes(memo).length > MEMO_MAX_LEN) revert MemoTooLong();

        usedOrderIds[orderId] = true;

        uint256 fee = (amount * feeBps) / 10_000;
        uint256 net = amount - fee;

        token.safeTransferFrom(msg.sender, address(this), amount);
        if (net > 0) token.safeTransfer(beneficiary, net);
        if (fee > 0) token.safeTransfer(feeRecipient, fee);

        receipts[orderId] = Receipt({
            donor: donor,
            beneficiary: beneficiary,
            asset: address(token),
            amount: amount,
            fee: fee,
            memo: memo,
            timestamp: block.timestamp
        });

        emit DonatedERC20(orderId, donor, beneficiary, address(token), amount, fee, net, memo, block.timestamp);
    }

    // ===== Compatibility Adapter (no funds move) =====
    /// @dev writer 전용, paused 시 금지. amount>0, memo<=256.
    function recordDonation(uint256 amount, string calldata memo) external onlyWriter whenNotPaused {
        if (amount == 0) revert ZeroAmount();
        if (bytes(memo).length > MEMO_MAX_LEN) revert MemoTooLong();

        // 간단한 노트 저장 (연속 ID)
        uint256 id = ++noteSeq;
        notes[id] = Note({
            amount: amount,
            memo: memo,
            timestamp: block.timestamp,
            writerAddr: msg.sender
        });

        emit DonationRecordedCompat(msg.sender, amount, memo, block.timestamp, id);
    }

    // ===== Emergency =====
    function rescueETH(address to, uint256 amount) external onlyOwner {
        if (to == address(0)) revert ZeroAddress();
        (bool ok, ) = to.call{value: amount}("");
        require(ok, "rescue eth failed");
    }

    function rescueToken(IERC20 token, address to, uint256 amount) external onlyOwner {
        if (to == address(0)) revert ZeroAddress();
        token.safeTransfer(to, amount);
    }

    receive() external payable {}
}
