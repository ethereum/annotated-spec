# Ethereum 2.0 Phase 0 -- Beacon Chain Fork Choice

**Notice**: This document was written in Aug 2020.

## Table of contents
<!-- TOC -->
<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->


- [Introduction](#introduction)
- [Fork choice](#fork-choice)
  - [Configuration](#configuration)
  - [Helpers](#helpers)
    - [`LatestMessage`](#latestmessage)
    - [`Store`](#store)
    - [`get_forkchoice_store`](#get_forkchoice_store)
    - [`get_slots_since_genesis`](#get_slots_since_genesis)
    - [`get_current_slot`](#get_current_slot)
    - [`compute_slots_since_epoch_start`](#compute_slots_since_epoch_start)
    - [`get_ancestor`](#get_ancestor)
    - [`get_latest_attesting_balance`](#get_latest_attesting_balance)
    - [`filter_block_tree`](#filter_block_tree)
    - [`get_filtered_block_tree`](#get_filtered_block_tree)
    - [`get_head`](#get_head)
    - [`should_update_justified_checkpoint`](#should_update_justified_checkpoint)
    - [`on_attestation` helpers](#on_attestation-helpers)
      - [`validate_on_attestation`](#validate_on_attestation)
      - [`store_target_checkpoint_state`](#store_target_checkpoint_state)
      - [`update_latest_messages`](#update_latest_messages)
  - [Handlers](#handlers)
    - [`on_tick`](#on_tick)
    - [`on_block`](#on_block)
    - [`on_attestation`](#on_attestation)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->
<!-- /TOC -->

## Introduction

This document is the beacon chain **fork choice rule** specification, part of Ethereum 2.0 Phase 0. It describes the mechanism for how to choose what is the "canonical" chain in the event that there are multiple competing chains that disagree with each other. All blockchains have the possibility of temporary disagreement, either because of malicious behavior (eg. a block proposer publishing two different blocks at the same time), or just network latency (eg. a block being delayed by a few seconds, causing it to be broadcasted around the same time as the _next_ block that gets published by someone else). In such cases, some mechanism is needed to choose which of the two (or more) chains represents the "actual" history and state of the system (this chain is called the **canonical chain**).

PoW chains (Bitcoin, Ethereum 1.0, etc) typically use some variant of the **longest chain rule**: if there is a disagreement between chains, pick the chain that is the longest.

![](https://vitalik.ca/files/posts_files/cbc-casper-files/Chain3.png)

In practice, "[total difficulty](https://ethereum.stackexchange.com/questions/7068/difficulty-and-total-difficulty)" is used instead of length, though for most intuitive analysis, thinking about length is typically sufficient. PoS chains can also use the longest chain rule; however, PoS opens the door to much better fork choice rules that provide much stronger properties than the longest chain rule.

The fork choice rule can be viewed as being part of the **consensus algorithm**, the other part of the consensus algorithm being the rules that determine what messages each participant should send to the network (see the [honest validator doc](https://github.com/ethereum/eth2.0-specs/blob/dev/specs/phase0/validator.md#beacon-chain-responsibilities) for more info). In eth2, the consensus algorithm is Casper FFG + LMD GHOST, sometimes called [Gasper](https://arxiv.org/abs/2003.03052).

* See here for the original paper describing Casper FFG: https://arxiv.org/abs/1710.09437
* See here for a description of LMD GHOST (ignore the section on detecting finality, as that is specific to Casper CBC, whereas the fork choice rule is shared between CBC and FFG): https://vitalik.ca/general/2018/12/05/cbc_casper.html

The goal of Casper FFG and LMD GHOST is to combine together the benefits of two major types of PoS design: **longest-chain-based** (or Nakamoto-based), as used by Peercoin, NXT, [Ouroboros](https://cardano.org/ouroboros/) and many other designs, and **traditional BFT based**, as used by [Tendermint](https://tendermint.com/docs/introduction/what-is-tendermint.html) and others. Longest chain systems have the benefit that they are low-overhead, even with a very high number of participants. Traditional BFT systems have the key benefit that they have a concept of **finality**: once a block is **finalized**, it can no longer be reverted, no matter what other participants in the network do. If >1/3 of participants in the network behave maliciously, different nodes could be tricked into accepting different conflicting blocks as finalized. However, to cause such a situation, those participants would have to misbehave in a very unambiguous and provable way, allowing them to be **slashed** (all their coins taken away as a penalty), making attacks extremely expensive. Additionally, traditional BFT systems reach finality quickly, though at the cost of high overhead and a low maximum participant count.

Eth2 combines together the advantages of both. It includes a traditional-BFT-inspired finality system (Casper FFG), though running at a rate of ~13 minutes per cycle (note: time to finality = 2 epochs = 2 * 32 * 12 sec) instead of a few seconds per cycle, allowing potentially over a million participants. To progress the chain between these epochs, LMD GHOST is used.

![](https://vitalik.ca/files/posts_files/cbc-casper-files/Chain7.png)

The core idea of LMD GHOST is that at each fork, instead of choosing the side that contains a longer chain, we choose the side that has more total support from validators, counting only the most recent message of each validator as support. This is heavily inspired by [Zohar and Sompolinsky's original GHOST paper](https://eprint.iacr.org/2013/881), but it adapts the design from its original PoW context to our new PoS context. LMD GHOST is powerful because it easily generalizes to much more than one "vote" being sent in parallel.

This is a very valuable feature for us, because Casper FFG already requires every validator to send one message per epoch, meaning that hundreds of messages are already being sent every second. We piggyback on those messages and ask them to include additional information voting on the current head of the chain. The result of this is that when a block is published, within seconds there are hundreds of signed messages from validators (**attestations**) confirming the block, and after even one slot (12 seconds) it's very difficult to revert a block. Anyone seeking even stronger ironclad confirmation can simply wait for finality after two epochs.

The approximate approach that we take to combining Casper FFG and LMD GHOST is:

1. Use the Casper FFG rules to compute finalized blocks. If a block finalizes, all future canonical chains must pass through this block.
2. Use the Casper FFG rules to keep track of the **latest justified block** (LJB) that is a descendant of the latest accepted finalized block.
3. Use the LMD GHOST rules, starting from the LJB as a root, to compute the chain head.

This combination, particularly rule (2), is implemented to ensure that new blocks that validators create by following the rules actually will continually finalize new blocks with Casper FFG, even if temporary exceptional situations (eg. involving attacks or extremely high network latency) take place.

Note also that Casper FFG only deals with **checkpoints**, or blocks right before the boundary of an epoch. There is thus a **checkpoint tree** that can be viewed as a [graph minor](https://en.wikipedia.org/wiki/Graph_minor) of the block tree, where checkpoint C1 is a parent of checkpoint C2 if block C1 is the ancestor of C2 in the block tree that is at the end of the epoch before the epoch of C2. Note that for convenience, we think about (block, slot) pairs, not blocks; the difference is that if the chain skips a slot because some block proposer is offline, the (block, slot) tree still includes a distinct member for each slot in between two blocks, making it easier to reason about the data structure.

Now, let's go through the specification...

## Fork choice

One important thing to note is that the fork choice _is not a pure function_; that is, what you accept as a canonical chain does not depend just on what data you also have, but also when you received it. The main reason this is done is to enforce finality: if you accept a block as finalized, then you will never revert it, even if you later see a conflicting block as finalized. Such a situation would only happen in cases where there is an active >1/3 attack on the chain; in such cases, we expect extra-protocol measures to be required to get all clients back on the same chain. There are also other deviations from purity, particularly a "sticky" choice of latest justified checkpoint, where the latest justified checkpoint can only change near the beginning of an epoch; this is done to prevent certain kinds of "bouncing attacks".

We implement this fork choice by defining a `store` that contains received fork-choice-relevant information, as well as some "memory variables", and a function `get_head(store)`.

At genesis, let `store = get_forkchoice_store(genesis_state)` and update `store` by running:

- `on_tick(store, time)` whenever `time > store.time` where `time` is the current Unix time
- `on_block(store, block)` whenever a block `block: SignedBeaconBlock` is received
- `on_attestation(store, attestation)` whenever an attestation `attestation` is received

Any of the above handlers that trigger an unhandled exception (e.g. a failed assert or an out-of-range list access) are considered invalid. Invalid calls to handlers must not modify `store`.

*Notes*:

1) **Leap seconds**: Slots will last `SECONDS_PER_SLOT + 1` or `SECONDS_PER_SLOT - 1` seconds around leap seconds. This is automatically handled by [UNIX time](https://en.wikipedia.org/wiki/Unix_time).
2) **Honest clocks**: Honest nodes are assumed to have clocks synchronized within `SECONDS_PER_SLOT` seconds of each other.
3) **Eth1 data**: The large `ETH1_FOLLOW_DISTANCE` specified in the [honest validator document](./validator.md) should ensure that `state.latest_eth1_data` of the canonical Ethereum 2.0 chain remains consistent with the canonical Ethereum 1.0 chain. If not, emergency manual intervention will be required.
4) **Manual forks**: Manual forks may arbitrarily change the fork choice rule but are expected to be enacted at epoch transitions, with the fork details reflected in `state.fork`.
5) **Implementation**: The implementation found in this specification is constructed for ease of understanding rather than for optimization in computation, space, or any other resource. A number of optimized alternatives can be found [here](https://github.com/protolambda/lmd-ghost).

### Configuration

| Name | Value | Unit | Duration |
| - | - | :-: | :-: |
| `SAFE_SLOTS_TO_UPDATE_JUSTIFIED` | `2**3` (= 8) | slots | 96 seconds |

The justified checkpoint can only be changed in the first 8 slots of an epoch; see below for reasoning why this is done.

### Helpers

Here, we define the data structure for the `store`. It only has one new subtype, the `LatestMessage` (the vote in the latest [meaning highest-epoch] valid attestation received from a validator).

#### `LatestMessage`

```python
@dataclass(eq=True, frozen=True)
class LatestMessage(object):
    epoch: Epoch
    root: Root
```

#### `Store`

```python
@dataclass
class Store(object):
    time: uint64
    genesis_time: uint64
    justified_checkpoint: Checkpoint
    finalized_checkpoint: Checkpoint
    best_justified_checkpoint: Checkpoint
    blocks: Dict[Root, BeaconBlock] = field(default_factory=dict)
    block_states: Dict[Root, BeaconState] = field(default_factory=dict)
    checkpoint_states: Dict[Checkpoint, BeaconState] = field(default_factory=dict)
    latest_messages: Dict[ValidatorIndex, LatestMessage] = field(default_factory=dict)
```

#### `get_forkchoice_store`

This function initializes the `store` given a particular block that the fork choice would start from. This should be the most recent finalized block that the client knows about from extra-protocol sources; at the beginning, it would just be the genesis.

*Note* With regards to fork choice, block headers are interchangeable with blocks. The spec is likely to move to headers for reduced overhead in test vectors and better encapsulation. Full implementations store blocks as part of their database and will often use full blocks when dealing with production fork choice.

_The block for `anchor_root` is incorrectly initialized to the block header, rather than the full block. This does not affect functionality but will be cleaned up in subsequent releases._

```python
def get_forkchoice_store(anchor_state: BeaconState) -> Store:
    anchor_block_header = copy(anchor_state.latest_block_header)
    if anchor_block_header.state_root == Bytes32():
        anchor_block_header.state_root = hash_tree_root(anchor_state)
    anchor_root = hash_tree_root(anchor_block_header)
    anchor_epoch = get_current_epoch(anchor_state)
    justified_checkpoint = Checkpoint(epoch=anchor_epoch, root=anchor_root)
    finalized_checkpoint = Checkpoint(epoch=anchor_epoch, root=anchor_root)
    return Store(
        time=uint64(anchor_state.genesis_time + SECONDS_PER_SLOT * anchor_state.slot),
        genesis_time=anchor_state.genesis_time,
        justified_checkpoint=justified_checkpoint,
        finalized_checkpoint=finalized_checkpoint,
        best_justified_checkpoint=justified_checkpoint,
        blocks={anchor_root: anchor_block_header},
        block_states={anchor_root: copy(anchor_state)},
        checkpoint_states={justified_checkpoint: copy(anchor_state)},
    )
```

#### `get_slots_since_genesis`

```python
def get_slots_since_genesis(store: Store) -> int:
    return (store.time - store.genesis_time) // SECONDS_PER_SLOT
```

#### `get_current_slot`

```python
def get_current_slot(store: Store) -> Slot:
    return Slot(GENESIS_SLOT + get_slots_since_genesis(store))
```

#### `compute_slots_since_epoch_start`

```python
def compute_slots_since_epoch_start(slot: Slot) -> int:
    return slot - compute_start_slot_at_epoch(compute_epoch_at_slot(slot))
```

Compute which slot of the current epoch we are in (returns 0...31).

#### `get_ancestor`

```python
def get_ancestor(store: Store, root: Root, slot: Slot) -> Root:
    block = store.blocks[root]
    if block.slot > slot:
        return get_ancestor(store, block.parent_root, slot)
    elif block.slot == slot:
        return root
    else:
        # root is older than queried slot, thus a skip slot. Return most recent root prior to slot
        return root
```

Get the ancestor of block `root` (we refer to all blocks by their root in the fork choice spec) at the given `slot` (eg. if `root` was at slot 105 and `slot = 100`, and the chain has no skipped slots in between, it would return the block's fifth ancestor).

#### `get_latest_attesting_balance`

```python
def get_latest_attesting_balance(store: Store, root: Root) -> Gwei:
    state = store.checkpoint_states[store.justified_checkpoint]
    active_indices = get_active_validator_indices(state, get_current_epoch(state))
    return Gwei(sum(
        state.validators[i].effective_balance for i in active_indices
        if (i in store.latest_messages
            and get_ancestor(store, store.latest_messages[i].root, store.blocks[root].slot) == root)
    ))
```

Get the total ETH attesting to a given block or its descendants, considering only latest attestations and active validators. This is the main function that is used to choose between two children of a block in LMD GHOST. Recall the diagram from above:

![](https://vitalik.ca/files/posts_files/cbc-casper-files/Chain7.png)

In this diagram, we assume that each of the last five block proposals (the blue ones) carries one attestation, which specifies that block as the head, and we assume each block is created by a different validator, and all validators have the same deposit size. The number in each square represents the latest attesting balance of that block. In eth2, blocks and attestations are separate, and there will be hundreds of attestations supporting each block, but otherwise the principle is the same.

#### `filter_block_tree`

Here, we implement an important but subtle deviation from the "LMD GHOST starting from the last justified block" rule mentioned above

[To be completed]

See [section 4.6 of the Gasper paper](https://arxiv.org/pdf/2003.03052.pdf) for more details.

```python
def filter_block_tree(store: Store, block_root: Root, blocks: Dict[Root, BeaconBlock]) -> bool:
    block = store.blocks[block_root]
    children = [
        root for root in store.blocks.keys()
        if store.blocks[root].parent_root == block_root
    ]

    # If any children branches contain expected finalized/justified checkpoints,
    # add to filtered block-tree and signal viability to parent.
    if any(children):
        filter_block_tree_result = [filter_block_tree(store, child, blocks) for child in children]
        if any(filter_block_tree_result):
            blocks[block_root] = block
            return True
        return False

    # If leaf block, check finalized/justified checkpoints as matching latest.
    head_state = store.block_states[block_root]

    correct_justified = (
        store.justified_checkpoint.epoch == GENESIS_EPOCH
        or head_state.current_justified_checkpoint == store.justified_checkpoint
    )
    correct_finalized = (
        store.finalized_checkpoint.epoch == GENESIS_EPOCH
        or head_state.finalized_checkpoint == store.finalized_checkpoint
    )
    # If expected finalized/justified, add to viable block-tree and signal viability to parent.
    if correct_justified and correct_finalized:
        blocks[block_root] = block
        return True

    # Otherwise, branch not viable
    return False
```

#### `get_filtered_block_tree`

```python
def get_filtered_block_tree(store: Store) -> Dict[Root, BeaconBlock]:
    """
    Retrieve a filtered block tree from ``store``, only returning branches
    whose leaf state's justified/finalized info agrees with that in ``store``.
    """
    base = store.justified_checkpoint.root
    blocks: Dict[Root, BeaconBlock] = {}
    filter_block_tree(store, base, blocks)
    return blocks
```

#### `get_head`

```python
def get_head(store: Store) -> Root:
    # Get filtered block tree that only includes viable branches
    blocks = get_filtered_block_tree(store)
    # Execute the LMD-GHOST fork choice
    head = store.justified_checkpoint.root
    justified_slot = compute_start_slot_at_epoch(store.justified_checkpoint.epoch)
    while True:
        children = [
            root for root in blocks.keys()
            if blocks[root].parent_root == head and blocks[root].slot > justified_slot
        ]
        if len(children) == 0:
            return head
        # Sort by latest attesting balance with ties broken lexicographically
        head = max(children, key=lambda root: (get_latest_attesting_balance(store, root), root))
```

#### `should_update_justified_checkpoint`

```python
def should_update_justified_checkpoint(store: Store, new_justified_checkpoint: Checkpoint) -> bool:
    """
    To address the bouncing attack, only update conflicting justified
    checkpoints in the fork choice if in the early slots of the epoch.
    Otherwise, delay incorporation of new justified checkpoint until next epoch boundary.

    See https://ethresear.ch/t/prevention-of-bouncing-attack-on-ffg/6114 for more detailed analysis and discussion.
    """
    if compute_slots_since_epoch_start(get_current_slot(store)) < SAFE_SLOTS_TO_UPDATE_JUSTIFIED:
        return True

    justified_slot = compute_start_slot_at_epoch(store.justified_checkpoint.epoch)
    if not get_ancestor(store, new_justified_checkpoint.root, justified_slot) == store.justified_checkpoint.root:
        return False

    return True
```

#### `on_attestation` helpers

##### `validate_on_attestation`

```python
def validate_on_attestation(store: Store, attestation: Attestation) -> None:
    target = attestation.data.target

    # Attestations must be from the current or previous epoch
    current_epoch = compute_epoch_at_slot(get_current_slot(store))
    # Use GENESIS_EPOCH for previous when genesis to avoid underflow
    previous_epoch = current_epoch - 1 if current_epoch > GENESIS_EPOCH else GENESIS_EPOCH
    # If attestation target is from a future epoch, delay consideration until the epoch arrives
    assert target.epoch in [current_epoch, previous_epoch]
    assert target.epoch == compute_epoch_at_slot(attestation.data.slot)

    # Attestations target be for a known block. If target block is unknown, delay consideration until the block is found
    assert target.root in store.blocks

    # Attestations must be for a known block. If block is unknown, delay consideration until the block is found
    assert attestation.data.beacon_block_root in store.blocks
    # Attestations must not be for blocks in the future. If not, the attestation should not be considered
    assert store.blocks[attestation.data.beacon_block_root].slot <= attestation.data.slot

    # LMD vote must be consistent with FFG vote target
    target_slot = compute_start_slot_at_epoch(target.epoch)
    assert target.root == get_ancestor(store, attestation.data.beacon_block_root, target_slot)

    # Attestations can only affect the fork choice of subsequent slots.
    # Delay consideration in the fork choice until their slot is in the past.
    assert get_current_slot(store) >= attestation.data.slot + 1
```

##### `store_target_checkpoint_state`

```python
def store_target_checkpoint_state(store: Store, target: Checkpoint) -> None:
    # Store target checkpoint state if not yet seen
    if target not in store.checkpoint_states:
        base_state = copy(store.block_states[target.root])
        if base_state.slot < compute_start_slot_at_epoch(target.epoch):
            process_slots(base_state, compute_start_slot_at_epoch(target.epoch))
        store.checkpoint_states[target] = base_state
```

##### `update_latest_messages`

```python
def update_latest_messages(store: Store, attesting_indices: Sequence[ValidatorIndex], attestation: Attestation) -> None:
    target = attestation.data.target
    beacon_block_root = attestation.data.beacon_block_root
    for i in attesting_indices:
        if i not in store.latest_messages or target.epoch > store.latest_messages[i].epoch:
            store.latest_messages[i] = LatestMessage(epoch=target.epoch, root=beacon_block_root)
```


### Handlers

#### `on_tick`

```python
def on_tick(store: Store, time: uint64) -> None:
    previous_slot = get_current_slot(store)

    # update store time
    store.time = time

    current_slot = get_current_slot(store)
    # Not a new epoch, return
    if not (current_slot > previous_slot and compute_slots_since_epoch_start(current_slot) == 0):
        return
    # Update store.justified_checkpoint if a better checkpoint is known
    if store.best_justified_checkpoint.epoch > store.justified_checkpoint.epoch:
        store.justified_checkpoint = store.best_justified_checkpoint
```

#### `on_block`

```python
def on_block(store: Store, signed_block: SignedBeaconBlock) -> None:
    block = signed_block.message
    # Parent block must be known
    assert block.parent_root in store.block_states
    # Make a copy of the state to avoid mutability issues
    pre_state = copy(store.block_states[block.parent_root])
    # Blocks cannot be in the future. If they are, their consideration must be delayed until the are in the past.
    assert get_current_slot(store) >= block.slot

    # Check that block is later than the finalized epoch slot (optimization to reduce calls to get_ancestor)
    finalized_slot = compute_start_slot_at_epoch(store.finalized_checkpoint.epoch)
    assert block.slot > finalized_slot
    # Check block is a descendant of the finalized block at the checkpoint finalized slot
    assert get_ancestor(store, block.parent_root, finalized_slot) == store.finalized_checkpoint.root

    # Check the block is valid and compute the post-state
    state = state_transition(pre_state, signed_block, True)
    # Add new block to the store
    store.blocks[hash_tree_root(block)] = block
    # Add new state for this block to the store
    store.block_states[hash_tree_root(block)] = state

    # Update justified checkpoint
    if state.current_justified_checkpoint.epoch > store.justified_checkpoint.epoch:
        if state.current_justified_checkpoint.epoch > store.best_justified_checkpoint.epoch:
            store.best_justified_checkpoint = state.current_justified_checkpoint
        if should_update_justified_checkpoint(store, state.current_justified_checkpoint):
            store.justified_checkpoint = state.current_justified_checkpoint

    # Update finalized checkpoint
    if state.finalized_checkpoint.epoch > store.finalized_checkpoint.epoch:
        store.finalized_checkpoint = state.finalized_checkpoint

        # Potentially update justified if different from store
        if store.justified_checkpoint != state.current_justified_checkpoint:
            # Update justified if new justified is later than store justified
            if state.current_justified_checkpoint.epoch > store.justified_checkpoint.epoch:
                store.justified_checkpoint = state.current_justified_checkpoint
                return

            # Update justified if store justified is not in chain with finalized checkpoint
            finalized_slot = compute_start_slot_at_epoch(store.finalized_checkpoint.epoch)
            ancestor_at_finalized_slot = get_ancestor(store, store.justified_checkpoint.root, finalized_slot)
            if ancestor_at_finalized_slot != store.finalized_checkpoint.root:
                store.justified_checkpoint = state.current_justified_checkpoint
```

#### `on_attestation`

```python
def on_attestation(store: Store, attestation: Attestation) -> None:
    """
    Run ``on_attestation`` upon receiving a new ``attestation`` from either within a block or directly on the wire.

    An ``attestation`` that is asserted as invalid may be valid at a later time,
    consider scheduling it for later processing in such case.
    """
    validate_on_attestation(store, attestation)
    store_target_checkpoint_state(store, attestation.data.target)

    # Get state at the `target` to fully validate attestation
    target_state = store.checkpoint_states[attestation.data.target]
    indexed_attestation = get_indexed_attestation(target_state, attestation)
    assert is_valid_indexed_attestation(target_state, indexed_attestation)

    # Update latest messages for attesting indices
    update_latest_messages(store, indexed_attestation.attesting_indices, attestation)
```
