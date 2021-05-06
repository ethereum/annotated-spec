# Ethereum 2.0 Altair Beacon chain changes

This is an annotated version of the Altair beacon chain spec. 

## Table of contents

<!-- TOC -->
<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->

- [Introduction](#introduction)
- [Custom types](#custom-types)
- [Constants](#constants)
  - [Participation flag indices](#participation-flag-indices)
  - [Incentivization weights](#incentivization-weights)
  - [Misc](#misc)
- [Configuration](#configuration)
  - [Updated penalty values](#updated-penalty-values)
  - [Misc](#misc-1)
  - [Time parameters](#time-parameters)
  - [Domain types](#domain-types)
- [Containers](#containers)
  - [Modified containers](#modified-containers)
    - [`BeaconBlockBody`](#beaconblockbody)
    - [`BeaconState`](#beaconstate)
  - [New containers](#new-containers)
    - [`SyncAggregate`](#syncaggregate)
    - [`SyncCommittee`](#synccommittee)
- [Helper functions](#helper-functions)
  - [`Predicates`](#predicates)
    - [`eth2_fast_aggregate_verify`](#eth2_fast_aggregate_verify)
  - [Misc](#misc-2)
    - [`get_flag_indices_and_weights`](#get_flag_indices_and_weights)
    - [`add_flag`](#add_flag)
    - [`has_flag`](#has_flag)
  - [Beacon state accessors](#beacon-state-accessors)
    - [`get_sync_committee_indices`](#get_sync_committee_indices)
    - [`get_sync_committee`](#get_sync_committee)
    - [`get_base_reward_per_increment`](#get_base_reward_per_increment)
    - [`get_base_reward`](#get_base_reward)
    - [`get_unslashed_participating_indices`](#get_unslashed_participating_indices)
    - [`get_flag_index_deltas`](#get_flag_index_deltas)
    - [Modified `get_inactivity_penalty_deltas`](#modified-get_inactivity_penalty_deltas)
  - [Beacon state mutators](#beacon-state-mutators)
    - [Modified `slash_validator`](#modified-slash_validator)
  - [Block processing](#block-processing)
    - [Modified `process_attestation`](#modified-process_attestation)
    - [Modified `process_deposit`](#modified-process_deposit)
    - [Sync committee processing](#sync-committee-processing)
  - [Epoch processing](#epoch-processing)
    - [Justification and finalization](#justification-and-finalization)
    - [Inactivity scores](#inactivity-scores)
    - [Rewards and penalties](#rewards-and-penalties)
    - [Slashings](#slashings)
    - [Participation flags updates](#participation-flags-updates)
    - [Sync committee updates](#sync-committee-updates)
- [Initialize state for pure Altair testnets and test vectors](#initialize-state-for-pure-altair-testnets-and-test-vectors)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->
<!-- /TOC -->

## Introduction

Altair is the first beacon chain hard fork. Its main features are:
Altair is the first hard fork of the Ethereum beacon chain. Its main features are:

* "**Sync committees**", which allow light clients to easily sync up with the header chain with very low computational and data cost. The goal is to make a light client easy and efficient enough that it can be run inside any environment (mobile device, embedded hardware, browser extension, and even inside another smart-contract-capable blockchain)
* **Incentive accounting reforms**. This includes a few changes:
    * Storing actions that were taken during the current and previous epoch in a more efficient bitfield format instead of storing `PendingAttestation` objects, reducing spec complexity
    * Making the "inactivity leak" quadratic _per validator_ instead of quadratic globally, and in particular make it insignificant for validators that are participating >80% of the time. For example, pre-Altair, if a chain stops finalizing for 2 eeks, fully inactive validators lose ~11.8% of their balance and validators active 75% of the time lose ~3.1%. Post-Altair, the fully inactive validator's loss would be ~15.4% but the 75% active validator's loss would only be ~0.3%. This makes inactivity leaks more forgiving to honest-but-imperfect validators.
    * Bug fixes to reward accounting (eg. giving proposers a ~1/8 share of _all_ rewards instead of just a ~1/8 share of one small piece of rewards, and ensuring that the rewards under perfect performance actually do add up to the full base reward)
* **Penalty parameter updates**, making both inactivity leaks and slashing somewhat more punitive than pre-Altair, though still less punitive than their eventually-intended values.

### Aside: validator duties, rewards and penalties

One of the main conceptual reworks of Altair is redesigning how validators are rewarded and penalized to make these incentives more systematic and easy to reason about. Validators are rewarded for fulfilling **duties** - tasks that they are assigned as part of the job of being a validators. These duties come in two types: (i) **attestation duties**, duties to make an attestation in every epoch that gets included quickly and attests to the correct chain, and (ii) **non-attestation duties**, tasks that are not connected to attesting and that any individual validator gets assigned to more rarely. In Altair, the complete list of duties is:

* **`TIMELY_HEAD`**: submit an attestation that correctly identifies the head of the chain, and gets included on chain in the next slot
* **`TIMELY_TARGET`**: submit an attestation that correctly identifies the Casper FFG target, and gets included within `sqrt(EPOCH_LENGTH)` slots
* **`TIMELY_SOURCE`**: submit an attestation that correctly identifies the Casper FFG source, and gets included within `EPOCH_LENGTH` slots
* **Sync committee participation**: if you are part of a sync committee, submit the sync committee signature
* **Proposing**: propose a block if you are assigned to do so

The total theoretical long-run average reward per epoch that a validator can get is determined by the [`get_base_reward`](#get_base_reward) function. Note that this is the maximum long-run average, _not_ the maximum reward in any given epoch. In particular, rewards for submitting sync committee signatures and for proposing are typically much larger than the `get_base_reward`, but any given validator is only assigned these tasks infrequently, and so the average per-epoch reward going to a validator who fulfills these tasks is only a fraction of the base reward.

The base reward is then split up into pieces that are allocated to these duties:



Each piece is represented as a fraction `X / WEIGHT_DENOMINATOR`, where `WEIGHT_DENOMINATOR = 64`.

Note that if a duty is assigned a `X / WEIGHT_DENOMINATOR` share of the pie, that does not necessarily mean that a validator who fulfills that duty is guaranteed to get exactly that fraction times the base reward in rewards. The attestation rewards are proportional to the percentage of validators who fulfill the duty (eg. if only 80% of validators fulfill the duty then the reward for each validator that does is multiplied by 0.8); this rule was added to discourage censorship and inter-validator attacks. A validator may be prevented from getting some sync committee rewards through no fault of their own if other proposers misbehave or are missing, and proposer rewards are dependent on what messages the proposer includes, which are in turn dependent on what other validators publish. However, in a well-functioning network, rewards should get quite close to these theoretical maximums.

Note also that there is one reward that falls outside this scheme: slashing whistleblower rewards. These rewards fall outside the duties scheme because they are irregular (we don't know ahead of time how many slashings there will be), and they don't contribute to issuance (because the slashing whistleblower reward is counterbalanced by a much larger slashing penalty suffered by whoever was slashed).

## Custom types

| Name | SSZ equivalent | Description |
| - | - | - |
| `ParticipationFlags` | `uint8` | a succinct representation of 8 boolean participation flags |

We will maintain a byte array to store which actions a validator has successfully taken during a given epoch, so that we can calculate finality and other global statistics and reward or penalize validators at the end of the epoch. Each validator gets 8 bits: 3 for each of their **attestation duties** (attesting to the correct Casper FFG source, to the correct Casper FFG target, and to the correct head), and 5 not-yet-used bits to be used for duties to be added in the future.

## Constants

### Participation flag indices

| Name | Value |
| - | - |
| `TIMELY_HEAD_FLAG_INDEX` | `0` |
| `TIMELY_SOURCE_FLAG_INDEX` | `1` |
| `TIMELY_TARGET_FLAG_INDEX` | `2` |

The "timely" here refers to the fact that fulfilling each of the three duties actually requires simultaneously meeting _two_ requirements: (i) correctly attesting to something, and (ii) having your attestation be included on time. See [the modified `process_attestation` function](#modified-process_attestation) for the exact specification of each of the three duties.

### Incentivization weights

| Name | Value |
| - | - |
| `TIMELY_HEAD_WEIGHT` | `uint64(12)` |
| `TIMELY_SOURCE_WEIGHT` | `uint64(12)` |
| `TIMELY_TARGET_WEIGHT` | `uint64(24)` |
| `SYNC_REWARD_WEIGHT` | `uint64(8)` |
| `PROPOSER_WEIGHT` | `uint64(8)` |
| `WEIGHT_DENOMINATOR` | `uint64(64)` |

Altair introduces a simpler and cleaner reward scheme for validators. The maximum reward that a validator can get in an epoch (if they (and others) perform perfectly) is determined by the [`get_base_reward` function](#get_base_reward), approximately equal to:

```
validator_balance * BASE_REWARD_FACTOR / sqrt(total_active_balance)
```

Where `BASE_REWARD_FACTOR = 64` and the balances and rewards are all denominated in gwei.

For example, if a validator has 32 ETH and the total active balance is 5 million ETH, the validator would get `(32 * 10**9 * 64) / sqrt(5000000 * 10**9) = 28963` gwei (the `* 10**9` being conversion from ETH to gwei). Multiplying that result by `31556925 / 384` (epochs per year), you get a reward of ~2.38 billion gwei, or 2.38 ETH, per year. If a validator performs imperfectly (or even if _other validators_ perform imperfectly), these rewards would be reduced somewhat, though in a well-running network rewards can often exceed 97% of the theoretical maximum.

The validator's reward is in turn made up of different parts, each of which are rewards for fulfilling a particular **duty**. The first three duties (`TIMELY_HEAD`, `TIMELY_SOURCE` and `TIMELY_TARGET`) are for making attestations to the correct blocks and publishing them and getting them included quickly enough. These duties together make up `(12+12+24)/64`, or `3/4`, of the total reward. The remaining duties are participating in the sync committee (`8/64`, or `1/8`, of the total reward) and proposing blocks (also `8/64`, or `1/8`, of the total reward).

### Misc

| Name | Value |
| - | - |
| `G2_POINT_AT_INFINITY` | `BLSSignature(b'\xc0' + b'\x00' * 95)` |

## Configuration

### Updated penalty values

This patch updates a few configuration values to move penalty parameters closer to their final, maximum security values.

*Note*: The spec does *not* override previous configuration values but instead creates new values and replaces usage throughout.

| Name | Value |
| - | - |
| `INACTIVITY_PENALTY_QUOTIENT_ALTAIR` | `uint64(3 * 2**24)` (= 50,331,648) |
| `MIN_SLASHING_PENALTY_QUOTIENT_ALTAIR` | `uint64(2**6)` (= 64) |
| `PROPORTIONAL_SLASHING_MULTIPLIER_ALTAIR` | `uint64(2)` |

The inactivity penalty quotient reduction should reduce the time that it takes for balances to leak by ~13.4% (not 25% because time-to-leak is proportional to the _square root_ of this quotient). The slashing penalty quotient changes increase the maximum loss from slashing from 0.25 ETH to 0.5 ETH, and decrease the percentage of misbehaving validators required for a slashing loss to be total from 100% to 50%.

### Misc

| Name | Value |
| - | - |
| `SYNC_COMMITTEE_SIZE` | `uint64(2**10)` (= 1,024) |
| `SYNC_PUBKEYS_PER_AGGREGATE` | `uint64(2**6)` (= 64) |

The **sync committee** is the "flagship feature" of the Altair hard fork. This is a committee of 512 validators that is randomly selected every ~2 days, and is assigned to sign the most recent block header. The public keys of the current and next sync committee are committed to in the beacon state. This allows light clients to keep track of the chain of beacon block headers, use the sync committee signatures to verify new block headers, and use the Merkle paths from beacon block headers to validate new sync committees. The minimum cost for light clients is a mere `512 * 48 = 24576` bytes per two days (plus another few hundred bytes for a Merkle branch and a single block header), though closely following the chain does of course require downloading and checking headers more frequently.

| `INACTIVITY_SCORE_BIAS` | `uint64(4)` |
| - | - |

See [the later section on inactivity penalty calculation](#modified-get_inactivity_penalty_deltas) for details.

### Time parameters

| Name | Value | Unit | Duration |
| - | - | :-: | :-: |
| `EPOCHS_PER_SYNC_COMMITTEE_PERIOD` | `Epoch(2**8)` (= 256) | epochs | ~27 hours |

A new sync committee is chosen once every two days.

### Domain types

| Name | Value |
| - | - |
| `DOMAIN_SYNC_COMMITTEE` | `DomainType('0x07000000')` |
| `DOMAIN_SYNC_COMMITTEE_SELECTION_PROOF` | `DomainType('0x08000000')` |
| `DOMAIN_CONTRIBUTION_AND_PROOF` | `DomainType('0x09000000')` |

## Containers

### Modified containers

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
    # [New in Altair]
    sync_aggregate: SyncAggregate
```

The beacon block body now contains a `SyncAggregate` object, basically an aggregate signature (a BLS signature plus a bitfield of who participated) signed by the sync committee. Note that the `SyncAggregate` would also be separately broadcasted over the wire for light clients; it's included on-chain only so that participants in the signature can be rewarded.

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
    previous_epoch_participation: List[ParticipationFlags, VALIDATOR_REGISTRY_LIMIT]  # [Modified in Altair]
    current_epoch_participation: List[ParticipationFlags, VALIDATOR_REGISTRY_LIMIT]  # [Modified in Altair]
    # Finality
    justification_bits: Bitvector[JUSTIFICATION_BITS_LENGTH]  # Bit set for every recent justified epoch
    previous_justified_checkpoint: Checkpoint
    current_justified_checkpoint: Checkpoint
    finalized_checkpoint: Checkpoint
    # Inactivity
    inactivity_scores: List[uint64, VALIDATOR_REGISTRY_LIMIT]  # [New in Altair]
    # Sync
    current_sync_committee: SyncCommittee  # [New in Altair]
    next_sync_committee: SyncCommittee  # [New in Altair]
```

The beacon state commits to the current sync committee and the next sync committee so that light clients that have accepted a block header can easily authenticate the sync committee for the next period. Without this feature, it would be difficult to do so, as it would require a computation on the entire validator set to determine the active validator list, and even after that point require a Merkle branch for each committee member.

### New containers

#### `SyncAggregate`

```python
class SyncAggregate(Container):
    sync_committee_bits: Bitvector[SYNC_COMMITTEE_SIZE]
    sync_committee_signature: BLSSignature
```

#### `SyncCommittee`

```python
class SyncCommittee(Container):
    pubkeys: Vector[BLSPubkey, SYNC_COMMITTEE_SIZE]
    pubkey_aggregates: Vector[BLSPubkey, SYNC_COMMITTEE_SIZE // SYNC_PUBKEYS_PER_AGGREGATE]
```

We store not just each individual pubkey, but also the sum of all the pubkeys. This is done so that when sync committees have a very high level of participation, few elliptic curve additions are required to verify the signature: you can just start with the sum and _subtract out_ all the pubkeys that did not participate.

## Helper functions

### `Predicates`

#### `eth2_fast_aggregate_verify`

```python
def eth2_fast_aggregate_verify(pubkeys: Sequence[BLSPubkey], message: Bytes32, signature: BLSSignature) -> bool:
    """
    Wrapper to ``bls.FastAggregateVerify`` accepting the ``G2_POINT_AT_INFINITY`` signature when ``pubkeys`` is empty.
    """
    if len(pubkeys) == 0 and signature == G2_POINT_AT_INFINITY:
        return True
    return bls.FastAggregateVerify(pubkeys, message, signature)
```

There are a few minor discrepancies between how the IETF BLS signature standard handles signatures and the needs of the eth2 protocol; to deal with this, in a few cases we need to wrap the IETF standard to replace its behavior with our own preferred behavior. Here, the important case is that multi-verification in the IETF standard does not support the empty signature as a valid signature for an empty aggregate, but in our use cases it's critically important to be able to support the empty case (in case no sync committee members at all get their signatures included).

### Misc

#### `get_flag_indices_and_weights`

```python
def get_flag_indices_and_weights() -> Sequence[Tuple[int, uint64]]:
    """
    Return paired tuples of participation flag indices along with associated incentivization weights.
    """
    return (
        (TIMELY_HEAD_FLAG_INDEX, TIMELY_HEAD_WEIGHT),
        (TIMELY_SOURCE_FLAG_INDEX, TIMELY_SOURCE_WEIGHT),
        (TIMELY_TARGET_FLAG_INDEX, TIMELY_TARGET_WEIGHT),
    )
```

These are the three attester duties and their corresponding weights. The "flag index" is the position in the `ParticipationFlags` mini-bitfield that is used to store whether or not a given validator has fulfilled that duty.

#### `add_flag`

```python
def add_flag(flags: ParticipationFlags, flag_index: int) -> ParticipationFlags:
    """
    Return a new ``ParticipationFlags`` adding ``flag_index`` to ``flags``.
    """
    flag = ParticipationFlags(2**flag_index)
    return flags | flag
```

#### `has_flag`

```python
def has_flag(flags: ParticipationFlags, flag_index: int) -> bool:
    """
    Return whether ``flags`` has ``flag_index`` set.
    """
    flag = ParticipationFlags(2**flag_index)
    return flags & flag == flag
```

### Beacon state accessors

#### `get_sync_committee_indices`

```python
def get_sync_committee_indices(state: BeaconState, epoch: Epoch) -> Sequence[ValidatorIndex]:
    """
    Return the sequence of sync committee indices (which may include duplicate indices)
    for a given ``state`` and ``epoch``.
    """
    MAX_RANDOM_BYTE = 2**8 - 1
    base_epoch = Epoch((max(epoch // EPOCHS_PER_SYNC_COMMITTEE_PERIOD, 1) - 1) * EPOCHS_PER_SYNC_COMMITTEE_PERIOD)
    active_validator_indices = get_active_validator_indices(state, base_epoch)
    active_validator_count = uint64(len(active_validator_indices))
    seed = get_seed(state, base_epoch, DOMAIN_SYNC_COMMITTEE)
    i = 0
    sync_committee_indices: List[ValidatorIndex] = []
    while len(sync_committee_indices) < SYNC_COMMITTEE_SIZE:
        shuffled_index = compute_shuffled_index(uint64(i % active_validator_count), active_validator_count, seed)
        candidate_index = active_validator_indices[shuffled_index]
        random_byte = hash(seed + uint_to_bytes(uint64(i // 32)))[i % 32]
        effective_balance = state.validators[candidate_index].effective_balance
        if effective_balance * MAX_RANDOM_BYTE >= MAX_EFFECTIVE_BALANCE * random_byte:  # Sample with replacement
            sync_committee_indices.append(candidate_index)
        i += 1
    return sync_committee_indices
```

This is the core function that computes the sync committee that will be active in a given `epoch`. It proceeds as follows:

* Compute the `base_epoch`, the epoch at the _start of the previous_ sync committee period (eg. if the sync committee period length was 100 epochs, and the `epoch` was 557, the `base_epoch` would be 400). 
* Compute the active validator indices at the `base_epoch`
* Walk through the shuffled indices based on the seed at the `base_epoch` (that is, go through `compute_shuffled_index(0)`, `compute_shuffled_index(1)`, etc.). For each index, accept that validator with probability `B/32` where `B` is their effective balance.

The base epoch being set to the start of the previous sync committee period ensures that there will always be at least one full period of look-ahead between when a committee is known and when the committee is used. This allows the sync committee that will be active in period N+1 to be computed and committed to in the `BeaconState` at the start of period N, allowing light clients to verify the sync committee from period N+1 from a period N block and thereby jump forward quickly through the header chain.

For shuffling, note that the probability of being accepted is proportional to your balance. Hence, there is no need for participation rewards to be proportional to balance, and there is also no need for the light client fork choice rule to care about the balances of sync committee members. Additionally, note that the sync committee is always filled to its maximum size; if the validator count is extremely low and it is absolutely needed to do this, this algorithm wraps around and walks through the shuffled validator set multiple times, and it can even accept the same validator multiple times into the committee.

#### `get_sync_committee`

```python
def get_sync_committee(state: BeaconState, epoch: Epoch) -> SyncCommittee:
    """
    Return the sync committee for a given ``state`` and ``epoch``.
    """
    indices = get_sync_committee_indices(state, epoch)
    pubkeys = [state.validators[index].pubkey for index in indices]
    partition = [pubkeys[i:i + SYNC_PUBKEYS_PER_AGGREGATE] for i in range(0, len(pubkeys), SYNC_PUBKEYS_PER_AGGREGATE)]
    pubkey_aggregates = [bls.AggregatePKs(preaggregate) for preaggregate in partition]
    return SyncCommittee(pubkeys=pubkeys, pubkey_aggregates=pubkey_aggregates)
```

This function computes a `SyncCommittee` object, which is an SSZ representation of the public keys contained in a sync committee. It contains the pubkey of each member of the sync committee, plus an aggregate (the sum of all the pubkeys) to make signature verification easier in that case where almost everyone participates in a sync committee signature and so you only need to subtract out a few non-participants to generate the group public key.

#### `get_base_reward_per_increment`

```python
def get_base_reward_per_increment(state: BeaconState) -> Gwei:
    return Gwei(EFFECTIVE_BALANCE_INCREMENT * BASE_REWARD_FACTOR // integer_squareroot(get_total_active_balance(state)))
```

The `get_base_reward` function is being re-factored for Altair to make it cleaner. The key changes are:

1. Split up the logic into `get_base_reward_per_increment` (the reward for a hypothetical 1 ETH validator) and `get_base_reward` that simply multiplies that value by the amount of ETH in the validator's effective balance. This was done because sync committee reward logic needs to use `get_base_reward_per_increment` as a standalone function.
2. The output of `get_base_reward` now represents the _entire_ theoretical maximum expected long-term reward, and not merely one component of it as before. This was done just to increase simplicity.

#### `get_base_reward`

*Note*: The function `get_base_reward` is modified with the removal of `BASE_REWARDS_PER_EPOCH` and the use of increment based accounting.

```python
def get_base_reward(state: BeaconState, index: ValidatorIndex) -> Gwei:
    """
    Return the base reward for the validator defined by ``index`` with respect to the current ``state``.

    Note: A validator can optimally earn one base reward per epoch over a long time horizon.
    This takes into account both per-epoch (e.g. attestation) and intermittent duties (e.g. block proposal
    and sync committees).
    """
    increments = state.validators[index].effective_balance // EFFECTIVE_BALANCE_INCREMENT
    return Gwei(increments * get_base_reward_per_increment(state))
```

#### `get_unslashed_participating_indices`

```python
def get_unslashed_participating_indices(state: BeaconState, flag_index: int, epoch: Epoch) -> Set[ValidatorIndex]:
    """
    Return the set of validator indices that are both active and unslashed for the given ``flag_index`` and ``epoch``.
    """
    assert epoch in (get_previous_epoch(state), get_current_epoch(state))
    if epoch == get_current_epoch(state):
        epoch_participation = state.current_epoch_participation
    else:
        epoch_participation = state.previous_epoch_participation
    active_validator_indices = get_active_validator_indices(state, epoch)
    participating_indices = [i for i in active_validator_indices if has_flag(epoch_participation[i], flag_index)]
    return set(filter(lambda index: not state.validators[index].slashed, participating_indices))
```

A major feature of Altair is reforming how we keep track of which validators fulfilled which duties during an epoch so we can reward them and compute finality. The intuitively cleanest approach, simply giving validators their reward and tracking progress toward finality in real time, has three key problems:

1. It does not prevent validators from getting their attestations included twice (preventing that would require some kind of bitfield _anyway_)
2. It does not have an easy path to allow rewards to be proportional to total participation levels (a feature that we want to keep to discourage censorship and inter-validator attacks)
3. It would require random-access updates to validator balances, which are expensive. This is because a random-access update requires re-computing a Merkle branch, or up to 22 hashes per validator per epoch. Updating balances at the end of an epoch in a batch, on the other hand, simply re-computes the entire balance tree, costing ~1/4 hashes per validator per epoch (each balance is 8 bytes, a chunk is 32 bytes, an N-chunk Merkle tree requires N-1 hashes to recompute)

The pre-Altair approach was to store `PendingAttestation` objects, effectively keeping the attestations received during an epoch in the state (and adding information about when they were received to keep track of timeliness) and then processing them all at once at the end of the epoch. The Altair approach is more efficient: it stores a bitfield (1 byte per active validator) and updates the bitfield in real time. We avoid random-access updates because the bitfield is stored _in shuffled order_, meaning that the `ParticipationFlags` of the validators in the same committee are stored beside each other. This ensures the real-time cost of updating this bitfield is only ~1/32 hashes per validator (slightly more if there are two attestations for the same committee, but never too much more).

#### `get_flag_index_deltas`

```python
def get_flag_index_deltas(state: BeaconState, flag_index: int, weight: uint64) -> Tuple[Sequence[Gwei], Sequence[Gwei]]:
    """
    Return the deltas for a given ``flag_index`` scaled by ``weight`` by scanning through the participation flags.
    """
    rewards = [Gwei(0)] * len(state.validators)
    penalties = [Gwei(0)] * len(state.validators)
    unslashed_participating_indices = get_unslashed_participating_indices(state, flag_index, get_previous_epoch(state))
    increment = EFFECTIVE_BALANCE_INCREMENT  # Factored out from balances to avoid uint64 overflow
    unslashed_participating_increments = get_total_balance(state, unslashed_participating_indices) // increment
    active_increments = get_total_active_balance(state) // increment
    for index in get_eligible_validator_indices(state):
        base_reward = get_base_reward(state, index)
        if index in unslashed_participating_indices:
            if is_in_inactivity_leak(state):
                # This flag reward cancels the inactivity penalty corresponding to the flag index
                rewards[index] += Gwei(base_reward * weight // WEIGHT_DENOMINATOR)
            else:
                reward_numerator = base_reward * weight * unslashed_participating_increments
                rewards[index] += Gwei(reward_numerator // (active_increments * WEIGHT_DENOMINATOR))
        else:
            penalties[index] += Gwei(base_reward * weight // WEIGHT_DENOMINATOR)
    return rewards, penalties
```

This function computes the rewards and penalties for fulfilling (or failing to fulfill) a particular duty. The fundamental structure is identical to pre-Altair rewards: if `X` is the maximum reward for fulfilling a duty and `p` is the portion of validators that fulfilled it, then fulfilling the duty gets you a reward of `p * X` and failing to fulfill it gets you a penalty of `X`. If an inactivity leak is active, the reward drops to `0` (ie. the benefit for fulfilling the duty during a leak is _only_ the ability to avoid penalties).

The main change from pre-Altair is the `weight // WEIGHT_DENOMINATOR` factor, reflecting that the `base_reward` now refers to the maximum _total_ reward and not the maximum _per-duty_ reward as it did pre-Altair (notice that this new structure also gives us more flexibility to assign different rewards to different duties).

#### Modified `get_inactivity_penalty_deltas`

*Note*: The function `get_inactivity_penalty_deltas` is modified in the selection of matching target indices
and the removal of `BASE_REWARDS_PER_EPOCH`.

```python
def get_inactivity_penalty_deltas(state: BeaconState) -> Tuple[Sequence[Gwei], Sequence[Gwei]]:
    """
    Return the inactivity penalty deltas by considering timely target participation flags and inactivity scores.
    """
    rewards = [Gwei(0) for _ in range(len(state.validators))]
    penalties = [Gwei(0) for _ in range(len(state.validators))]
    if is_in_inactivity_leak(state):
        previous_epoch = get_previous_epoch(state)
        matching_target_indices = get_unslashed_participating_indices(state, TIMELY_TARGET_FLAG_INDEX, previous_epoch)
        for index in get_eligible_validator_indices(state):
            for (_, weight) in get_flag_indices_and_weights():
                # This inactivity penalty cancels the flag reward corresponding to the flag index
                penalties[index] += Gwei(get_base_reward(state, index) * weight // WEIGHT_DENOMINATOR)
            if index not in matching_target_indices:
                penalty_numerator = state.validators[index].effective_balance * state.inactivity_scores[index]
                penalty_denominator = INACTIVITY_SCORE_BIAS * INACTIVITY_PENALTY_QUOTIENT_ALTAIR
                penalties[index] += Gwei(penalty_numerator // penalty_denominator)
    return rewards, penalties
```

The way that the inactivity leak works in Altair has been significantly reformed. The most significant reform is that pre-Altair the inactivity leak for a validator in a given epoch was proportional to a _global_ variable equal to the number of epochs since the last time the chain finalized, whereas post-Altair the inactivity leak in a given epoch is proportional to a _per-validator_ variable called the _inactivity score_.

For _fully inactive_ validators, the effect is the same: during each epoch that a validator is inactive and the chain fails to finalize, the inactivity score increases by a fixed number, and so the _total_ loss after `N` epochs is proportional to the area-under-the-triangle `N**2/2`. For _perfectly active_ validators, the effect again is the same: both pre-Altair and post-Altair, validators that fulfill their duties perfectly suffer no losses.

The difference is for _imperfectly active validators_. The inactivity score's behavior is specified by [this function](#inactivity-scores):

* If, during an inactivity leak epoch, a validator fails to submit an attestation with the correct source and target, their inactivity score goes up by 4
* If, during _any_ epoch, a validator successfully submits an attestation with the correct source and target, their inactivity score drops by 1

This means that if a validator participates correctly more than 80% of the time, their inactivity score will hover close to zero, and so their inactivity leak penalties will be very close to zero. Validators that miss more than 20% of epochs will see their inactivity scores rise, though even there the penalties are slow at first (eg. a validator that misses 25% of epochs will only suffer ~1/4 the inactivity leak of a validator that misses 30% of epochs).

### Beacon state mutators

#### Modified `slash_validator`

*Note*: The function `slash_validator` is modified to use `MIN_SLASHING_PENALTY_QUOTIENT_ALTAIR` and use `PROPOSER_WEIGHT` when calculating the proposer reward.

```python
def slash_validator(state: BeaconState,
                    slashed_index: ValidatorIndex,
                    whistleblower_index: ValidatorIndex=None) -> None:
    """
    Slash the validator with index ``slashed_index``.
    """
    epoch = get_current_epoch(state)
    initiate_validator_exit(state, slashed_index)
    validator = state.validators[slashed_index]
    validator.slashed = True
    validator.withdrawable_epoch = max(validator.withdrawable_epoch, Epoch(epoch + EPOCHS_PER_SLASHINGS_VECTOR))
    state.slashings[epoch % EPOCHS_PER_SLASHINGS_VECTOR] += validator.effective_balance
    decrease_balance(state, slashed_index, validator.effective_balance // MIN_SLASHING_PENALTY_QUOTIENT_ALTAIR)

    # Apply proposer and whistleblower rewards
    proposer_index = get_beacon_proposer_index(state)
    if whistleblower_index is None:
        whistleblower_index = proposer_index
    whistleblower_reward = Gwei(validator.effective_balance // WHISTLEBLOWER_REWARD_QUOTIENT)
    proposer_reward = Gwei(whistleblower_reward * PROPOSER_WEIGHT // WEIGHT_DENOMINATOR)
    increase_balance(state, proposer_index, proposer_reward)
    increase_balance(state, whistleblower_index, Gwei(whistleblower_reward - proposer_reward))
```

### Block processing

```python
def process_block(state: BeaconState, block: BeaconBlock) -> None:
    process_block_header(state, block)
    process_randao(state, block.body)
    process_eth1_data(state, block.body)
    process_operations(state, block.body)  # [Modified in Altair]
    process_sync_committee(state, block.body.sync_aggregate)  # [New in Altair]
```

#### Modified `process_attestation`

*Note*: The function `process_attestation` is modified to do incentive accounting with epoch participation flags.

```python
def process_attestation(state: BeaconState, attestation: Attestation) -> None:
    data = attestation.data
    assert data.target.epoch in (get_previous_epoch(state), get_current_epoch(state))
    assert data.target.epoch == compute_epoch_at_slot(data.slot)
    assert data.slot + MIN_ATTESTATION_INCLUSION_DELAY <= state.slot <= data.slot + SLOTS_PER_EPOCH
    assert data.index < get_committee_count_per_slot(state, data.target.epoch)

    committee = get_beacon_committee(state, data.slot, data.index)
    assert len(attestation.aggregation_bits) == len(committee)

    if data.target.epoch == get_current_epoch(state):
        epoch_participation = state.current_epoch_participation
        justified_checkpoint = state.current_justified_checkpoint
    else:
        epoch_participation = state.previous_epoch_participation
        justified_checkpoint = state.previous_justified_checkpoint

    # Matching roots
    is_matching_source = data.source == justified_checkpoint
    is_matching_target = is_matching_source and data.target.root == get_block_root(state, data.target.epoch)
    is_matching_head = is_matching_target and data.beacon_block_root == get_block_root_at_slot(state, data.slot)
    assert is_matching_source

    # Verify signature
    assert is_valid_indexed_attestation(state, get_indexed_attestation(state, attestation))

    # Participation flag indices
    participation_flag_indices = []
    if is_matching_source and state.slot <= data.slot + integer_squareroot(SLOTS_PER_EPOCH):
        participation_flag_indices.append(TIMELY_SOURCE_FLAG_INDEX)
    if is_matching_target and state.slot <= data.slot + SLOTS_PER_EPOCH:
        participation_flag_indices.append(TIMELY_TARGET_FLAG_INDEX)
    if is_matching_head and state.slot == data.slot + MIN_ATTESTATION_INCLUSION_DELAY:
        participation_flag_indices.append(TIMELY_HEAD_FLAG_INDEX)

    # Update epoch participation flags
    proposer_reward_numerator = 0
    for index in get_attesting_indices(state, data, attestation.aggregation_bits):
        for flag_index, weight in get_flag_indices_and_weights():
            if flag_index in participation_flag_indices and not has_flag(epoch_participation[index], flag_index):
                epoch_participation[index] = add_flag(epoch_participation[index], flag_index)
                proposer_reward_numerator += get_base_reward(state, index) * weight

    # Reward proposer
    proposer_reward_denominator = (WEIGHT_DENOMINATOR - PROPOSER_WEIGHT) * WEIGHT_DENOMINATOR // PROPOSER_WEIGHT
    proposer_reward = Gwei(proposer_reward_numerator // proposer_reward_denominator)
    increase_balance(state, get_beacon_proposer_index(state), proposer_reward)
```

The main difference between this code and pre-Altair code is that here we replace the pre-Altair `PendingAttestation` logic with the much cleaner `ParticipationFlags` logic.

#### Aside: proposer rewards in Altair

Note also some new special logic for the proposer rewards: the proposer reward for a duty is the attester reward for that duty, multiplied by the _proposer reward as a fraction of everything but the proposer reward_.

The mathematical reasoning here is subtle. Here is the chart for how rewards are allocated in Altair (not including whistleblower-related rewards as those fall outside the base reward schema). All rewards add up to a theoretical max of a full `base_reward`. `7/8` of the chart is allocated to non-proposal duties. The remaining `1/8` is allocated to proposer rewards, and is split up proportionately to the rewards for the thing that the proposer is including.

![](piechart.png)

For example, we can focus on the `TIMELY_HEAD` duty. If you as a validator make an attestation to the correct head, and get it included in the next slot, you get the `TIMELY_HEAD` reward: `12/64` of a base reward. But we could instead think of it as _`12/56` of the non-proposal rewards_, where in turn the non-proposal rewards account for `56/64` (or `7/8`) of the whole pie. The proposer slice of the pie is allocated in the same proportions as the non-proposer slice of the pie: the proposer that _includes_ your timely-head attestation gets _`12/56` of the proposal rewards_ as a reward for doing so. If everyone (including the proposers) perform perfectly at everything, the non-proposer rewards add up to `56/64` of the base reward, and the proposer rewards themselves add up to `56/56` of the `8/64` proposer share (ie. the entire remaining `8/64` of the base reward), and so the combined rewards to everyone are exactly a full base reward.

#### Modified `process_deposit`

*Note*: The function `process_deposit` is modified to initialize `inactivity_scores`, `previous_epoch_participation`, and `current_epoch_participation`.

```python
def process_deposit(state: BeaconState, deposit: Deposit) -> None:
    # Verify the Merkle branch
    assert is_valid_merkle_branch(
        leaf=hash_tree_root(deposit.data),
        branch=deposit.proof,
        depth=DEPOSIT_CONTRACT_TREE_DEPTH + 1,  # Add 1 for the List length mix-in
        index=state.eth1_deposit_index,
        root=state.eth1_data.deposit_root,
    )

    # Deposits must be processed in order
    state.eth1_deposit_index += 1

    pubkey = deposit.data.pubkey
    amount = deposit.data.amount
    validator_pubkeys = [validator.pubkey for validator in state.validators]
    if pubkey not in validator_pubkeys:
        # Verify the deposit signature (proof of possession) which is not checked by the deposit contract
        deposit_message = DepositMessage(
            pubkey=deposit.data.pubkey,
            withdrawal_credentials=deposit.data.withdrawal_credentials,
            amount=deposit.data.amount,
        )
        domain = compute_domain(DOMAIN_DEPOSIT)  # Fork-agnostic domain since deposits are valid across forks
        signing_root = compute_signing_root(deposit_message, domain)
        # Initialize validator if the deposit signature is valid
        if bls.Verify(pubkey, signing_root, deposit.data.signature):
            state.validators.append(get_validator_from_deposit(state, deposit))
            state.balances.append(amount)
            state.previous_epoch_participation.append(ParticipationFlags(0b0000_0000))
            state.current_epoch_participation.append(ParticipationFlags(0b0000_0000))
            state.inactivity_scores.append(uint64(0))
    else:
        # Increase balance by deposit amount
        index = ValidatorIndex(validator_pubkeys.index(pubkey))
        increase_balance(state, index, amount)
```

#### Sync committee processing

```python
def process_sync_committee(state: BeaconState, aggregate: SyncAggregate) -> None:
    # Verify sync committee aggregate signature signing over the previous slot block root
    committee_pubkeys = state.current_sync_committee.pubkeys
    participant_pubkeys = [pubkey for pubkey, bit in zip(committee_pubkeys, aggregate.sync_committee_bits) if bit]
    previous_slot = max(state.slot, Slot(1)) - Slot(1)
    domain = get_domain(state, DOMAIN_SYNC_COMMITTEE, compute_epoch_at_slot(previous_slot))
    signing_root = compute_signing_root(get_block_root_at_slot(state, previous_slot), domain)
    assert eth2_fast_aggregate_verify(participant_pubkeys, signing_root, aggregate.sync_committee_signature)

    # Compute participant and proposer rewards
    total_active_increments = get_total_active_balance(state) // EFFECTIVE_BALANCE_INCREMENT
    total_base_rewards = Gwei(get_base_reward_per_increment(state) * total_active_increments)
    max_participant_rewards = Gwei(total_base_rewards * SYNC_REWARD_WEIGHT // WEIGHT_DENOMINATOR // SLOTS_PER_EPOCH)
    participant_reward = Gwei(max_participant_rewards // SYNC_COMMITTEE_SIZE)
    proposer_reward = Gwei(participant_reward * PROPOSER_WEIGHT // (WEIGHT_DENOMINATOR - PROPOSER_WEIGHT))

    # Apply participant and proposer rewards
    committee_indices = get_sync_committee_indices(state, get_current_epoch(state))
    participant_indices = [index for index, bit in zip(committee_indices, aggregate.sync_committee_bits) if bit]
    for participant_index in participant_indices:
        increase_balance(state, participant_index, participant_reward)
        increase_balance(state, get_beacon_proposer_index(state), proposer_reward)
```

This function verifies that the sync committee included in the block is correct, and computes and applies the rewards for participants. The signature verification logic is simple: sync committee members are expected to sign the block header, and the signing root is computed from the block header root and the domain (much like all BLS signatures in the beacon chain protocol sign messages with domains attached for anti-replay-rpotection reasons). The signature is verified against the subset of sync committee members that participated, which can be determined from the sync committee and the bitfield.

There is some subtlety in correctly computing the rewards. The goal is for maximum possible total sync committee rewards to equal `8/64` of the base reward for the _total_ validator set (so that _in the long term, on average_, a perfectly participating validator gets `8/64` of the base reward per epoch for their sync committee participation. The base reward itself is per-epoch, and sync committees are per-slot, so to get the total reward per-slot, we take the total base reward and further divide it by `SLOTS_PER_EPOCH`. This gives us `max_participant_rewards`, the maximum possible combined reward to the whole sync committee in one slot.

We get the `participant_reward` (the reward to each participant) by dividing the `max_participant_rewards` by the size of the committee. Proposer rewards for including signatures are set to `8/56` of the rewards for producing the signatures, [just like in the rest of the protocol](#aside-proposer-rewards-in-altair).

### Epoch processing

```python
def process_epoch(state: BeaconState) -> None:
    process_justification_and_finalization(state)  # [Modified in Altair]
    process_inactivity_updates(state)  # [New in Altair]
    process_rewards_and_penalties(state)  # [Modified in Altair]
    process_registry_updates(state)
    process_slashings(state)  # [Modified in Altair]
    process_eth1_data_reset(state)
    process_effective_balance_updates(state)
    process_slashings_reset(state)
    process_randao_mixes_reset(state)
    process_historical_roots_update(state)
    process_participation_flag_updates(state)  # [New in Altair]
    process_sync_committee_updates(state)  # [New in Altair]
```

#### Justification and finalization

*Note*: The function `process_justification_and_finalization` is modified to adapt to the new participation records.

```python
def process_justification_and_finalization(state: BeaconState) -> None:
    # Initial FFG checkpoint values have a `0x00` stub for `root`.
    # Skip FFG updates in the first two epochs to avoid corner cases that might result in modifying this stub.
    if get_current_epoch(state) <= GENESIS_EPOCH + 1:
        return
    previous_indices = get_unslashed_participating_indices(state, TIMELY_TARGET_FLAG_INDEX, get_previous_epoch(state))
    current_indices = get_unslashed_participating_indices(state, TIMELY_TARGET_FLAG_INDEX, get_current_epoch(state))
    total_active_balance = get_total_active_balance(state)
    previous_target_balance = get_total_balance(state, previous_indices)
    current_target_balance = get_total_balance(state, current_indices)
    weigh_justification_and_finalization(state, total_active_balance, previous_target_balance, current_target_balance)
```

The `weigh_justification_and_finalization` function, unchanged from pre-Altair, actually checks justification and finality of epochs and adds records to the state as needed. This outer `process_justification_and_finalization` function is modified to remove the pre-Altair complicated logic for computing participants from `PendingAttestation` records, and instead simply sums the balances of all validators with a 1 in the right place of their participation bitfields.

#### Inactivity scores

*Note*: The function `process_inactivity_updates` is new.

```python
def process_inactivity_updates(state: BeaconState) -> None:
    for index in get_eligible_validator_indices(state):
        if index in get_unslashed_participating_indices(state, TIMELY_TARGET_FLAG_INDEX, get_previous_epoch(state)):
            if state.inactivity_scores[index] > 0:
                state.inactivity_scores[index] -= 1
        elif is_in_inactivity_leak(state):
            state.inactivity_scores[index] += INACTIVITY_SCORE_BIAS
```

See [here](#modified-get_inactivity_penalty_deltas) for what this function is doing and how it is used.

#### Rewards and penalties

*Note*: The function `process_rewards_and_penalties` is modified to support the incentive accounting reforms.

```python
def process_rewards_and_penalties(state: BeaconState) -> None:
    # No rewards are applied at the end of `GENESIS_EPOCH` because rewards are for work done in the previous epoch
    if get_current_epoch(state) == GENESIS_EPOCH:
        return

    flag_indices_and_numerators = get_flag_indices_and_weights()
    flag_deltas = [get_flag_index_deltas(state, index, numerator) for (index, numerator) in flag_indices_and_numerators]
    deltas = flag_deltas + [get_inactivity_penalty_deltas(state)]
    for (rewards, penalties) in deltas:
        for index in range(len(state.validators)):
            increase_balance(state, ValidatorIndex(index), rewards[index])
            decrease_balance(state, ValidatorIndex(index), penalties[index])
```

#### Slashings

*Note*: The function `process_slashings` is modified to use `PROPORTIONAL_SLASHING_MULTIPLIER_ALTAIR`.

```python
def process_slashings(state: BeaconState) -> None:
    epoch = get_current_epoch(state)
    total_balance = get_total_active_balance(state)
    adjusted_total_slashing_balance = min(sum(state.slashings) * PROPORTIONAL_SLASHING_MULTIPLIER_ALTAIR, total_balance)
    for index, validator in enumerate(state.validators):
        if validator.slashed and epoch + EPOCHS_PER_SLASHINGS_VECTOR // 2 == validator.withdrawable_epoch:
            increment = EFFECTIVE_BALANCE_INCREMENT  # Factored out from penalty numerator to avoid uint64 overflow
            penalty_numerator = validator.effective_balance // increment * adjusted_total_slashing_balance
            penalty = penalty_numerator // total_balance * increment
            decrease_balance(state, ValidatorIndex(index), penalty)
```

#### Participation flags updates

*Note*: The function `process_participation_flag_updates` is new.

```python
def process_participation_flag_updates(state: BeaconState) -> None:
    state.previous_epoch_participation = state.current_epoch_participation
    state.current_epoch_participation = [ParticipationFlags(0b0000_0000) for _ in range(len(state.validators))]
```

This function simply ensures that a new participation flags array gets initialized for each new epoch, and that the array for the current epoch becomes the array for the previous epoch when appropriate. The logic is the same to the logic of how `PendingAttestation` lists were updated at epoch boundaries pre-Altair.

#### Sync committee updates

*Note*: The function `process_sync_committee_updates` is new.

```python
def process_sync_committee_updates(state: BeaconState) -> None:
    next_epoch = get_current_epoch(state) + Epoch(1)
    if next_epoch % EPOCHS_PER_SYNC_COMMITTEE_PERIOD == 0:
        state.current_sync_committee = state.next_sync_committee
        state.next_sync_committee = get_sync_committee(state, next_epoch + EPOCHS_PER_SYNC_COMMITTEE_PERIOD)
```

When a new sync committee period starts, compute the committee 1 period in the future and save it in the state. Also, move the prior next committee into the position of the current committee (as with the start of a new period, the "next" committee _becomes_ the "current" committee).

## Initialize state for pure Altair testnets and test vectors

This helper function is only for initializing the state for pure Altair testnets and tests.

*Note*: The function `initialize_beacon_state_from_eth1` is modified: (1) using `ALTAIR_FORK_VERSION` as the current fork version, (2) utilizing the Altair `BeaconBlockBody` when constructing the initial `latest_block_header`, and (3) adding initial sync committees.

```python
def initialize_beacon_state_from_eth1(eth1_block_hash: Bytes32,
                                      eth1_timestamp: uint64,
                                      deposits: Sequence[Deposit]) -> BeaconState:
    fork = Fork(
        previous_version=GENESIS_FORK_VERSION,
        current_version=ALTAIR_FORK_VERSION,  # [Modified in Altair]
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

    # [New in Altair] Fill in sync committees
    state.current_sync_committee = get_sync_committee(state, get_current_epoch(state))
    state.next_sync_committee = get_sync_committee(state, get_current_epoch(state) + EPOCHS_PER_SYNC_COMMITTEE_PERIOD)

    return state
```

