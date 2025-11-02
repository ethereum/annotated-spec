# Capella Beacon chain changes

This is an annotated version of the Capella beacon chain spec. 

## Table of contents

<!-- TOC -->
<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->

- [Introduction](#introduction)
- [Custom types](#custom-types)
  - [Domain types](#domain-types)
- [Preset](#preset)
  - [Max operations per block](#max-operations-per-block)
  - [Execution](#execution)
  - [Withdrawals processing](#withdrawals-processing)
- [Containers](#containers)
  - [New containers](#new-containers)
    - [`Withdrawal`](#withdrawal)
    - [`BLSToExecutionChange`](#blstoexecutionchange)
    - [`SignedBLSToExecutionChange`](#signedblstoexecutionchange)
    - [`HistoricalSummary`](#historicalsummary)
  - [Extended Containers](#extended-containers)
    - [`ExecutionPayload`](#executionpayload)
    - [`ExecutionPayloadHeader`](#executionpayloadheader)
    - [`BeaconBlockBody`](#beaconblockbody)
    - [`BeaconState`](#beaconstate)
- [Helpers](#helpers)
  - [Predicates](#predicates)
    - [`has_eth1_withdrawal_credential`](#has_eth1_withdrawal_credential)
    - [`is_fully_withdrawable_validator`](#is_fully_withdrawable_validator)
    - [`is_partially_withdrawable_validator`](#is_partially_withdrawable_validator)
- [Beacon chain state transition function](#beacon-chain-state-transition-function)
  - [Epoch processing](#epoch-processing)
    - [Historical summaries updates](#historical-summaries-updates)
  - [Block processing](#block-processing)
    - [Aside: how withdrawal processing works](#aside-how-withdrawal-processing-works)
    - [New `get_expected_withdrawals`](#new-get_expected_withdrawals)
    - [New `process_withdrawals`](#new-process_withdrawals)
    - [Modified `process_execution_payload`](#modified-process_execution_payload)
    - [Modified `process_operations`](#modified-process_operations)
    - [New `process_bls_to_execution_change`](#new-process_bls_to_execution_change)
- [Testing](#testing)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->
<!-- /TOC -->

## Introduction

Capella is a consensus-layer upgrade containing a number of features related to validator withdrawals. Including:

* **Automatic withdrawals of `withdrawable` validators**. It has been possible for a long time for validators to enter the `withdrawable` state. However, the functionality to actually withdraw validator balances has not yet been available. Capella, together with the Shanghai upgrade for the execution spec, finally adds the functionality that allows for withdrawals to process.
* **Partial withdrawals**: validators with `0x01` withdrawal credentials and balances above 32 ETH get their excess balance withdrawn to their address. A "sweeping" procedure cycles through the full set of validators and reaches each validator once every ~4-8 days.
* **Conversion to ETH-address-based withdrawals**. There are currently two types of withdrawal credentials that validators can have, defined by the first byte in the validator's `withdrawal_credentials`: `0x00` (withdrawal controlled by BLS pubkey) and `0x01` (the validator's balance withdraws to a specific ETH address). Capella adds a feature that lets `0x00` validators convert to `0x01`.

Capella also makes a small technical change to how historical block and state root summaries are stored, to make it slightly easier for a node to verify things about ancient history that it no longer stores (or did not download yet because it fast-synced).

## Custom types

We define the following Python custom types for type hinting and readability:

| Name | SSZ equivalent | Description |
| - | - | - |
| `WithdrawalIndex` | `uint64` | an index of a `Withdrawal` |

This is just a counter that stores the (global) index of the withdrawal. The first withdrawal that ever happens will have index 0, the second will have index 1, etc. This is not strictly necessary for the spec to work, but it was added for convenience, so that each withdrawal could have a clear "transaction ID" that can be used to refer to it (just hashing withdrawal contents would not work, as there may be multiple withdrawals with the exact same contents).

### Domain types

| Name | Value |
| - | - |
| `DOMAIN_BLS_TO_EXECUTION_CHANGE` | `DomainType('0x0A000000')` |

## Preset

### Max operations per block

| Name | Value |
| - | - |
| `MAX_BLS_TO_EXECUTION_CHANGES` | `2**4` (= 16) |

A maximum of 16 operations that convert a `0x00` (withdraw-by-BLS-key) account to a `0x01` (withdraw-to-ETH-address) account can be included in each block.

### Execution

| Name | Value | Description |
| - | - | - |
| `MAX_WITHDRAWALS_PER_PAYLOAD` | `uint64(2**4)` (= 16) | Maximum amount of withdrawals allowed in each payload |

### Withdrawals processing

| Name | Value |
| - | - |
| `MAX_VALIDATORS_PER_WITHDRAWALS_SWEEP` | `16384` (= 2**14 ) |

The sweeping mechanism walks through a maximum of this many validators to look for potential withdrawals.

## Containers

### New containers

#### `Withdrawal`

```python
class Withdrawal(Container):
    index: WithdrawalIndex
    validator_index: ValidatorIndex
    address: ExecutionAddress
    amount: Gwei
```

This is the object that contains a withdrawal. When the consensus layer detects that a validator is ready for withdrawing (using `is_fully_withdrawable_validator`), the validator's balance is withdrawn automatically.

Withdrawals are special because they move funds from the consensus layer to the execution layer, and so implementing them requires interaction between the two. There was a technical debate between two different ways to implement this interaction. One approach was to avoid including withdrawals in the body at all: the consensus portion of a block is processed first, it generates the list of withdrawals, and then that list is passed directly to the execution client and processed, without ever being serialized anywhere. The other approach is to include the list of withdrawals in the `ExecutionPayload` (the portion of the block that goes to the execution client). Consensus clients would check that the provided list is correctly generated, and execution clients would process those withdrawals.

We ultimately decided on the second approach, because it improves modularity and separation of concerns, and particularly it allows for execution validity and consensus validity to be verified at different times. This is very valuable for optimized node syncing procedures.

#### `BLSToExecutionChange`

```python
class BLSToExecutionChange(Container):
    validator_index: ValidatorIndex
    from_bls_pubkey: BLSPubkey
    to_execution_address: ExecutionAddress
```

This is the object that represents a validator's desire to upgrade from `0x00` (withdraw-by-BLS-key) to `0x01` (withdraw-to-ETH-address) withdrawal credentials. It needs to be signed (see `SignedBLSToExecutionChange` below) by the BLS key that is hashed in the original withdrawal credentials. The BLS key used to sign is the `from_bls_pubkey`, and we check that `hash(from_bls_pubkey)[1:] == validator.withdrawal_credentials[1:]` when processing a `BLSToExecutionChange` to verify that this is actually the key that was originally committed to.

#### `SignedBLSToExecutionChange`

```python
class SignedBLSToExecutionChange(Container):
    message: BLSToExecutionChange
    signature: BLSSignature
```

#### `HistoricalSummary`

```python
class HistoricalSummary(Container):
    """
    `HistoricalSummary` matches the components of the phase0 `HistoricalBatch`
    making the two hash_tree_root-compatible.
    """
    block_summary_root: Root
    state_summary_root: Root
```

See [the phase0 spec](../phase0/beacon-chain.md#slots_per_historical_root) for how historical roots worked pre-Capella. To summarize, after each 8192-slot period, we would append a hash of the last 8192 block roots and 8192 state roots to an ever-growing structure in the state that stores these hashes. This gives us a data structure that we could use to Merkle-prove historical facts about old history or state.

Here, we change it to store _two_ roots per period instead of one, storing the root of block roots and the root of state roots separately. This allows us to generate proofs about blocks without knowing anything about historical states, and to generate proofs about states without knowing anything about historical blocks. When the two were merged, a Merkle proof about one of the two structures would have to end with the Merkle root of the other structure because that's the final sister node in the path. Here, this requirement is removed. This is particularly valuable in the sync process, as it allows fast-synced nodes to download and verify batches of 8192 historical blocks without needing anyone to keep a separate data structure that tracks old states.

We replace the `historical_roots` object, which stores one root per period, with a `historical_summaries` object, which stores a `HistoricalSummary` containing two roots (the root-of-block-roots and root-of-state-roots) per period. Because we do not actually have the old roots-of-block-roots and roots-of-state-roots in the spec, we unfortunately cannot replace the old historical roots; hence, for now, we keep them around and have two separate structures, the older one frozen, but in a future fork we may well re-merge them.

### Extended Containers

#### `ExecutionPayload`

```python
class ExecutionPayload(Container):
    # Execution block header fields
    parent_hash: Hash32
    fee_recipient: ExecutionAddress  # 'beneficiary' in the yellow paper
    state_root: Bytes32
    receipts_root: Bytes32
    logs_bloom: ByteVector[BYTES_PER_LOGS_BLOOM]
    prev_randao: Bytes32  # 'difficulty' in the yellow paper
    block_number: uint64  # 'number' in the yellow paper
    gas_limit: uint64
    gas_used: uint64
    timestamp: uint64
    extra_data: ByteList[MAX_EXTRA_DATA_BYTES]
    base_fee_per_gas: uint256
    # Extra payload fields
    block_hash: Hash32  # Hash of execution block
    transactions: List[Transaction, MAX_TRANSACTIONS_PER_PAYLOAD]
    withdrawals: List[Withdrawal, MAX_WITHDRAWALS_PER_PAYLOAD]  # [New in Capella]
```

#### `ExecutionPayloadHeader`

```python
class ExecutionPayloadHeader(Container):
    # Execution block header fields
    parent_hash: Hash32
    fee_recipient: ExecutionAddress
    state_root: Bytes32
    receipts_root: Bytes32
    logs_bloom: ByteVector[BYTES_PER_LOGS_BLOOM]
    prev_randao: Bytes32
    block_number: uint64
    gas_limit: uint64
    gas_used: uint64
    timestamp: uint64
    extra_data: ByteList[MAX_EXTRA_DATA_BYTES]
    base_fee_per_gas: uint256
    # Extra payload fields
    block_hash: Hash32  # Hash of execution block
    transactions_root: Root
    withdrawals_root: Root  # [New in Capella]
```

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
    execution_payload: ExecutionPayload
    # Capella operations
    bls_to_execution_changes: List[SignedBLSToExecutionChange, MAX_BLS_TO_EXECUTION_CHANGES]  # [New in Capella]
```

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
    historical_roots: List[Root, HISTORICAL_ROOTS_LIMIT]  # Frozen in Capella, replaced by historical_summaries
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
    latest_execution_payload_header: ExecutionPayloadHeader  # [Modified in Capella]
    # Withdrawals
    next_withdrawal_index: WithdrawalIndex  # [New in Capella]
    next_withdrawal_validator_index: ValidatorIndex  # [New in Capella]
    # Deep history valid from Capella onwards
    historical_summaries: List[HistoricalSummary, HISTORICAL_ROOTS_LIMIT]  # [New in Capella]
```

## Helpers

### Predicates

#### `has_eth1_withdrawal_credential`

```python
def has_eth1_withdrawal_credential(validator: Validator) -> bool:
    """
    Check if ``validator`` has an 0x01 prefixed "eth1" withdrawal credential.
    """
    return validator.withdrawal_credentials[:1] == ETH1_ADDRESS_WITHDRAWAL_PREFIX
```

#### `is_fully_withdrawable_validator`

```python
def is_fully_withdrawable_validator(validator: Validator, balance: Gwei, epoch: Epoch) -> bool:
    """
    Check if ``validator`` is fully withdrawable.
    """
    return (
        has_eth1_withdrawal_credential(validator)
        and validator.withdrawable_epoch <= epoch
        and balance > 0
    )
```

If a validator with a `0x01` withdrawal credential has reached their withdrawability epoch and has more than 0 ETH, their total balance is eligible to be automatically withdrawn to their specified withdrawal address.

#### `is_partially_withdrawable_validator`

```python
def is_partially_withdrawable_validator(validator: Validator, balance: Gwei) -> bool:
    """
    Check if ``validator`` is partially withdrawable.
    """
    has_max_effective_balance = validator.effective_balance == MAX_EFFECTIVE_BALANCE
    has_excess_balance = balance > MAX_EFFECTIVE_BALANCE
    return has_eth1_withdrawal_credential(validator) and has_max_effective_balance and has_excess_balance
```

If a validator with a `0x01` withdrawal credential has more than 32 ETH, their "excess" ETH is eligible to be automatically withdrawn to their specified withdrawal address.

## Beacon chain state transition function

### Epoch processing

*Note*: The function `process_historical_summaries_update` replaces `process_historical_roots_update` in Bellatrix.

```python
def process_epoch(state: BeaconState) -> None:
    process_justification_and_finalization(state)
    process_inactivity_updates(state)
    process_rewards_and_penalties(state)
    process_registry_updates(state)
    process_slashings(state)
    process_eth1_data_reset(state)
    process_effective_balance_updates(state)
    process_slashings_reset(state)
    process_randao_mixes_reset(state)
    process_historical_summaries_update(state)  # [Modified in Capella]
    process_participation_flag_updates(state)
    process_sync_committee_updates(state)
```

#### Historical summaries updates

```python
def process_historical_summaries_update(state: BeaconState) -> None:
    # Set historical block root accumulator.
    next_epoch = Epoch(get_current_epoch(state) + 1)
    if next_epoch % (SLOTS_PER_HISTORICAL_ROOT // SLOTS_PER_EPOCH) == 0:
        historical_summary = HistoricalSummary(
            block_summary_root=hash_tree_root(state.block_roots),
            state_summary_root=hash_tree_root(state.state_roots),
        )
        state.historical_summaries.append(historical_summary)
```

Extends the historical summaries list. Similar to the `historical_batch`-related logic in the [Final updates section](https://github.com/ethereum/annotated-spec/blob/master/phase0/beacon-chain.md#final-updates) of the pre-Capella spec.

### Block processing

```python
def process_block(state: BeaconState, block: BeaconBlock) -> None:
    process_block_header(state, block)
    if is_execution_enabled(state, block.body):
        process_withdrawals(state, block.body.execution_payload)  # [New in Capella]
        process_execution_payload(state, block.body.execution_payload, EXECUTION_ENGINE)  # [Modified in Capella]
    process_randao(state, block.body)
    process_eth1_data(state, block.body)
    process_operations(state, block.body)  # [Modified in Capella]
    process_sync_aggregate(state, block.body.sync_aggregate)
```

#### Aside: how withdrawal processing works

_This describes the logic implemented in `get_expected_withdrawals` and `process_withdrawals` below, and the logic on the execution client side ([EIP-4895](https://eips.ethereum.org/EIPS/eip-4895)) to accept the withdrawals._

To detect accounts eligible for (full or partial) withdrawals, a "sweeping" process cycles through the entire list of validators. The current location of the sweep is stored in `state.next_withdrawal_validator_index`; during the processing of a block, the sweep walks through the validator list starting from that point, going back to the start of the list if it reaches the end.

During one block, the sweep continues until it either (i) sweeps through `MAX_VALIDATORS_PER_WITHDRAWALS_SWEEP` validators, or, more commonly, (ii) discovers enough withdrawals to completely fill the `withdrawals` list and terminates early. The sweep checks for two types of withdrawable accounts: **full withdrawals**, where a validator has ETH and is `withdrawable`, and **partial withdrawals**, where a validator has more than 32 ETH, and so the excess can be withdrawn. In both cases, an additional condition is enforced that the validator must have a `0x01` (withdraw-to-ETH-address) withdrawal credential, which ensures that we know what ETH address the validator's (either total or excess) funds should be withdrawn to.

If the sweep discovers a validator that is eligible for a withdrawal, it constructs a `Withdrawal` object of the appropriate type, and adds it to the list. Once the sweep is complete, the `process_withdrawals` function first checks that the _generated_ list of withdrawals equals the _declared_ list of withdrawals in the `ExecutionPayload`, and then processes the withdrawals, decreasing the balances of withdrawn validators by the amount in the `Withdrawal` (in practice, partial withdrawals decrease to 32 ETH, and full withdrawals decrease to 0 ETH).

On the execution side, [EIP-4895](https://eips.ethereum.org/EIPS/eip-4895) introduces the rule that after all transactions are processed, the balances of ETH addresses mentioned in withdrawals get increased by the amounts specified by those withdrawals.

#### New `get_expected_withdrawals`

```python
def get_expected_withdrawals(state: BeaconState) -> Sequence[Withdrawal]:
    epoch = get_current_epoch(state)
    withdrawal_index = state.next_withdrawal_index
    validator_index = state.next_withdrawal_validator_index
    withdrawals: List[Withdrawal] = []
    bound = min(len(state.validators), MAX_VALIDATORS_PER_WITHDRAWALS_SWEEP)
    for _ in range(bound):
        validator = state.validators[validator_index]
        balance = state.balances[validator_index]
        if is_fully_withdrawable_validator(validator, balance, epoch):
            withdrawals.append(Withdrawal(
                index=withdrawal_index,
                validator_index=validator_index,
                address=ExecutionAddress(validator.withdrawal_credentials[12:]),
                amount=balance,
            ))
            withdrawal_index += WithdrawalIndex(1)
        elif is_partially_withdrawable_validator(validator, balance):
            withdrawals.append(Withdrawal(
                index=withdrawal_index,
                validator_index=validator_index,
                address=ExecutionAddress(validator.withdrawal_credentials[12:]),
                amount=balance - MAX_EFFECTIVE_BALANCE,
            ))
            withdrawal_index += WithdrawalIndex(1)
        if len(withdrawals) == MAX_WITHDRAWALS_PER_PAYLOAD:
            break
        validator_index = ValidatorIndex((validator_index + 1) % len(state.validators))
    return withdrawals
```

#### New `process_withdrawals`

```python
def process_withdrawals(state: BeaconState, payload: ExecutionPayload) -> None:
    expected_withdrawals = get_expected_withdrawals(state)
    assert payload.withdrawals == expected_withdrawals

    for withdrawal in expected_withdrawals:
        decrease_balance(state, withdrawal.validator_index, withdrawal.amount)

    # Update the next withdrawal index if this block contained withdrawals
    if len(expected_withdrawals) != 0:
        latest_withdrawal = expected_withdrawals[-1]
        state.next_withdrawal_index = WithdrawalIndex(latest_withdrawal.index + 1)

    # Update the next validator index to start the next withdrawal sweep
    if len(expected_withdrawals) == MAX_WITHDRAWALS_PER_PAYLOAD:
        # Next sweep starts after the latest withdrawal's validator index
        next_validator_index = ValidatorIndex((expected_withdrawals[-1].validator_index + 1) % len(state.validators))
        state.next_withdrawal_validator_index = next_validator_index
    else:
        # Advance sweep by the max length of the sweep if there was not a full set of withdrawals
        next_index = state.next_withdrawal_validator_index + MAX_VALIDATORS_PER_WITHDRAWALS_SWEEP
        next_validator_index = ValidatorIndex(next_index % len(state.validators))
        state.next_withdrawal_validator_index = next_validator_index
```

The key things that we are doing here are (i) checking that the list of expected withdrawals generated by running the sweep (`get_expected_withdrawals`) is the same as the list in the payload, and (ii) actually processing those withdrawals.  

#### Modified `process_execution_payload`

*Note*: The function `process_execution_payload` is modified to use the new `ExecutionPayloadHeader` type.

```python
def process_execution_payload(state: BeaconState, payload: ExecutionPayload, execution_engine: ExecutionEngine) -> None:
    # [Modified in Capella] Removed `is_merge_transition_complete` check in Capella
    # Verify consistency of the parent hash with respect to the previous execution payload header
    assert payload.parent_hash == state.latest_execution_payload_header.block_hash
    # Verify prev_randao
    assert payload.prev_randao == get_randao_mix(state, get_current_epoch(state))
    # Verify timestamp
    assert payload.timestamp == compute_timestamp_at_slot(state, state.slot)
    # Verify the execution payload is valid
    assert execution_engine.verify_and_notify_new_payload(NewPayloadRequest(execution_payload=payload))
    # Cache execution payload header
    state.latest_execution_payload_header = ExecutionPayloadHeader(
        parent_hash=payload.parent_hash,
        fee_recipient=payload.fee_recipient,
        state_root=payload.state_root,
        receipts_root=payload.receipts_root,
        logs_bloom=payload.logs_bloom,
        prev_randao=payload.prev_randao,
        block_number=payload.block_number,
        gas_limit=payload.gas_limit,
        gas_used=payload.gas_used,
        timestamp=payload.timestamp,
        extra_data=payload.extra_data,
        base_fee_per_gas=payload.base_fee_per_gas,
        block_hash=payload.block_hash,
        transactions_root=hash_tree_root(payload.transactions),
        withdrawals_root=hash_tree_root(payload.withdrawals),  # [New in Capella]
    )
```

#### Modified `process_operations`

*Note*: The function `process_operations` is modified to process `BLSToExecutionChange` operations included in the block.

```python
def process_operations(state: BeaconState, body: BeaconBlockBody) -> None:
    # Verify that outstanding deposits are processed up to the maximum number of deposits
    assert len(body.deposits) == min(MAX_DEPOSITS, state.eth1_data.deposit_count - state.eth1_deposit_index)

    def for_ops(operations: Sequence[Any], fn: Callable[[BeaconState, Any], None]) -> None:
        for operation in operations:
            fn(state, operation)

    for_ops(body.proposer_slashings, process_proposer_slashing)
    for_ops(body.attester_slashings, process_attester_slashing)
    for_ops(body.attestations, process_attestation)
    for_ops(body.deposits, process_deposit)
    for_ops(body.voluntary_exits, process_voluntary_exit)
    for_ops(body.bls_to_execution_changes, process_bls_to_execution_change)  # [New in Capella]
```

#### New `process_bls_to_execution_change`

```python
def process_bls_to_execution_change(state: BeaconState,
                                    signed_address_change: SignedBLSToExecutionChange) -> None:
    address_change = signed_address_change.message

    assert address_change.validator_index < len(state.validators)

    validator = state.validators[address_change.validator_index]

    assert validator.withdrawal_credentials[:1] == BLS_WITHDRAWAL_PREFIX
    assert validator.withdrawal_credentials[1:] == hash(address_change.from_bls_pubkey)[1:]

    # Fork-agnostic domain since address changes are valid across forks
    domain = compute_domain(DOMAIN_BLS_TO_EXECUTION_CHANGE, genesis_validators_root=state.genesis_validators_root)
    signing_root = compute_signing_root(address_change, domain)
    assert bls.Verify(address_change.from_bls_pubkey, signing_root, signed_address_change.signature)

    validator.withdrawal_credentials = (
        ETH1_ADDRESS_WITHDRAWAL_PREFIX
        + b'\x00' * 11
        + address_change.to_execution_address
    )
```

Processes requests to change a validator's withdrawal credentials from being a BLS key to being an eth1 address.

## Testing

*Note*: The function `initialize_beacon_state_from_eth1` is modified for pure Capella testing only.
Modifications include:
1. Use `CAPELLA_FORK_VERSION` as the previous and current fork version.
2. Utilize the Capella `BeaconBlockBody` when constructing the initial `latest_block_header`.

```python
def initialize_beacon_state_from_eth1(eth1_block_hash: Hash32,
                                      eth1_timestamp: uint64,
                                      deposits: Sequence[Deposit],
                                      execution_payload_header: ExecutionPayloadHeader=ExecutionPayloadHeader()
                                      ) -> BeaconState:
    fork = Fork(
        previous_version=CAPELLA_FORK_VERSION,  # [Modified in Capella] for testing only
        current_version=CAPELLA_FORK_VERSION,  # [Modified in Capella]
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

    # Initialize the execution payload header
    state.latest_execution_payload_header = execution_payload_header

    return state
```
