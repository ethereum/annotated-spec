# The Merge -- The Beacon Chain

**Notice**: This document is a work-in-progress for researchers and implementers.

## Table of contents

<!-- TOC -->
<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->

- [Introduction](#introduction)
- [Custom types](#custom-types)
- [Constants](#constants)
  - [Execution](#execution)
- [Configuration](#configuration)
  - [Transition settings](#transition-settings)
- [Containers](#containers)
  - [Extended containers](#extended-containers)
    - [`BeaconBlockBody`](#beaconblockbody)
    - [`BeaconState`](#beaconstate)
  - [New containers](#new-containers)
    - [`ExecutionPayload`](#executionpayload)
    - [`ExecutionPayloadHeader`](#executionpayloadheader)
- [Helper functions](#helper-functions)
  - [Predicates](#predicates)
    - [`is_merge_complete`](#is_merge_complete)
    - [`is_merge_block`](#is_merge_block)
    - [`is_execution_enabled`](#is_execution_enabled)
  - [Misc](#misc)
    - [`compute_timestamp_at_slot`](#compute_timestamp_at_slot)
- [Beacon chain state transition function](#beacon-chain-state-transition-function)
  - [Execution engine](#execution-engine)
    - [`execute_payload`](#execute_payload)
    - [`notify_consensus_validated`](#notify_consensus_validated)
  - [Block processing](#block-processing)
  - [Execution payload processing](#execution-payload-processing)
    - [`is_valid_gas_limit`](#is_valid_gas_limit)
    - [`process_execution_payload`](#process_execution_payload)
- [Testing](#testing)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->
<!-- /TOC -->

## Introduction

The Merge is the event in which the Ethereum proof of work chain is deprecated, and the beacon chain (the Ethereum proof of stake chain) takes over as the chain that Ethereum is running on. To simplify the Merge and allow it to happen faster, the Merge is designed via a **block-inside-a-block structure**: the Ethereum PoW chain appears to continue, except past a certain transition point (i) the PoW nonces are no longer required to be valid, and (ii) the Ethereum PoW blocks, from then on referred to as **execution blocks**, are required to be embedded inside of beacon chain blocks.

![](https://i.imgur.com/udZlkQr.png)

The timing of the merge is parametrized by two thresholds:

* The `MERGE_FORK_EPOCH`, the epoch at which the beacon chain includes the post-merge features (mainly, the ability to contain execution blocks), and so the merge becomes possible
* The `TERMINAL_TOTAL_DIFFICULTY`, the total PoW difficulty such that a block those total difficulty is `>= TERMINAL_TOTAL_DIFFICULTY` (but whose parent is below the threshold) is a terminal block, so its children and further descendants do not require PoW and must be part of beacon chain blocks.

Total difficulty is used as a threshold instead of block height (which forks normally use) for security: it prevents an attacker from privately creating a chain with lower difficulty but higher block height and then colluding with a single beacon proposer to get it included first. Using TD ensures that the winner of the PoW fork choice becomes eligible for inclusion into the beacon chain before any other block.

The parameters are expected to be set such that the beacon chain reaches the `MERGE_FORK_EPOCH` before the PoW chain reaches the `TERMINAL_TOTAL_DIFFICULTY`. Hence, by the time the PoW chain gets a terminal block, which can only have an **embedded block** inside the beacon chain as a child, the beacon chain will be ready to accept embedded blocks. In the unlikely case that the events end up happening in the other order (only possible if miners attack the transition by adding a _huge_ amount of new hashpower), Ethereum will simply be offline and not generate new blocks until the `MERGE_FORK_EPOCH` is reached.

## Custom types

*Note*: The `Transaction` type is a stub which is not final.

| Name | SSZ equivalent | Description |
| - | - | - |
| `OpaqueTransaction` | `ByteList[MAX_BYTES_PER_OPAQUE_TRANSACTION]` | a [typed transaction envelope](https://eips.ethereum.org/EIPS/eip-2718#opaque-byte-array-rather-than-an-rlp-array) structured as `TransactionType \|\| TransactionPayload` |
| `Transaction` | `Union[OpaqueTransaction]` | a transaction |
| `ExecutionAddress` | `Bytes20` | Address of account on the execution layer |

The beacon chain uses [SSZ](https://github.com/ethereum/consensus-specs/blob/dev/ssz/simple-serialize.md) for serialization and SSZ + SHA256 for hashing, and the execution chain uses [RLP](https://eth.wiki/fundamentals/rlp) for serialization, and the keccak hash of the RLP serialized form for hashing. In the long term, it's a desired goal to move everything to SSZ. For now, however, because of the desire to finish the merge quickly, most of the execution chain remains RLP-based. Specifically, execution _blocks_ are stored in SSZ form, but the _transactions_ inside them are encoded with RLP, and so to software that only understands SSZ they are presented as "opaque" byte arrays. Note also that the `parent_hash` of an execution block is expected to match the keccak hash of the RLP-serialized form of the previous execution block.

## Constants

### Execution

| Name | Value |
| - | - |
| `MAX_BYTES_PER_OPAQUE_TRANSACTION` | `uint64(2**20)` (= 1,048,576) |
| `MAX_TRANSACTIONS_PER_PAYLOAD` | `uint64(2**14)` (= 16,384) |
| `BYTES_PER_LOGS_BLOOM` | `uint64(2**8)` (= 256) |
| `GAS_LIMIT_DENOMINATOR` | `uint64(2**10)` (= 1,024) |
| `MIN_GAS_LIMIT` | `uint64(5000)` (= 5,000) |
| `MAX_EXTRA_DATA_BYTES` | `2**5` (= 32) |

The `GAS_LIMIT_DENOMINATOR` is the inverse of the max fraction by which a block's gas limit can change per block. This is identical to the gas limit voting mechanism on the execution chain.

## Configuration

### Transition settings

| Name | Value |
| - | - |
| `TERMINAL_TOTAL_DIFFICULTY` | **TBD** |
| `TERMINAL_BLOCK_HASH` | `Hash32('0x0000000000000000000000000000000000000000000000000000000000000000')` |

The `TERMINAL_BLOCK_HASH` feature is an emergency override mechanism. If PoW miners attempt to cause chaos on the chain via 51% attacks before the merge, the community can react by setting the `TERMINAL_BLOCK_HASH` to choose a specific terminal block, and the `MERGE_FORK_EPOCH` to some specific value in the future (ideally not too far in the future). The Ethereum chain would make no progress between this point and the `MERGE_FORK_EPOCH`, but after that point it would proceed smoothly embedded inside the beacon chain.

Note that if the `TERMINAL_BLOCK_HASH` is set to any value that is clearly not a valid hash output (eg. zero), this means that there is no valid block that could trigger the hash-based validity condition, so a block reaching the `TERMINAL_TOTAL_DIFFICULTY` is the only option.

## Containers

### Extended containers

#### `BeaconBlockBody`

```python
class BeaconBlockBody(Container):
    randao_reveal: BLSSignature
    eth1_data: Eth1Data  # Eth1 data vote
    graffiti: Bytes32  # Arbitrary data
    # Operations
    proposer_slashings: List[ProposerSlashing, MAX_PROPOSER_SLASHINGS]
    attester_slashings: List[AttesterSlashing, MAX_ATTESTER_SLASHINGS]
    attestations: List[Attestation, MAX_ATTESTATIONS]
    deposits: List[Deposit, MAX_DEPOSITS]
    voluntary_exits: List[SignedVoluntaryExit, MAX_VOLUNTARY_EXITS]
    sync_aggregate: SyncAggregate
    # Execution
    execution_payload: ExecutionPayload  # [New in Merge]
```

Extend a beacon block with the `ExecutionPayload` object (the embedded execution block).

#### `BeaconState`

```python
class BeaconState(Container):
    # Versioning
    genesis_time: uint64
    genesis_validators_root: Root
    slot: Slot
    fork: Fork
    # History
    latest_block_header: BeaconBlockHeader
    block_roots: Vector[Root, SLOTS_PER_HISTORICAL_ROOT]
    state_roots: Vector[Root, SLOTS_PER_HISTORICAL_ROOT]
    historical_roots: List[Root, HISTORICAL_ROOTS_LIMIT]
    # Eth1
    eth1_data: Eth1Data
    eth1_data_votes: List[Eth1Data, EPOCHS_PER_ETH1_VOTING_PERIOD * SLOTS_PER_EPOCH]
    eth1_deposit_index: uint64
    # Registry
    validators: List[Validator, VALIDATOR_REGISTRY_LIMIT]
    balances: List[Gwei, VALIDATOR_REGISTRY_LIMIT]
    # Randomness
    randao_mixes: Vector[Bytes32, EPOCHS_PER_HISTORICAL_VECTOR]
    # Slashings
    slashings: Vector[Gwei, EPOCHS_PER_SLASHINGS_VECTOR]  # Per-epoch sums of slashed effective balances
    # Participation
    previous_epoch_participation: List[ParticipationFlags, VALIDATOR_REGISTRY_LIMIT]
    current_epoch_participation: List[ParticipationFlags, VALIDATOR_REGISTRY_LIMIT]
    # Finality
    justification_bits: Bitvector[JUSTIFICATION_BITS_LENGTH]  # Bit set for every recent justified epoch
    previous_justified_checkpoint: Checkpoint
    current_justified_checkpoint: Checkpoint
    finalized_checkpoint: Checkpoint
    # Inactivity
    inactivity_scores: List[uint64, VALIDATOR_REGISTRY_LIMIT]
    # Sync
    current_sync_committee: SyncCommittee
    next_sync_committee: SyncCommittee
    # Execution
    latest_execution_payload_header: ExecutionPayloadHeader  # [New in Merge]
```

Extend the `BeaconState` by adding the `ExecutionPayloadHeader` of the most recently included execution block. This contains data like execution block hash, post-state root, gas limit, etc, that the next execution block will need to be checked against.

### New containers

#### `ExecutionPayload`

*Note*: The `base_fee_per_gas` field is serialized in little-endian.

```python
class ExecutionPayload(Container):
    # Execution block header fields
    parent_hash: Hash32
    coinbase: ExecutionAddress  # 'beneficiary' in the yellow paper
    state_root: Bytes32
    receipt_root: Bytes32  # 'receipts root' in the yellow paper
    logs_bloom: ByteVector[BYTES_PER_LOGS_BLOOM]
    random: Bytes32  # 'difficulty' in the yellow paper
    block_number: uint64  # 'number' in the yellow paper
    gas_limit: uint64
    gas_used: uint64
    timestamp: uint64
    extra_data: ByteList[MAX_EXTRA_DATA_BYTES]
    base_fee_per_gas: Bytes32  # base fee introduced in EIP-1559, little-endian serialized
    # Extra payload fields
    block_hash: Hash32  # Hash of execution block
    transactions: List[Transaction, MAX_TRANSACTIONS_PER_PAYLOAD]
```

The data structure that stores the execution block. Note that the execution block hash is part of the structure and not computed from it. Verification of this hash is done by execution clients (formerly known as "eth1 clients"; eg. Geth, Nethermind, Erigon, Besu) when the execution block is passed to them for verification.

#### `ExecutionPayloadHeader`

```python
class ExecutionPayloadHeader(Container):
    # Execution block header fields
    parent_hash: Hash32
    coinbase: ExecutionAddress
    state_root: Bytes32
    receipt_root: Bytes32
    logs_bloom: ByteVector[BYTES_PER_LOGS_BLOOM]
    random: Bytes32
    block_number: uint64
    gas_limit: uint64
    gas_used: uint64
    timestamp: uint64
    extra_data: ByteList[MAX_EXTRA_DATA_BYTES]
    base_fee_per_gas: Bytes32
    # Extra payload fields
    block_hash: Hash32  # Hash of execution block
    transactions_root: Root
```

Same structure as above, except the transaction list is replaced by its SSZ hash tree root.

## Helper functions

### Predicates

#### `is_merge_complete`

```python
def is_merge_complete(state: BeaconState) -> bool:
    return state.latest_execution_payload_header != ExecutionPayloadHeader()
```

Returns whether or not the merge "has already happened", defined by whether or not there has already been an embedded execution block inside the beacon chain (if there has, its header is saved in `state.latest_execution_payload_header`).

#### `is_merge_block`

```python
def is_merge_block(state: BeaconState, body: BeaconBlockBody) -> bool:
    return not is_merge_complete(state) and body.execution_payload != ExecutionPayload()
```

Returns whether or not a given block is the first block that contains an embedded execution block.

#### `is_execution_enabled`

```python
def is_execution_enabled(state: BeaconState, body: BeaconBlockBody) -> bool:
    return is_merge_block(state, body) or is_merge_complete(state)
```

### Misc

#### `compute_timestamp_at_slot`

*Note*: This function is unsafe with respect to overflows and underflows.

```python
def compute_timestamp_at_slot(state: BeaconState, slot: Slot) -> uint64:
    slots_since_genesis = slot - GENESIS_SLOT
    return uint64(state.genesis_time + slots_since_genesis * SECONDS_PER_SLOT)
```

## Beacon chain state transition function

### Execution engine

This function calls the execution client (formerly known as an "eth1 client"; eg. Geth, Nethermind, Erigon, Besu) to validate the execution block in the `execution_payload`. The payload contains the `parent_hash`, so the execution engine knows what pre-state to verify the execution block off of. Note that there is implied state (the execution pre-state) that is stored by the execution client and that the execution client is expected to use to validate the block. The function can be considered quasi-pure in that although it does not pass the pre-state in as an explicit argument, the `execution_payload.parent_hash` is nevertheless cryptographically linked to a unique pre-state.

Under normal operation, there is no possibility that the pre-state is unavailable, because a beacon block would only be validated if all of its ancestors have been validated, and that ensures that the previous execution blocks were validated and their post-state (and hence the latest block's pre-state) would already be computed. The only exception to this logic is the _first_ embedded execution block, whose parent (the terminal PoW block) is not in the beacon chain. If the terminal PoW block is unavailable, the beacon chain client should wait until the terminal PoW block becomes available before accepting the beacon block . Importantly, the beacon chain client should NOT "conclusively reject" a beacon block whose embedded execution block's parent is an unavailable terminal PoW block, because the terminal PoW block could become available very soon in the future. 

#### `execute_payload`

```python
def execute_payload(self: ExecutionEngine, execution_payload: ExecutionPayload) -> bool:
    """
    Return ``True`` if and only if ``execution_payload`` is valid with respect to ``self.execution_state``.
    """
    ...
```

### Block processing

*Note*: The call to the `process_execution_payload` must happen before the call to the `process_randao` as the former depends on the `randao_mix` computed with the reveal of the previous block.

```python
def process_block(state: BeaconState, block: BeaconBlock) -> None:
    process_block_header(state, block)
    if is_execution_enabled(state, block.body):
        process_execution_payload(state, block.body.execution_payload, EXECUTION_ENGINE)  # [New in Merge]
    process_randao(state, block.body)
    process_eth1_data(state, block.body)
    process_operations(state, block.body)
    process_sync_aggregate(state, block.body.sync_aggregate)
```

The main addition to the `process_block` function is the `process_execution_payload` function. This function is computed against the previous `randao` because we want it to be possible to construct an execution block without having secret information only available to the proposer (both to minimize cross-client communication and to allow proposer/builder separation in the future).

Note that `process_execution_payload` is NOT the same as `execute_payload` defined above; rather, it's a function that calls `execute_payload` but also does a few other local validations.

### Execution payload processing

#### `is_valid_gas_limit`

```python
def is_valid_gas_limit(payload: ExecutionPayload, parent: ExecutionPayloadHeader) -> bool:
    parent_gas_limit = parent.gas_limit

    # Check if the payload used too much gas
    if payload.gas_used > payload.gas_limit:
        return False

    # Check if the payload changed the gas limit too much
    if payload.gas_limit >= parent_gas_limit + parent_gas_limit // GAS_LIMIT_DENOMINATOR:
        return False
    if payload.gas_limit <= parent_gas_limit - parent_gas_limit // GAS_LIMIT_DENOMINATOR:
        return False

    # Check if the gas limit is at least the minimum gas limit
    if payload.gas_limit < MIN_GAS_LIMIT:
        return False

    return True
```

Enforces the same gas limit checking as the Ethereum PoW chain does today.

#### `process_execution_payload`

```python
def process_execution_payload(state: BeaconState, payload: ExecutionPayload, execution_engine: ExecutionEngine) -> None:
    # Verify consistency of the parent hash, block number, base fee per gas and gas limit
    # with respect to the previous execution payload header
    if is_merge_complete(state):
        assert payload.parent_hash == state.latest_execution_payload_header.block_hash
        assert payload.block_number == state.latest_execution_payload_header.block_number + uint64(1)
        assert is_valid_gas_limit(payload, state.latest_execution_payload_header)
    # Verify random
    assert payload.random == get_randao_mix(state, get_current_epoch(state))
    # Verify timestamp
    assert payload.timestamp == compute_timestamp_at_slot(state, state.slot)
    # Verify the execution payload is valid
    assert execution_engine.execute_payload(payload)
    # Cache execution payload header
    state.latest_execution_payload_header = ExecutionPayloadHeader(
        parent_hash=payload.parent_hash,
        coinbase=payload.coinbase,
        state_root=payload.state_root,
        receipt_root=payload.receipt_root,
        logs_bloom=payload.logs_bloom,
        random=payload.random,
        block_number=payload.block_number,
        gas_limit=payload.gas_limit,
        gas_used=payload.gas_used,
        timestamp=payload.timestamp,
        extra_data=payload.extra_data,
        base_fee_per_gas=payload.base_fee_per_gas,
        block_hash=payload.block_hash,
        transactions_root=hash_tree_root(payload.transactions),
    )
```

Verifies the consistency of the current execution block against the previous execution header stored in the beacon state. The validations that can be done using beacon chain state information alone are done here; everything "deep" is done by execution client validation.

## Testing

*Note*: The function `initialize_beacon_state_from_eth1` is modified for pure Merge testing only.
Modifications include:
1. Use `MERGE_FORK_VERSION` as the current fork version.
2. Utilize the Merge `BeaconBlockBody` when constructing the initial `latest_block_header`.
3. Initialize `latest_execution_payload_header`.
  If `execution_payload_header == ExecutionPayloadHeader()`, then the Merge has not yet occurred.
  Else, the Merge starts from genesis and the transition is incomplete.

```python
def initialize_beacon_state_from_eth1(eth1_block_hash: Bytes32,
                                      eth1_timestamp: uint64,
                                      deposits: Sequence[Deposit],
                                      execution_payload_header: ExecutionPayloadHeader=ExecutionPayloadHeader()
                                      ) -> BeaconState:
    fork = Fork(
        previous_version=MERGE_FORK_VERSION,  # [Modified in Merge] for testing only
        current_version=MERGE_FORK_VERSION,  # [Modified in Merge]
        epoch=GENESIS_EPOCH,
    )
    state = BeaconState(
        genesis_time=eth1_timestamp + GENESIS_DELAY,
        fork=fork,
        eth1_data=Eth1Data(block_hash=eth1_block_hash, deposit_count=uint64(len(deposits))),
        latest_block_header=BeaconBlockHeader(body_root=hash_tree_root(BeaconBlockBody())),
        randao_mixes=[eth1_block_hash] * EPOCHS_PER_HISTORICAL_VECTOR,  # Seed RANDAO with Eth1 entropy
    )

    # Process deposits
    leaves = list(map(lambda deposit: deposit.data, deposits))
    for index, deposit in enumerate(deposits):
        deposit_data_list = List[DepositData, 2**DEPOSIT_CONTRACT_TREE_DEPTH](*leaves[:index + 1])
        state.eth1_data.deposit_root = hash_tree_root(deposit_data_list)
        process_deposit(state, deposit)

    # Process activations
    for index, validator in enumerate(state.validators):
        balance = state.balances[index]
        validator.effective_balance = min(balance - balance % EFFECTIVE_BALANCE_INCREMENT, MAX_EFFECTIVE_BALANCE)
        if validator.effective_balance == MAX_EFFECTIVE_BALANCE:
            validator.activation_eligibility_epoch = GENESIS_EPOCH
            validator.activation_epoch = GENESIS_EPOCH

    # Set genesis validators root for domain separation and chain versioning
    state.genesis_validators_root = hash_tree_root(state.validators)

    # Fill in sync committees
    # Note: A duplicate committee is assigned for the current and next committee at genesis
    state.current_sync_committee = get_next_sync_committee(state)
    state.next_sync_committee = get_next_sync_committee(state)

    # [New in Merge] Initialize the execution payload header
    # If empty, will initialize a chain that has not yet gone through the Merge transition
    state.latest_execution_payload_header = execution_payload_header

    return state
```
