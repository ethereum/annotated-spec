# Bellatrix -- The Beacon Chain

<!-- mdformat-toc start --slug=github --no-anchors --maxlevel=6 --minlevel=2 -->

- [Introduction](#introduction)
- [Custom types](#custom-types)
- [Preset](#preset)
  - [Rewards and penalties](#rewards-and-penalties)
  - [Execution](#execution)
- [Configuration](#configuration)
  - [Transition settings](#transition-settings)
- [Containers](#containers)
  - [Modified containers](#modified-containers)
    - [`BeaconBlockBody`](#beaconblockbody)
    - [`BeaconState`](#beaconstate)
  - [New containers](#new-containers)
    - [`ExecutionPayload`](#executionpayload)
    - [`ExecutionPayloadHeader`](#executionpayloadheader)
- [Helper functions](#helper-functions)
  - [Predicates](#predicates)
    - [`is_merge_transition_complete`](#is_merge_transition_complete)
    - [`is_merge_transition_block`](#is_merge_transition_block)
    - [`is_execution_enabled`](#is_execution_enabled)
  - [Beacon state accessors](#beacon-state-accessors)
    - [Modified `get_inactivity_penalty_deltas`](#modified-get_inactivity_penalty_deltas)
  - [Beacon state mutators](#beacon-state-mutators)
    - [Modified `slash_validator`](#modified-slash_validator)
- [Beacon chain state transition function](#beacon-chain-state-transition-function)
  - [Execution engine](#execution-engine)
    - [Request data](#request-data)
      - [`NewPayloadRequest`](#newpayloadrequest)
    - [Engine APIs](#engine-apis)
    - [`notify_new_payload`](#notify_new_payload)
    - [`is_valid_block_hash`](#is_valid_block_hash)
    - [`verify_and_notify_new_payload`](#verify_and_notify_new_payload)
  - [Block processing](#block-processing)
    - [Execution payload](#execution-payload)
      - [`process_execution_payload`](#process_execution_payload)
  - [Epoch processing](#epoch-processing)
    - [Slashings](#slashings)

<!-- mdformat-toc end -->

## Introduction

This upgrade adds transaction execution to the beacon chain as part of Bellatrix
upgrade.

Additionally, this upgrade introduces the following minor changes:

- Penalty parameter updates to their planned maximally punitive values

<!-- NOTES-BEGIN -->

The Merge is the event in which the Ethereum proof of work chain is deprecated, and the beacon chain (the Ethereum proof of stake chain) takes over as the chain that Ethereum is running on. To simplify the Merge and allow it to happen faster, the Merge is designed via a **block-inside-a-block structure**: the Ethereum PoW chain appears to continue, except past a certain transition point (i) the PoW nonces are no longer required to be valid, and (ii) the Ethereum PoW blocks, from then on referred to as **execution blocks**, are required to be embedded inside of beacon chain blocks.

![](https://i.imgur.com/udZlkQr.png)

The timing of the merge is parametrized by two thresholds:

* The `MERGE_FORK_EPOCH`, the epoch at which the beacon chain includes the post-merge features (mainly, the ability to contain execution blocks), and so the merge becomes possible
* The `TERMINAL_TOTAL_DIFFICULTY`, the total PoW difficulty such that a block those total difficulty is `>= TERMINAL_TOTAL_DIFFICULTY` (but whose parent is below the threshold) is a terminal block, so its children and further descendants do not require PoW and must be part of beacon chain blocks.

Total difficulty is used as a threshold instead of block height (which forks normally use) for security: it prevents an attacker from privately creating a chain with lower difficulty but higher block height and then colluding with a single beacon proposer to get it included first. Using TD ensures that the winner of the PoW fork choice becomes eligible for inclusion into the beacon chain before any other block.

The parameters are expected to be set such that the beacon chain reaches the `MERGE_FORK_EPOCH` before the PoW chain reaches the `TERMINAL_TOTAL_DIFFICULTY`. Hence, by the time the PoW chain gets a terminal block, which can only have an **embedded block** inside the beacon chain as a child, the beacon chain will be ready to accept embedded blocks. In the unlikely case that the events end up happening in the other order (only possible if miners attack the transition by adding a _huge_ amount of new hashpower), Ethereum will simply be offline and not generate new blocks until the `MERGE_FORK_EPOCH` is reached.

## Custom types

*Note*: The `Transaction` type is a stub which is not final.

| Name               | SSZ equivalent                        | Description                                                                                                                                       |
| ------------------ | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Transaction`      | `ByteList[MAX_BYTES_PER_TRANSACTION]` | either a [typed transaction envelope](https://eips.ethereum.org/EIPS/eip-2718#opaque-byte-array-rather-than-an-rlp-array) or a legacy transaction |
| `ExecutionAddress` | `Bytes20`                             | Address of account on the execution layer                                                                                                         |

<!-- NOTES-BEGIN -->

The beacon chain uses [SSZ](https://github.com/ethereum/consensus-specs/blob/dev/ssz/simple-serialize.md) for serialization and SSZ + SHA256 for hashing, and the execution chain uses [RLP](https://eth.wiki/fundamentals/rlp) for serialization, and the keccak hash of the RLP serialized form for hashing. In the long term, it's a desired goal to move everything to SSZ. For now, however, because of the desire to finish the merge quickly, most of the execution chain remains RLP-based. Specifically, execution _blocks_ are stored in SSZ form, but the _transactions_ inside them are encoded with RLP, and so to software that only understands SSZ they are presented as "opaque" byte arrays. Note also that the `parent_hash` of an execution block is expected to match the keccak hash of the RLP-serialized form of the previous execution block.

## Preset

### Rewards and penalties

Bellatrix updates a few configuration values to move penalty parameters to their
final, maximum security values.

*Note*: The spec does *not* override previous configuration values but instead
creates new values and replaces usage throughout.

| Name                                         | Value                          |
| -------------------------------------------- | ------------------------------ |
| `INACTIVITY_PENALTY_QUOTIENT_BELLATRIX`      | `uint64(2**24)` (= 16,777,216) |
| `MIN_SLASHING_PENALTY_QUOTIENT_BELLATRIX`    | `uint64(2**5)` (= 32)          |
| `PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX` | `uint64(3)`                    |

### Execution

| Name                           | Value                             |
| ------------------------------ | --------------------------------- |
| `MAX_BYTES_PER_TRANSACTION`    | `uint64(2**30)` (= 1,073,741,824) |
| `MAX_TRANSACTIONS_PER_PAYLOAD` | `uint64(2**20)` (= 1,048,576)     |
| `BYTES_PER_LOGS_BLOOM`         | `uint64(2**8)` (= 256)            |
| `MAX_EXTRA_DATA_BYTES`         | `2**5` (= 32)                     |

<!-- NOTES-BEGIN -->

The `GAS_LIMIT_DENOMINATOR` is the inverse of the max fraction by which a block's gas limit can change per block. This is identical to the gas limit voting mechanism on the execution chain. The max bytes per transaction and max transactions per payload are expected to be changed; the intent is for the limits to merely be there because the SSZ structures require _some_ max depth, and the execution chain gas limit is intended to set the actual limits.

## Configuration

### Transition settings

| Name                                   | Value                                                |
| -------------------------------------- | ---------------------------------------------------- |
| `TERMINAL_TOTAL_DIFFICULTY`            | `58750000000000000000000` (Estimated: Sept 15, 2022) |
| `TERMINAL_BLOCK_HASH`                  | `Hash32()`                                           |
| `TERMINAL_BLOCK_HASH_ACTIVATION_EPOCH` | `FAR_FUTURE_EPOCH`                                   |

<!-- NOTES-BEGIN -->

The `TERMINAL_BLOCK_HASH` feature is an emergency override mechanism. If PoW miners attempt to cause chaos on the chain via 51% attacks before the merge, the community can react by setting the `TERMINAL_BLOCK_HASH` to choose a specific terminal block, and the `MERGE_FORK_EPOCH` to some specific value in the future (ideally not too far in the future). The Ethereum chain would make no progress between this point and the `MERGE_FORK_EPOCH`, but after that point it would proceed smoothly embedded inside the beacon chain.

Note that if the `TERMINAL_BLOCK_HASH` is set to any value that is clearly not a valid hash output (eg. zero), this means that there is no valid block that could trigger the hash-based validity condition, so a block reaching the `TERMINAL_TOTAL_DIFFICULTY` is the only option.

## Containers

### Modified containers

#### `BeaconBlockBody`

```python
class BeaconBlockBody(Container):
    randao_reveal: BLSSignature
    eth1_data: Eth1Data
    graffiti: Bytes32
    proposer_slashings: List[ProposerSlashing, MAX_PROPOSER_SLASHINGS]
    attester_slashings: List[AttesterSlashing, MAX_ATTESTER_SLASHINGS]
    attestations: List[Attestation, MAX_ATTESTATIONS]
    deposits: List[Deposit, MAX_DEPOSITS]
    voluntary_exits: List[SignedVoluntaryExit, MAX_VOLUNTARY_EXITS]
    sync_aggregate: SyncAggregate
    # [New in Bellatrix]
    execution_payload: ExecutionPayload
```

#### `BeaconState`

```python
class BeaconState(Container):
    genesis_time: uint64
    genesis_validators_root: Root
    slot: Slot
    fork: Fork
    latest_block_header: BeaconBlockHeader
    block_roots: Vector[Root, SLOTS_PER_HISTORICAL_ROOT]
    state_roots: Vector[Root, SLOTS_PER_HISTORICAL_ROOT]
    historical_roots: List[Root, HISTORICAL_ROOTS_LIMIT]
    eth1_data: Eth1Data
    eth1_data_votes: List[Eth1Data, EPOCHS_PER_ETH1_VOTING_PERIOD * SLOTS_PER_EPOCH]
    eth1_deposit_index: uint64
    validators: List[Validator, VALIDATOR_REGISTRY_LIMIT]
    balances: List[Gwei, VALIDATOR_REGISTRY_LIMIT]
    randao_mixes: Vector[Bytes32, EPOCHS_PER_HISTORICAL_VECTOR]
    slashings: Vector[Gwei, EPOCHS_PER_SLASHINGS_VECTOR]
    previous_epoch_participation: List[ParticipationFlags, VALIDATOR_REGISTRY_LIMIT]
    current_epoch_participation: List[ParticipationFlags, VALIDATOR_REGISTRY_LIMIT]
    justification_bits: Bitvector[JUSTIFICATION_BITS_LENGTH]
    previous_justified_checkpoint: Checkpoint
    current_justified_checkpoint: Checkpoint
    finalized_checkpoint: Checkpoint
    inactivity_scores: List[uint64, VALIDATOR_REGISTRY_LIMIT]
    current_sync_committee: SyncCommittee
    next_sync_committee: SyncCommittee
    # [New in Bellatrix]
    latest_execution_payload_header: ExecutionPayloadHeader
```

<!-- NOTES-BEGIN -->

Extend the `BeaconState` by adding the `ExecutionPayloadHeader` of the most recently included execution block. This contains data like execution block hash, post-state root, gas limit, etc, that the next execution block will need to be checked against.

### New containers

#### `ExecutionPayload`

*Note*: `fee_recipient`, `prev_randao`, and `block_number` correspond to
`beneficiary`, `difficulty`, and `number` in
[the yellow paper](https://ethereum.github.io/yellowpaper/paper.pdf),
respectively.

```python
class ExecutionPayload(Container):
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
    block_hash: Hash32
    transactions: List[Transaction, MAX_TRANSACTIONS_PER_PAYLOAD]
```

<!-- NOTES-BEGIN -->

The data structure that stores the execution block. Note that the execution block hash is part of the structure and not computed from it. Verification of this hash is done by execution clients (formerly known as "eth1 clients"; eg. Geth, Nethermind, Erigon, Besu) when the execution block is passed to them for verification.

#### `ExecutionPayloadHeader`

*Note*: `block_hash` is the hash of the execution block.

```python
class ExecutionPayloadHeader(Container):
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
    block_hash: Hash32
    transactions_root: Root
```

<!-- NOTES-BEGIN -->

Same structure as above, except the transaction list is replaced by its SSZ hash tree root.

## Helper functions

### Predicates

#### `is_merge_transition_complete`

```python
def is_merge_transition_complete(state: BeaconState) -> bool:
    return state.latest_execution_payload_header != ExecutionPayloadHeader()
```

<!-- NOTES-BEGIN -->

Returns whether or not the merge "has already happened", defined by whether or not there has already been an embedded execution block inside the beacon chain (if there has, its header is saved in `state.latest_execution_payload_header`).

#### `is_merge_transition_block`

```python
def is_merge_transition_block(state: BeaconState, body: BeaconBlockBody) -> bool:
    return not is_merge_transition_complete(state) and body.execution_payload != ExecutionPayload()
```

<!-- NOTES-BEGIN -->

Returns whether or not a given block is the first block that contains an embedded execution block.

#### `is_execution_enabled`

```python
def is_execution_enabled(state: BeaconState, body: BeaconBlockBody) -> bool:
    return is_merge_transition_block(state, body) or is_merge_transition_complete(state)
```

### Beacon state accessors

#### Modified `get_inactivity_penalty_deltas`

*Note*: The function `get_inactivity_penalty_deltas` is modified to use
`INACTIVITY_PENALTY_QUOTIENT_BELLATRIX`.

```python
def get_inactivity_penalty_deltas(state: BeaconState) -> Tuple[Sequence[Gwei], Sequence[Gwei]]:
    """
    Return the inactivity penalty deltas by considering timely target participation flags and inactivity scores.
    """
    rewards = [Gwei(0) for _ in range(len(state.validators))]
    penalties = [Gwei(0) for _ in range(len(state.validators))]
    previous_epoch = get_previous_epoch(state)
    matching_target_indices = get_unslashed_participating_indices(
        state, TIMELY_TARGET_FLAG_INDEX, previous_epoch
    )
    for index in get_eligible_validator_indices(state):
        if index not in matching_target_indices:
            penalty_numerator = (
                state.validators[index].effective_balance * state.inactivity_scores[index]
            )
            # [Modified in Bellatrix]
            penalty_denominator = INACTIVITY_SCORE_BIAS * INACTIVITY_PENALTY_QUOTIENT_BELLATRIX
            penalties[index] += Gwei(penalty_numerator // penalty_denominator)
    return rewards, penalties
```

### Beacon state mutators

#### Modified `slash_validator`

*Note*: The function `slash_validator` is modified to use
`MIN_SLASHING_PENALTY_QUOTIENT_BELLATRIX`.

```python
def slash_validator(
    state: BeaconState, slashed_index: ValidatorIndex, whistleblower_index: ValidatorIndex = None
) -> None:
    """
    Slash the validator with index ``slashed_index``.
    """
    epoch = get_current_epoch(state)
    initiate_validator_exit(state, slashed_index)
    validator = state.validators[slashed_index]
    validator.slashed = True
    validator.withdrawable_epoch = max(
        validator.withdrawable_epoch, Epoch(epoch + EPOCHS_PER_SLASHINGS_VECTOR)
    )
    state.slashings[epoch % EPOCHS_PER_SLASHINGS_VECTOR] += validator.effective_balance
    # [Modified in Bellatrix]
    slashing_penalty = validator.effective_balance // MIN_SLASHING_PENALTY_QUOTIENT_BELLATRIX
    decrease_balance(state, slashed_index, slashing_penalty)

    # Apply proposer and whistleblower rewards
    proposer_index = get_beacon_proposer_index(state)
    if whistleblower_index is None:
        whistleblower_index = proposer_index
    whistleblower_reward = Gwei(validator.effective_balance // WHISTLEBLOWER_REWARD_QUOTIENT)
    proposer_reward = Gwei(whistleblower_reward * PROPOSER_WEIGHT // WEIGHT_DENOMINATOR)
    increase_balance(state, proposer_index, proposer_reward)
    increase_balance(state, whistleblower_index, Gwei(whistleblower_reward - proposer_reward))
```

## Beacon chain state transition function

### Execution engine

<!-- NOTES-BEGIN -->

This function calls the execution client (formerly known as an "eth1 client"; eg. Geth, Nethermind, Erigon, Besu) to validate the execution block in the `execution_payload`. The payload contains the `parent_hash`, so the execution engine knows what pre-state to verify the execution block off of. Note that there is implied state (the execution pre-state) that is stored by the execution client and that the execution client is expected to use to validate the block. The function can be considered quasi-pure in that although it does not pass the pre-state in as an explicit argument, the `execution_payload.parent_hash` is nevertheless cryptographically linked to a unique pre-state.

Under normal operation, there is no possibility that the pre-state is unavailable, because a beacon block would only be validated if all of its ancestors have been validated, and that ensures that the previous execution blocks were validated and their post-state (and hence the latest block's pre-state) would already be computed. The only exception to this logic is the _first_ embedded execution block, whose parent (the terminal PoW block) is not in the beacon chain. If the terminal PoW block is unavailable, the beacon chain client should wait until the terminal PoW block becomes available before accepting the beacon block . Importantly, the beacon chain client should NOT "conclusively reject" a beacon block whose embedded execution block's parent is an unavailable terminal PoW block, because the terminal PoW block could become available very soon in the future. 

#### Request data

##### `NewPayloadRequest`

```python
@dataclass
class NewPayloadRequest(object):
    execution_payload: ExecutionPayload
```

#### Engine APIs

The implementation-dependent `ExecutionEngine` protocol encapsulates the
execution sub-system logic via:

- a state object `self.execution_state` of type `ExecutionState`
- a notification function `self.notify_new_payload` which may apply changes to
  the `self.execution_state`

The body of these functions are implementation dependent. The Engine API may be
used to implement this and similarly defined functions via an external execution
engine.

#### `notify_new_payload`

`notify_new_payload` is a function accessed through the `EXECUTION_ENGINE`
module which instantiates the `ExecutionEngine` protocol.

```python
def notify_new_payload(self: ExecutionEngine, execution_payload: ExecutionPayload) -> bool:
    """
    Return ``True`` if and only if ``execution_payload`` is valid with respect to ``self.execution_state``.
    """
    ...
```

#### `is_valid_block_hash`

```python
def is_valid_block_hash(self: ExecutionEngine, execution_payload: ExecutionPayload) -> bool:
    """
    Return ``True`` if and only if ``execution_payload.block_hash`` is computed correctly.
    """
    ...
```

#### `verify_and_notify_new_payload`

```python
def verify_and_notify_new_payload(
    self: ExecutionEngine, new_payload_request: NewPayloadRequest
) -> bool:
    """
    Return ``True`` if and only if ``new_payload_request`` is valid with respect to ``self.execution_state``.
    """
    execution_payload = new_payload_request.execution_payload

    if b"" in execution_payload.transactions:
        return False

    if not self.is_valid_block_hash(execution_payload):
        return False

    if not self.notify_new_payload(execution_payload):
        return False

    return True
```

### Block processing

*Note*: The call to the `process_execution_payload` must happen before the call
to the `process_randao` as the former depends on the `randao_mix` computed with
the reveal of the previous block.

```python
def process_block(state: BeaconState, block: BeaconBlock) -> None:
    process_block_header(state, block)
    if is_execution_enabled(state, block.body):
        # [New in Bellatrix]
        process_execution_payload(state, block.body, EXECUTION_ENGINE)
    process_randao(state, block.body)
    process_eth1_data(state, block.body)
    process_operations(state, block.body)
    process_sync_aggregate(state, block.body.sync_aggregate)
```

<!-- NOTES-BEGIN -->

The main addition to the `process_block` function is the `process_execution_payload` function. This function is computed against the previous `randao` because we want it to be possible to construct an execution block without having secret information only available to the proposer (both to minimize cross-client communication and to allow proposer/builder separation in the future).

Note that `process_execution_payload` is NOT the same as `execute_payload` defined above; rather, it's a function that calls `execute_payload` but also does a few other local validations.

#### Execution payload

##### `process_execution_payload`

```python
def process_execution_payload(
    state: BeaconState, body: BeaconBlockBody, execution_engine: ExecutionEngine
) -> None:
    payload = body.execution_payload

    # Verify consistency of the parent hash with respect to the previous execution payload header
    if is_merge_transition_complete(state):
        assert payload.parent_hash == state.latest_execution_payload_header.block_hash
    # Verify prev_randao
    assert payload.prev_randao == get_randao_mix(state, get_current_epoch(state))
    # Verify timestamp
    assert payload.timestamp == compute_time_at_slot(state, state.slot)
    # Verify the execution payload is valid
    assert execution_engine.verify_and_notify_new_payload(
        NewPayloadRequest(execution_payload=payload)
    )
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
    )
```

<!-- NOTES-BEGIN -->

Verifies the consistency of the current execution block against the previous execution header stored in the beacon state. The validations that can be done using beacon chain state information alone are done here; everything "deep" is done by execution client validation.
### Epoch processing

#### Slashings

*Note*: The function `process_slashings` is modified to use
`PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX`.

```python
def process_slashings(state: BeaconState) -> None:
    epoch = get_current_epoch(state)
    total_balance = get_total_active_balance(state)
    adjusted_total_slashing_balance = min(
        sum(state.slashings)
        # [Modified in Bellatrix]
        * PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX,
        total_balance,
    )
    for index, validator in enumerate(state.validators):
        if (
            validator.slashed
            and epoch + EPOCHS_PER_SLASHINGS_VECTOR // 2 == validator.withdrawable_epoch
        ):
            increment = EFFECTIVE_BALANCE_INCREMENT  # Factored out from penalty numerator to avoid uint64 overflow
            penalty_numerator = (
                validator.effective_balance // increment * adjusted_total_slashing_balance
            )
            penalty = penalty_numerator // total_balance * increment
            decrease_balance(state, ValidatorIndex(index), penalty)
```
