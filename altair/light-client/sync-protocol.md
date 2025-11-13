# Altair Light Client -- Sync Protocol

<!-- mdformat-toc start --slug=github --no-anchors --maxlevel=6 --minlevel=2 -->

- [Introduction](#introduction)
- [Custom types](#custom-types)
- [Constants](#constants)
- [Preset](#preset)
  - [Misc](#misc)
- [Containers](#containers)
  - [`LightClientHeader`](#lightclientheader)
  - [`LightClientBootstrap`](#lightclientbootstrap)
  - [`LightClientUpdate`](#lightclientupdate)
  - [`LightClientFinalityUpdate`](#lightclientfinalityupdate)
  - [`LightClientOptimisticUpdate`](#lightclientoptimisticupdate)
  - [`LightClientStore`](#lightclientstore)
- [Helper functions](#helper-functions)
  - [`finalized_root_gindex_at_slot`](#finalized_root_gindex_at_slot)
  - [`current_sync_committee_gindex_at_slot`](#current_sync_committee_gindex_at_slot)
  - [`next_sync_committee_gindex_at_slot`](#next_sync_committee_gindex_at_slot)
  - [`is_valid_light_client_header`](#is_valid_light_client_header)
  - [`is_sync_committee_update`](#is_sync_committee_update)
  - [`is_finality_update`](#is_finality_update)
  - [`is_better_update`](#is_better_update)
  - [`is_next_sync_committee_known`](#is_next_sync_committee_known)
  - [`get_safety_threshold`](#get_safety_threshold)
  - [`get_subtree_index`](#get_subtree_index)
  - [`is_valid_normalized_merkle_branch`](#is_valid_normalized_merkle_branch)
  - [`compute_sync_committee_period_at_slot`](#compute_sync_committee_period_at_slot)
- [Light client initialization](#light-client-initialization)
  - [`initialize_light_client_store`](#initialize_light_client_store)
- [Light client state updates](#light-client-state-updates)
  - [`validate_light_client_update`](#validate_light_client_update)
  - [`apply_light_client_update`](#apply_light_client_update)
  - [`process_light_client_store_force_update`](#process_light_client_store_force_update)
  - [`process_light_client_update`](#process_light_client_update)
  - [`process_light_client_finality_update`](#process_light_client_finality_update)
  - [`process_light_client_optimistic_update`](#process_light_client_optimistic_update)

<!-- mdformat-toc end -->

## Introduction

The beacon chain is designed to be light client friendly for constrained
environments to access Ethereum with reasonable safety and liveness. Such
environments include resource-constrained devices (e.g. phones for
trust-minimized wallets) and metered VMs (e.g. blockchain VMs for cross-chain
bridges).

This document suggests a minimal light client design for the beacon chain that
uses sync committees introduced in
[this beacon chain extension](../beacon-chain.md).

Additional documents describe how the light client sync protocol can be used:

- [Full node](./full-node.md)
- [Light client](./light-client.md)
- [Networking](./p2p-interface.md)

<!-- NOTES-BEGIN -->

The **sync committee** is the "flagship feature" of the Altair hard fork. This is a committee of 512 validators that is randomly selected every **sync committee period (~1 day)**, and while a validator is part of the currently active sync committee they are expected to continually sign the block header that is the new head of the chain at each slot.

The purpose of the sync committee is to allow **light clients** to keep track of the chain of beacon block headers. The other two duties that involve signing block headers, block proposal and block attestation, do not work for this function because computing the proposer or attesters at a given slot requires a calculation on the entire active validator set, which light clients do not have access to (if they did, they would not be light!). Sync committees, on the other hand, are (i) updated infrequently, and (ii) saved directly in the beacon state, allowing light clients to verify the sync committee with a Merkle branch from a block header that they already know about, and use the public keys in the sync committee to directly authenticate signatures of more recent blocks.

This diagram shows the basic procedure by which a light client learns about more recent blocks:

![](lightsync.png)

We assume a light client already has a block header at slot `N`, in period `X = N // 16384`. The light client wants to authenticate a block header somewhere in period `X+1`. The steps the light client needs to take are as follows:

1. Use a Merkle branch to verify the `next_sync_committee` in the slot `N` post-state. This is the sync committee that will be signing block headers during period `X+1`.
2. Download the aggregate signature of the newer header that the light client is trying to authenticate. This can be found in the child block of the newer block, or the information could be grabbed directly from the p2p network.
3. Add together the public keys of the subset of the sync committee that participated in the aggregate signature (the bitfield in the signature will tell you who participated)
4. Verify the signature against the combined public key and the newer block header. If verification passes, the new block header has been successfully authenticated!

The minimum cost for light clients to track the chain is only about 25 kB per two days: 24576 bytes for the 512 48-byte public keys in the sync committee, plus a few hundred bytes for the aggregate signature, the light client header and the Merkle branch. Of course, closely following the chain at a high level of granularity does require more data bandwidth as you would have to download each header you're verifying (plus the signature for it).

The extremely low cost for light clients is intended to help make the beacon chain light client friendly for extremely constrained environments. Such environments include mobile phones, embedded IoT devices, in-browser wallets and other blockchains (for cross-chain bridges).

## Custom types

| Name                         | SSZ equivalent                                              | Description                                                       |
| ---------------------------- | ----------------------------------------------------------- | ----------------------------------------------------------------- |
| `FinalityBranch`             | `Vector[Bytes32, floorlog2(FINALIZED_ROOT_GINDEX)]`         | Merkle branch of `finalized_checkpoint.root` within `BeaconState` |
| `CurrentSyncCommitteeBranch` | `Vector[Bytes32, floorlog2(CURRENT_SYNC_COMMITTEE_GINDEX)]` | Merkle branch of `current_sync_committee` within `BeaconState`    |
| `NextSyncCommitteeBranch`    | `Vector[Bytes32, floorlog2(NEXT_SYNC_COMMITTEE_GINDEX)]`    | Merkle branch of `next_sync_committee` within `BeaconState`       |

## Constants

| Name                            | Value                                                                        |
| ------------------------------- | ---------------------------------------------------------------------------- |
| `FINALIZED_ROOT_GINDEX`         | `get_generalized_index(BeaconState, 'finalized_checkpoint', 'root')` (= 105) |
| `CURRENT_SYNC_COMMITTEE_GINDEX` | `get_generalized_index(BeaconState, 'current_sync_committee')` (= 54)        |
| `NEXT_SYNC_COMMITTEE_GINDEX`    | `get_generalized_index(BeaconState, 'next_sync_committee')` (= 55)           |

<!-- NOTES-BEGIN -->

These values are the [generalized indices](https://github.com/ethereum/eth2.0-specs/blob/dev/ssz/merkle-proofs.md#generalized-merkle-tree-index) for the finalized checkpoint and the next sync committee in a `BeaconState`. A generalized index is a way of referring to a position of an object in a Merkle tree, so that the Merkle proof verification algorithm knows what path to check the hashes against.

## Preset

### Misc

| Name                              | Value                                                | Unit       | Duration    |
| --------------------------------- | ---------------------------------------------------- | ---------- | ----------- |
| `MIN_SYNC_COMMITTEE_PARTICIPANTS` | `1`                                                  | validators |             |
| `UPDATE_TIMEOUT`                  | `SLOTS_PER_EPOCH * EPOCHS_PER_SYNC_COMMITTEE_PERIOD` | slots      | ~27.3 hours |

## Containers

### `LightClientHeader`

```python
class LightClientHeader(Container):
    beacon: BeaconBlockHeader
```

Future upgrades may introduce additional fields to this structure, and validate
them by extending
[`is_valid_light_client_header`](#is_valid_light_client_header).

### `LightClientBootstrap`

```python
class LightClientBootstrap(Container):
    # Header matching the requested beacon block root
    header: LightClientHeader
    # Current sync committee corresponding to `header.beacon.state_root`
    current_sync_committee: SyncCommittee
    current_sync_committee_branch: CurrentSyncCommitteeBranch
```

### `LightClientUpdate`

```python
class LightClientUpdate(Container):
    # Header attested to by the sync committee
    attested_header: LightClientHeader
    # Next sync committee corresponding to `attested_header.beacon.state_root`
    next_sync_committee: SyncCommittee
    next_sync_committee_branch: NextSyncCommitteeBranch
    # Finalized header corresponding to `attested_header.beacon.state_root`
    finalized_header: LightClientHeader
    finality_branch: FinalityBranch
    # Sync committee aggregate signature
    sync_aggregate: SyncAggregate
    # Slot at which the aggregate signature was created (untrusted)
    signature_slot: Slot
```

<!-- NOTES-BEGIN -->

A `LightClientUpdate` is an object passed over the wire (could be over a p2p network or through a client-server setup) which contains all of the information needed to convince a light client to accept a newer block header. The information included is:

* **`header`**: the header that the light client will accept if the `LightClientUpdate` is valid.
* **`next_sync_committee`**: if the `header` is in a newer sync committee period than the header in the light client's current `LightClientSnapshot`, then if the light client decides to accept this header it will need to know the new header's `next_sync_committee` so that it will be able to accept headers in even later periods. So the `LightClientUpdate` itself provides this sync committee.
* **`next_sync_committee_branch`**: the Merkle branch that authenticates the `next_sync_committee`
* **`finality_header`**: if nonempty, the header whose signature is being verified (if empty, the signature of the `header` itself is being verified)
* **`finality_branch`**: the Merkle branch that authenticates that the `header` actually is the header corresponding to the _finalized root_ saved in the `finality_header` (if the `finality_header` is empty, the `finality_branch` is empty too)
* **`sync_committee_bits`**: a bitfield showing who participated in the sync committee
* **`sync_committee_signature`**: the signature
* **`fork_version`**: needed to mix in to the data being signed (will be different across different hard forks and between mainnet and testnets)

### `LightClientFinalityUpdate`

```python
class LightClientFinalityUpdate(Container):
    # Header attested to by the sync committee
    attested_header: LightClientHeader
    # Finalized header corresponding to `attested_header.beacon.state_root`
    finalized_header: LightClientHeader
    finality_branch: FinalityBranch
    # Sync committee aggregate signature
    sync_aggregate: SyncAggregate
    # Slot at which the aggregate signature was created (untrusted)
    signature_slot: Slot
```

### `LightClientOptimisticUpdate`

```python
class LightClientOptimisticUpdate(Container):
    # Header attested to by the sync committee
    attested_header: LightClientHeader
    # Sync committee aggregate signature
    sync_aggregate: SyncAggregate
    # Slot at which the aggregate signature was created (untrusted)
    signature_slot: Slot
```

### `LightClientStore`

```python
@dataclass
class LightClientStore(object):
    # Header that is finalized
    finalized_header: LightClientHeader
    # Sync committees corresponding to the finalized header
    current_sync_committee: SyncCommittee
    next_sync_committee: SyncCommittee
    # Best available header to switch finalized head to if we see nothing else
    best_valid_update: Optional[LightClientUpdate]
    # Most recent available reasonably-safe header
    optimistic_header: LightClientHeader
    # Max number of active participants in a sync committee (used to calculate safety threshold)
    previous_max_active_participants: uint64
    current_max_active_participants: uint64
```

<!-- NOTES-BEGIN -->

The `LightClientStore` is the _full_ "state" of a light client, and includes:

* A `snapshot`, reflecting a block header that a light client accepts as **finalized** (note: this is a different, and usually weaker, notion of finality than beacon chain finality). The sync committees in the state of this header are used to authenticate any new incoming headers.
* A list of `valid_updates`, reflecting _speculative_ recent block headers (that is: recent block headers that have strong support, and will _probably_ continue to be part of the chain, but still have some small risk of being reverted)

The `snapshot` can be updated in two ways:

1. If the light client sees a valid `LightClientUpdate` containing a `finality_header`, and with at least 2/3 of the sync committee participating, it accepts the `update.header` as the new snapshot header. Note that the light client uses the signature to verify `update.finality_header` (which would in practice often be one of the most recent blocks, and not yet finalized), and then uses the Merkle branch _from_ the `update.finality_header` _to_ the finalized checkpoint in its post-state to verify the `update.header`. If `update.finality_header` is a valid block, then `update.header` actually is finalized.
2. If the light client sees no valid updates via method (1) for a sufficiently long duration (specifically, the length of one sync committee period), it simply accepts the speculative header in `valid_updates` with the most signatures as finalized.

(2) allows the light client to keep advancing even during periods of extended non-finality, though at the cost that during a long non-finality period the light client's safety is vulnerable to network latency of ~1 day (full clients' safety is only vulnerable to network latency on the order of weeks).

## Helper functions

### `finalized_root_gindex_at_slot`

```python
def finalized_root_gindex_at_slot(_slot: Slot) -> GeneralizedIndex:
    return FINALIZED_ROOT_GINDEX
```

### `current_sync_committee_gindex_at_slot`

```python
def current_sync_committee_gindex_at_slot(_slot: Slot) -> GeneralizedIndex:
    return CURRENT_SYNC_COMMITTEE_GINDEX
```

### `next_sync_committee_gindex_at_slot`

```python
def next_sync_committee_gindex_at_slot(_slot: Slot) -> GeneralizedIndex:
    return NEXT_SYNC_COMMITTEE_GINDEX
```

### `is_valid_light_client_header`

```python
def is_valid_light_client_header(_header: LightClientHeader) -> bool:
    return True
```

### `is_sync_committee_update`

```python
def is_sync_committee_update(update: LightClientUpdate) -> bool:
    return update.next_sync_committee_branch != NextSyncCommitteeBranch()
```

### `is_finality_update`

```python
def is_finality_update(update: LightClientUpdate) -> bool:
    return update.finality_branch != FinalityBranch()
```

### `is_better_update`

```python
def is_better_update(new_update: LightClientUpdate, old_update: LightClientUpdate) -> bool:
    # Compare supermajority (> 2/3) sync committee participation
    max_active_participants = len(new_update.sync_aggregate.sync_committee_bits)
    new_num_active_participants = sum(new_update.sync_aggregate.sync_committee_bits)
    old_num_active_participants = sum(old_update.sync_aggregate.sync_committee_bits)
    new_has_supermajority = new_num_active_participants * 3 >= max_active_participants * 2
    old_has_supermajority = old_num_active_participants * 3 >= max_active_participants * 2
    if new_has_supermajority != old_has_supermajority:
        return new_has_supermajority
    if not new_has_supermajority and new_num_active_participants != old_num_active_participants:
        return new_num_active_participants > old_num_active_participants

    # Compare presence of relevant sync committee
    new_has_relevant_sync_committee = is_sync_committee_update(new_update) and (
        compute_sync_committee_period_at_slot(new_update.attested_header.beacon.slot)
        == compute_sync_committee_period_at_slot(new_update.signature_slot)
    )
    old_has_relevant_sync_committee = is_sync_committee_update(old_update) and (
        compute_sync_committee_period_at_slot(old_update.attested_header.beacon.slot)
        == compute_sync_committee_period_at_slot(old_update.signature_slot)
    )
    if new_has_relevant_sync_committee != old_has_relevant_sync_committee:
        return new_has_relevant_sync_committee

    # Compare indication of any finality
    new_has_finality = is_finality_update(new_update)
    old_has_finality = is_finality_update(old_update)
    if new_has_finality != old_has_finality:
        return new_has_finality

    # Compare sync committee finality
    if new_has_finality:
        new_has_sync_committee_finality = compute_sync_committee_period_at_slot(
            new_update.finalized_header.beacon.slot
        ) == compute_sync_committee_period_at_slot(new_update.attested_header.beacon.slot)
        old_has_sync_committee_finality = compute_sync_committee_period_at_slot(
            old_update.finalized_header.beacon.slot
        ) == compute_sync_committee_period_at_slot(old_update.attested_header.beacon.slot)
        if new_has_sync_committee_finality != old_has_sync_committee_finality:
            return new_has_sync_committee_finality

    # Tiebreaker 1: Sync committee participation beyond supermajority
    if new_num_active_participants != old_num_active_participants:
        return new_num_active_participants > old_num_active_participants

    # Tiebreaker 2: Prefer older data (fewer changes to best)
    if new_update.attested_header.beacon.slot != old_update.attested_header.beacon.slot:
        return new_update.attested_header.beacon.slot < old_update.attested_header.beacon.slot

    # Tiebreaker 3: Prefer updates with earlier signature slots
    return new_update.signature_slot < old_update.signature_slot
```

### `is_next_sync_committee_known`

```python
def is_next_sync_committee_known(store: LightClientStore) -> bool:
    return store.next_sync_committee != SyncCommittee()
```

### `get_safety_threshold`

```python
def get_safety_threshold(store: LightClientStore) -> uint64:
    return (
        max(
            store.previous_max_active_participants,
            store.current_max_active_participants,
        )
        // 2
    )
```

### `get_subtree_index`

```python
def get_subtree_index(generalized_index: GeneralizedIndex) -> uint64:
    return uint64(generalized_index % 2 ** (floorlog2(generalized_index)))
```

<!-- NOTES-BEGIN -->

From a generalized index, return an integer whose bits, in least-to-greatest-place-value order, represent the Merkle path (0 = "left", 1 = "right", going from bottom to top) to get from a leaf to the root of a tree. Passed into the Merkle tree verification function used in other parts of the beacon chain spec.

### `is_valid_normalized_merkle_branch`

```python
def is_valid_normalized_merkle_branch(
    leaf: Bytes32, branch: Sequence[Bytes32], gindex: GeneralizedIndex, root: Root
) -> bool:
    depth = floorlog2(gindex)
    index = get_subtree_index(gindex)
    num_extra = len(branch) - depth
    for i in range(num_extra):
        if branch[i] != Bytes32():
            return False
    return is_valid_merkle_branch(leaf, branch[num_extra:], depth, index, root)
```

### `compute_sync_committee_period_at_slot`

```python
def compute_sync_committee_period_at_slot(slot: Slot) -> uint64:
    return compute_sync_committee_period(compute_epoch_at_slot(slot))
```

## Light client initialization

A light client maintains its state in a `store` object of type
`LightClientStore`. `initialize_light_client_store` initializes a new `store`
with a received `LightClientBootstrap` derived from a given
`trusted_block_root`.

### `initialize_light_client_store`

```python
def initialize_light_client_store(
    trusted_block_root: Root, bootstrap: LightClientBootstrap
) -> LightClientStore:
    assert is_valid_light_client_header(bootstrap.header)
    assert hash_tree_root(bootstrap.header.beacon) == trusted_block_root

    assert is_valid_normalized_merkle_branch(
        leaf=hash_tree_root(bootstrap.current_sync_committee),
        branch=bootstrap.current_sync_committee_branch,
        gindex=current_sync_committee_gindex_at_slot(bootstrap.header.beacon.slot),
        root=bootstrap.header.beacon.state_root,
    )

    return LightClientStore(
        finalized_header=bootstrap.header,
        current_sync_committee=bootstrap.current_sync_committee,
        next_sync_committee=SyncCommittee(),
        best_valid_update=None,
        optimistic_header=bootstrap.header,
        previous_max_active_participants=0,
        current_max_active_participants=0,
    )
```

## Light client state updates

- A light client receives objects of type `LightClientUpdate`,
  `LightClientFinalityUpdate` and `LightClientOptimisticUpdate`:
  - **`update: LightClientUpdate`**: Every `update` triggers
    `process_light_client_update(store, update, current_slot, genesis_validators_root)`
    where `current_slot` is the current slot based on a local clock.
  - **`finality_update: LightClientFinalityUpdate`**: Every `finality_update`
    triggers
    `process_light_client_finality_update(store, finality_update, current_slot, genesis_validators_root)`.
  - **`optimistic_update: LightClientOptimisticUpdate`**: Every
    `optimistic_update` triggers
    `process_light_client_optimistic_update(store, optimistic_update, current_slot, genesis_validators_root)`.
- `process_light_client_store_force_update` MAY be called based on use case
  dependent heuristics if light client sync appears stuck.

<!-- NOTES-BEGIN -->

A light client maintains its state in a `store` object of type `LightClientStore` and receives `update` objects of type `LightClientUpdate`. Every `update` triggers `process_light_client_update(store, update, current_slot)` where `current_slot` is the current slot based on some local clock.

### `validate_light_client_update`

```python
def validate_light_client_update(
    store: LightClientStore,
    update: LightClientUpdate,
    current_slot: Slot,
    genesis_validators_root: Root,
) -> None:
    # Verify sync committee has sufficient participants
    sync_aggregate = update.sync_aggregate
    assert sum(sync_aggregate.sync_committee_bits) >= MIN_SYNC_COMMITTEE_PARTICIPANTS

    # Verify update does not skip a sync committee period
    assert is_valid_light_client_header(update.attested_header)
    update_attested_slot = update.attested_header.beacon.slot
    update_finalized_slot = update.finalized_header.beacon.slot
    assert current_slot >= update.signature_slot > update_attested_slot >= update_finalized_slot
    store_period = compute_sync_committee_period_at_slot(store.finalized_header.beacon.slot)
    update_signature_period = compute_sync_committee_period_at_slot(update.signature_slot)
    if is_next_sync_committee_known(store):
        assert update_signature_period in (store_period, store_period + 1)
    else:
        assert update_signature_period == store_period

    # Verify update is relevant
    update_attested_period = compute_sync_committee_period_at_slot(update_attested_slot)
    update_has_next_sync_committee = not is_next_sync_committee_known(store) and (
        is_sync_committee_update(update) and update_attested_period == store_period
    )
    assert (
        update_attested_slot > store.finalized_header.beacon.slot or update_has_next_sync_committee
    )

    # Verify that the `finality_branch`, if present, confirms `finalized_header`
    # to match the finalized checkpoint root saved in the state of `attested_header`.
    # Note that the genesis finalized checkpoint root is represented as a zero hash.
    if not is_finality_update(update):
        assert update.finalized_header == LightClientHeader()
    else:
        if update_finalized_slot == GENESIS_SLOT:
            assert update.finalized_header == LightClientHeader()
            finalized_root = Bytes32()
        else:
            assert is_valid_light_client_header(update.finalized_header)
            finalized_root = hash_tree_root(update.finalized_header.beacon)
        assert is_valid_normalized_merkle_branch(
            leaf=finalized_root,
            branch=update.finality_branch,
            gindex=finalized_root_gindex_at_slot(update.attested_header.beacon.slot),
            root=update.attested_header.beacon.state_root,
        )

    # Verify that the `next_sync_committee`, if present, actually is the next sync committee saved in the
    # state of the `attested_header`
    if not is_sync_committee_update(update):
        assert update.next_sync_committee == SyncCommittee()
    else:
        if update_attested_period == store_period and is_next_sync_committee_known(store):
            assert update.next_sync_committee == store.next_sync_committee
        assert is_valid_normalized_merkle_branch(
            leaf=hash_tree_root(update.next_sync_committee),
            branch=update.next_sync_committee_branch,
            gindex=next_sync_committee_gindex_at_slot(update.attested_header.beacon.slot),
            root=update.attested_header.beacon.state_root,
        )

    # Verify sync committee aggregate signature
    if update_signature_period == store_period:
        sync_committee = store.current_sync_committee
    else:
        sync_committee = store.next_sync_committee
    participant_pubkeys = [
        pubkey
        for (bit, pubkey) in zip(sync_aggregate.sync_committee_bits, sync_committee.pubkeys)
        if bit
    ]
    fork_version_slot = max(update.signature_slot, Slot(1)) - Slot(1)
    fork_version = compute_fork_version(compute_epoch_at_slot(fork_version_slot))
    domain = compute_domain(DOMAIN_SYNC_COMMITTEE, fork_version, genesis_validators_root)
    signing_root = compute_signing_root(update.attested_header.beacon, domain)
    assert bls.FastAggregateVerify(
        participant_pubkeys, signing_root, sync_aggregate.sync_committee_signature
    )
```

<!-- NOTES-BEGIN -->

This function has 5 parts:

1. **Basic validation**: confirm that the `update.header` is newer than the snapshot header, and that it does not skip more than 1 sync committee period.
2. **Verify Merkle branch of header** - confirm that the `update.header` actually is the header that corresponds to the finalized root in the post-state of `update.finality_header` (and so if the `update.finality_header` is valid, the `update.header` is finalized). This check is only done if the `update.finality_header` is provided.
3. **Verify Merkle branch of sync committee** - if the `update.header` is in a newer sync period than the snapshot header, check that the `next_sync_committee` provided in the snapshot is correct by verifying the Merkle branch (if the `update.header` is not in a newer sync period, it's ok to leave the `next_sync_committee` empty).
4. **More basic validation**: confirm that the sync committee has more than zero participants.
5. **Verify the signature**: remember that if the `update.finality_header` is provided, the signature that we are expecting is a valid signature of the `update.finality_header`; otherwise, we are expecting a valid signature of the `update.header`.

### `apply_light_client_update`

```python
def apply_light_client_update(store: LightClientStore, update: LightClientUpdate) -> None:
    store_period = compute_sync_committee_period_at_slot(store.finalized_header.beacon.slot)
    update_finalized_period = compute_sync_committee_period_at_slot(
        update.finalized_header.beacon.slot
    )
    if not is_next_sync_committee_known(store):
        assert update_finalized_period == store_period
        store.next_sync_committee = update.next_sync_committee
    elif update_finalized_period == store_period + 1:
        store.current_sync_committee = store.next_sync_committee
        store.next_sync_committee = update.next_sync_committee
        store.previous_max_active_participants = store.current_max_active_participants
        store.current_max_active_participants = 0
    if update.finalized_header.beacon.slot > store.finalized_header.beacon.slot:
        store.finalized_header = update.finalized_header
        if store.finalized_header.beacon.slot > store.optimistic_header.beacon.slot:
            store.optimistic_header = store.finalized_header
```

<!-- NOTES-BEGIN -->

This function is called only when it is time to update that snapshot header: either (1) when a new header is provided that corresponds to a finalized checkpoint of another header, or (2) after the timeout. In addition to simply updating the header, we also update the sync committees in the snapshot.

### `process_light_client_store_force_update`

```python
def process_light_client_store_force_update(store: LightClientStore, current_slot: Slot) -> None:
    if (
        current_slot > store.finalized_header.beacon.slot + UPDATE_TIMEOUT
        and store.best_valid_update is not None
    ):
        # Forced best update when the update timeout has elapsed.
        # Because the apply logic waits for `finalized_header.beacon.slot` to indicate sync committee finality,
        # the `attested_header` may be treated as `finalized_header` in extended periods of non-finality
        # to guarantee progression into later sync committee periods according to `is_better_update`.
        if (
            store.best_valid_update.finalized_header.beacon.slot
            <= store.finalized_header.beacon.slot
        ):
            store.best_valid_update.finalized_header = store.best_valid_update.attested_header
        apply_light_client_update(store, store.best_valid_update)
        store.best_valid_update = None
```

### `process_light_client_update`

```python
def process_light_client_update(
    store: LightClientStore,
    update: LightClientUpdate,
    current_slot: Slot,
    genesis_validators_root: Root,
) -> None:
    validate_light_client_update(store, update, current_slot, genesis_validators_root)

    sync_committee_bits = update.sync_aggregate.sync_committee_bits

    # Update the best update in case we have to force-update to it if the timeout elapses
    if store.best_valid_update is None or is_better_update(update, store.best_valid_update):
        store.best_valid_update = update

    # Track the maximum number of active participants in the committee signatures
    store.current_max_active_participants = max(
        store.current_max_active_participants,
        sum(sync_committee_bits),
    )

    # Update the optimistic header
    if (
        sum(sync_committee_bits) > get_safety_threshold(store)
        and update.attested_header.beacon.slot > store.optimistic_header.beacon.slot
    ):
        store.optimistic_header = update.attested_header

    # Update finalized header
    update_has_finalized_next_sync_committee = (
        not is_next_sync_committee_known(store)
        and is_sync_committee_update(update)
        and is_finality_update(update)
        and (
            compute_sync_committee_period_at_slot(update.finalized_header.beacon.slot)
            == compute_sync_committee_period_at_slot(update.attested_header.beacon.slot)
        )
    )
    if sum(sync_committee_bits) * 3 >= len(sync_committee_bits) * 2 and (
        update.finalized_header.beacon.slot > store.finalized_header.beacon.slot
        or update_has_finalized_next_sync_committee
    ):
        # Normal update through 2/3 threshold
        apply_light_client_update(store, update)
        store.best_valid_update = None
```

<!-- NOTES-BEGIN -->

The main function for processing a light client update. We first validate that it is correct; if it is correct, we at the very least save it as a speculative update. We then check if one of the two conditions for updating the snapshot is satisfied; if it is, then we update the snapshot.
### `process_light_client_finality_update`

```python
def process_light_client_finality_update(
    store: LightClientStore,
    finality_update: LightClientFinalityUpdate,
    current_slot: Slot,
    genesis_validators_root: Root,
) -> None:
    update = LightClientUpdate(
        attested_header=finality_update.attested_header,
        next_sync_committee=SyncCommittee(),
        next_sync_committee_branch=NextSyncCommitteeBranch(),
        finalized_header=finality_update.finalized_header,
        finality_branch=finality_update.finality_branch,
        sync_aggregate=finality_update.sync_aggregate,
        signature_slot=finality_update.signature_slot,
    )
    process_light_client_update(store, update, current_slot, genesis_validators_root)
```

### `process_light_client_optimistic_update`

```python
def process_light_client_optimistic_update(
    store: LightClientStore,
    optimistic_update: LightClientOptimisticUpdate,
    current_slot: Slot,
    genesis_validators_root: Root,
) -> None:
    update = LightClientUpdate(
        attested_header=optimistic_update.attested_header,
        next_sync_committee=SyncCommittee(),
        next_sync_committee_branch=NextSyncCommitteeBranch(),
        finalized_header=LightClientHeader(),
        finality_branch=FinalityBranch(),
        sync_aggregate=optimistic_update.sync_aggregate,
        signature_slot=optimistic_update.signature_slot,
    )
    process_light_client_update(store, update, current_slot, genesis_validators_root)
```
