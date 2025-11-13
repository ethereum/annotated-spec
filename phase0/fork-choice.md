# Phase 0 -- Beacon Chain Fork Choice

<!-- mdformat-toc start --slug=github --no-anchors --maxlevel=6 --minlevel=2 -->

- [Introduction](#introduction)
- [Fork choice](#fork-choice)
  - [Constant](#constant)
  - [Configuration](#configuration)
    - [Time parameters](#time-parameters)
  - [Helpers](#helpers)
    - [`LatestMessage`](#latestmessage)
    - [`Store`](#store)
    - [`get_forkchoice_store`](#get_forkchoice_store)
    - [`get_slots_since_genesis`](#get_slots_since_genesis)
    - [`get_current_slot`](#get_current_slot)
    - [`get_current_store_epoch`](#get_current_store_epoch)
    - [`compute_slots_since_epoch_start`](#compute_slots_since_epoch_start)
    - [`get_ancestor`](#get_ancestor)
    - [`calculate_committee_fraction`](#calculate_committee_fraction)
    - [`get_checkpoint_block`](#get_checkpoint_block)
    - [`get_proposer_score`](#get_proposer_score)
    - [`get_weight`](#get_weight)
    - [`get_voting_source`](#get_voting_source)
    - [`filter_block_tree`](#filter_block_tree)
    - [`get_filtered_block_tree`](#get_filtered_block_tree)
    - [`get_head`](#get_head)
    - [`update_checkpoints`](#update_checkpoints)
    - [`update_unrealized_checkpoints`](#update_unrealized_checkpoints)
    - [`seconds_to_milliseconds`](#seconds_to_milliseconds)
    - [`get_slot_component_duration_ms`](#get_slot_component_duration_ms)
    - [`get_attestation_due_ms`](#get_attestation_due_ms)
    - [`get_proposer_reorg_cutoff_ms`](#get_proposer_reorg_cutoff_ms)
    - [`get_aggregate_due_ms`](#get_aggregate_due_ms)
    - [Proposer head and reorg helpers](#proposer-head-and-reorg-helpers)
      - [`is_head_late`](#is_head_late)
      - [`is_shuffling_stable`](#is_shuffling_stable)
      - [`is_ffg_competitive`](#is_ffg_competitive)
      - [`is_finalization_ok`](#is_finalization_ok)
      - [`is_proposing_on_time`](#is_proposing_on_time)
      - [`is_head_weak`](#is_head_weak)
      - [`is_parent_strong`](#is_parent_strong)
      - [`get_proposer_head`](#get_proposer_head)
    - [Pull-up tip helpers](#pull-up-tip-helpers)
      - [`compute_pulled_up_tip`](#compute_pulled_up_tip)
    - [`on_tick` helpers](#on_tick-helpers)
      - [`on_tick_per_slot`](#on_tick_per_slot)
    - [`on_attestation` helpers](#on_attestation-helpers)
      - [`validate_target_epoch_against_current_time`](#validate_target_epoch_against_current_time)
      - [`validate_on_attestation`](#validate_on_attestation)
      - [`store_target_checkpoint_state`](#store_target_checkpoint_state)
      - [`update_latest_messages`](#update_latest_messages)
  - [Handlers](#handlers)
    - [`on_tick`](#on_tick)
    - [`on_block`](#on_block)
    - [`on_attestation`](#on_attestation)
    - [`on_attester_slashing`](#on_attester_slashing)

<!-- mdformat-toc end -->

## Introduction

This document is the beacon chain fork choice spec, part of Phase 0. It assumes
the [beacon chain state transition function spec](./beacon-chain.md).

<!-- NOTES-BEGIN -->

It describes the mechanism for how to choose what is the "canonical" chain in the event that there are multiple conflicting versions of the chain to choose from. All blockchains have the possibility of temporary disagreement, either because of malicious behavior (eg. a block proposer publishing two different blocks at the same time), or just network latency (eg. a block being delayed by a few seconds, causing it to be broadcasted around the same time as the _next_ block that gets published by someone else). In such cases, some mechanism is needed to choose which of the two (or more) chains represents the "actual" history and state of the system (this chain is called the **canonical chain**).

PoW chains (Bitcoin, Ethereum 1.0, etc) typically use some variant of the **longest chain rule**: if there is a disagreement between chains, pick the chain that is the longest.

![](https://vitalik.ca/files/posts_files/cbc-casper-files/Chain3.png)

In practice, "[total difficulty](https://ethereum.stackexchange.com/questions/7068/difficulty-and-total-difficulty)" is used instead of length, though for most intuitive analysis, thinking about length is typically sufficient. PoS chains can also use the longest chain rule; however, PoS opens the door to much better fork choice rules that provide much stronger properties than the longest chain rule.

The fork choice rule can be viewed as being part of the **consensus algorithm**, the other part of the consensus algorithm being the rules that determine what messages each participant should send to the network (see the [honest validator doc](https://github.com/ethereum/eth2.0-specs/blob/dev/specs/phase0/validator.md#beacon-chain-responsibilities) for more info). In eth2, the consensus algorithm is Casper FFG + LMD GHOST, sometimes called [Gasper](https://arxiv.org/abs/2003.03052).

* See here for the original paper describing Casper FFG: https://arxiv.org/abs/1710.09437
* See here for a description of LMD GHOST (ignore the section on detecting finality, as that is specific to Casper CBC, whereas the fork choice rule is shared between CBC and FFG): https://vitalik.ca/general/2018/12/05/cbc_casper.html

The goal of Casper FFG and LMD GHOST is to combine together the benefits of two major types of PoS design: **longest-chain-based** (or Nakamoto-based), as used by Peercoin, NXT, [Ouroboros](https://cardano.org/ouroboros/) and many other designs, and **traditional BFT based**, as used by [Tendermint](https://tendermint.com/docs/introduction/what-is-tendermint.html) and others. Longest chain systems have the benefit that they are low-overhead, even with a very high number of participants. Traditional BFT systems have the key benefit that they have a concept of **finality**: once a block is **finalized**, it can no longer be reverted, no matter what other participants in the network do. If >1/3 of participants in the network behave maliciously, different nodes could be tricked into accepting different conflicting blocks as finalized. However, to cause such a situation, those participants would have to misbehave in a very unambiguous and provable way, allowing them to be **slashed** (all their coins are taken away as a penalty), making attacks extremely expensive. Additionally, traditional BFT systems reach finality quickly, though at the cost of high overhead and a low maximum participant count.

Eth2 combines together the advantages of both. It includes a traditional-BFT-inspired finality system (Casper FFG), though running at a rate of ~13 minutes per cycle (note: time to finality = 2 epochs = 2 * 32 * 12 sec) instead of a few seconds per cycle, allowing potentially over a million participants. To progress the chain between these epochs, LMD GHOST is used.

![](https://vitalik.ca/files/posts_files/cbc-casper-files/Chain7.png)

The core idea of LMD GHOST is that at each fork, instead of choosing the side that contains a longer chain, we choose the side that has more total support from validators, counting only the most recent message of each validator as support. This is heavily inspired by [Zohar and Sompolinsky's original GHOST paper](https://eprint.iacr.org/2013/881), but it adapts the design from its original PoW context to our new PoS context. LMD GHOST is powerful because it easily generalizes to much more than one "vote" being sent in parallel.

This is a very valuable feature for us because Casper FFG [already requires every validator](https://github.com/ethereum/annotated-spec/blob/master/phase0/beacon-chain.md#how-does-eth2-proof-of-stake-work) to send one attestation per epoch, meaning that hundreds of attestations are already being sent every second. We piggyback on those messages and ask them to include additional information voting on the current head of the chain. The result of this is that when a block is published, within seconds there are hundreds of signed messages from validators (**attestations**) confirming the block, and after even one slot (12 seconds) it's very difficult to revert a block. Anyone seeking even stronger ironclad confirmation can simply wait for finality after two epochs (~12 minutes).

The approximate approach that we take to combining Casper FFG and LMD GHOST is:

1. Use the Casper FFG rules to compute finalized blocks. If a block becomes finalized, all future canonical chains must pass through this block.
2. Use the Casper FFG rules to keep track of the **latest justified checkpoint** (LJC) that is a descendant of the latest accepted finalized checkpoint.
3. Use the LMD GHOST rules, starting from the LJC as root, to compute the chain head.

This combination of steps, particularly rule (2), is implemented to ensure that new blocks that validators create by following the rules actually will continually finalize new blocks with Casper FFG, even if temporary exceptional situations (eg. involving attacks or extremely high network latency) take place.

**Checkpoints vs blocks**

Note also that Casper FFG deals with **checkpoints** and the **checkpoint tree**, whereas LMD GHOST deals with blocks and the **block tree**. One simple way to think about this is that the checkpoint tree is a compressed version of the block tree, where we only consider blocks at the start of an epoch, and where checkpoint A is a parent of checkpoint B if block A is the ancestor of B in the block tree that begins the epoch before B:

![](../images/checkpoint_tree_1.png)

_Green blocks are the checkpoints; in the checkpoint tree, A is the parent of B1 and B2._

But to approach a more realistic picture we need to account for an important scenario: when there are skipped slots. If a chain has a skipped block at some slot, we take the most recent block before that slot in that chain as the epoch boundary block:

![](../images/checkpoint_tree_2.png)

In any case, where there is a divergence between multiple chains, skipped slots will be frequent because proposer selection and slashing rules forbid multiple blocks from being created in the same slot (unless two chains diverge for more than four epochs)! Note also that if we want to compute the _post-state_ of a checkpoint, we would have to run [the `process_slots` function](https://github.com/ethereum/annotated-spec/blob/master/phase0/beacon-chain.md#state-transition) up to the first slot of the epoch to process the empty slots.

Another important edge case is when there is more than an entire epoch of skipped slots. To cover this edge case, we think about a checkpoint as a (block, slot) pair, not a blocks; this means that the same block could be part of multiple checkpoints that an attestation could validly reference:

![](../images/checkpoint_tree_3.png)

In this case, the block B2 corresponds to two checkpoints, `(B2, N)` and `(B2, N+1)`, one for each epoch. In general, the most helpful model for understanding Ethereum state transitions may actually be the full state transition tree, where we look at all possible `(block, slot)` pairs:

![](../images/checkpoint_tree_4.png)

If you're a mathematician, you could view both the block tree and the checkpoint tree as [graph minors](https://en.wikipedia.org/wiki/Graph_minor) of the state transition tree. Casper FFG works over the checkpoint tree, and LMD GHOST works over the block tree. For convenience, we'll use the phrase "**latest justified block**" (LJB) to refer to the block referenced in the latest justified checkpoint; because LMD GHOST works over the block tree we'll keep the discussion to blocks, though the actual data structures will talk about the latest justified checkpoint. Note that while one block may map to multiple checkpoints, a checkpoint only references one block, so this language is unambiguous.

Now, let's go through the specification...


## Fork choice

The head block root associated with a `store` is defined as `get_head(store)`.
At genesis, let `store = get_forkchoice_store(genesis_state, genesis_block)` and
update `store` by running:

- `on_tick(store, time)` whenever `time > store.time` where `time` is the
  current Unix time
- `on_block(store, block)` whenever a block `block: SignedBeaconBlock` is
  received
- `on_attestation(store, attestation)` whenever an attestation `attestation` is
  received
- `on_attester_slashing(store, attester_slashing)` whenever an attester slashing
  `attester_slashing` is received

Any of the above handlers that trigger an unhandled exception (e.g. a failed
assert or an out-of-range list access) are considered invalid. Invalid calls to
handlers must not modify `store`.

*Notes*:

1. **Leap seconds**: Slots will last `SECONDS_PER_SLOT + 1` or
   `SECONDS_PER_SLOT - 1` seconds around leap seconds. This is automatically
   handled by [UNIX time](https://en.wikipedia.org/wiki/Unix_time).
2. **Honest clocks**: Honest nodes are assumed to have clocks synchronized
   within `SECONDS_PER_SLOT` seconds of each other.
3. **Eth1 data**: The large `ETH1_FOLLOW_DISTANCE` specified in the
   [honest validator document](./validator.md) should ensure that
   `state.latest_eth1_data` of the canonical beacon chain remains consistent
   with the canonical Ethereum proof-of-work chain. If not, emergency manual
   intervention will be required.
4. **Manual forks**: Manual forks may arbitrarily change the fork choice rule
   but are expected to be enacted at epoch transitions, with the fork details
   reflected in `state.fork`.
5. **Implementation**: The implementation found in this specification is
   constructed for ease of understanding rather than for optimization in
   computation, space, or any other resource. A number of optimized alternatives
   can be found [here](https://github.com/protolambda/lmd-ghost).

<!-- NOTES-BEGIN -->

One important thing to note is that the fork choice _is not a pure function_; that is, what you accept as a canonical chain does not depend just on what data you also have, but also when you received it. The main reason this is done is to enforce finality: if you accept a block as finalized, then you will never revert it, even if you later see a conflicting block as finalized. Such a situation would only happen in cases where there is an active >1/3 attack on the chain; in such cases, we expect extra-protocol measures to be required to get all clients back on the same chain. There are also other deviations from purity, particularly a "sticky" choice of the latest justified block, where the latest justified block can only change near the beginning of an epoch; this is done to prevent certain kinds of "bouncing attacks".

### Constant

| Name                              | Value           |
| --------------------------------- | --------------- |
| `INTERVALS_PER_SLOT` *deprecated* | `uint64(3)`     |
| `BASIS_POINTS`                    | `uint64(10000)` |

### Configuration

| Name                                  | Value         |
| ------------------------------------- | ------------- |
| `PROPOSER_SCORE_BOOST`                | `uint64(40)`  |
| `REORG_HEAD_WEIGHT_THRESHOLD`         | `uint64(20)`  |
| `REORG_PARENT_WEIGHT_THRESHOLD`       | `uint64(160)` |
| `REORG_MAX_EPOCHS_SINCE_FINALIZATION` | `Epoch(2)`    |

- The proposer score boost and re-org weight threshold are percentage values
  that are measured with respect to the weight of a single committee. See
  `calculate_committee_fraction`.

#### Time parameters

| Name                        | Value          |     Unit     |          Duration          |
| --------------------------- | -------------- | :----------: | :------------------------: |
| `PROPOSER_REORG_CUTOFF_BPS` | `uint64(1667)` | basis points | ~17% of `SLOT_DURATION_MS` |

### Helpers

<!-- NOTES-BEGIN -->

Here, we define the data structure for the `store`. It only has one new subtype, the `LatestMessage` (the vote in the latest [meaning highest-epoch] valid attestation received from a validator).

#### `LatestMessage`

```python
@dataclass(eq=True, frozen=True)
class LatestMessage(object):
    epoch: Epoch
    root: Root
```

#### `Store`

The `Store` is responsible for tracking information required for the fork choice
algorithm. The important fields being tracked are described below:

- `justified_checkpoint`: the justified checkpoint used as the starting point
  for the LMD GHOST fork choice algorithm.
- `finalized_checkpoint`: the highest known finalized checkpoint. The fork
  choice only considers blocks that are not conflicting with this checkpoint.
- `unrealized_justified_checkpoint` & `unrealized_finalized_checkpoint`: these
  track the highest justified & finalized checkpoints resp., without regard to
  whether on-chain ***realization*** has occurred, i.e. FFG processing of new
  attestations within the state transition function. This is an important
  distinction from `justified_checkpoint` & `finalized_checkpoint`, because they
  will only track the checkpoints that are realized on-chain. Note that on-chain
  processing of FFG information only happens at epoch boundaries.
- `unrealized_justifications`: stores a map of block root to the unrealized
  justified checkpoint observed in that block.

```python
@dataclass
class Store(object):
    time: uint64
    genesis_time: uint64
    justified_checkpoint: Checkpoint
    finalized_checkpoint: Checkpoint
    unrealized_justified_checkpoint: Checkpoint
    unrealized_finalized_checkpoint: Checkpoint
    proposer_boost_root: Root
    equivocating_indices: Set[ValidatorIndex]
    blocks: Dict[Root, BeaconBlock] = field(default_factory=dict)
    block_states: Dict[Root, BeaconState] = field(default_factory=dict)
    block_timeliness: Dict[Root, boolean] = field(default_factory=dict)
    checkpoint_states: Dict[Checkpoint, BeaconState] = field(default_factory=dict)
    latest_messages: Dict[ValidatorIndex, LatestMessage] = field(default_factory=dict)
    unrealized_justifications: Dict[Root, Checkpoint] = field(default_factory=dict)
```

<!-- NOTES-BEGIN -->

The member variables here are as follows:

* `time`: the current time
* `genesis_time`: the time of the genesis block of the chain
* `justified_checkpoint`: the Casper FFG justified checkpoint that is used as the root of the LMD GHOST fork choice
* `finalized_checkpoint`: the last finalized checkpoint; this block and its ancestors cannot be reverted
* `best_justified_checkpoint`: the justified checkpoint that we will switch to at the start of the next epoch (see [this section](#should_update_justified_checkpoint) for why we store this variable temporarily and only switch over the `justified_checkpoint` at the start of the next epoch)
* `blocks`: all blocks that we know about. Note that each `Block` contains a `parent_root`, so this contains the full "block tree" so we can get parents and children for any block
* `block_states`: the post-state of every block that we know about. We need this for a few reasons: (i) to verify any new incoming block that claims that block as a parent, (ii) to be able to get the current and previous justified checkpoint of a block when running `filter_block_tree`, and (iii) to compute the end-of-epoch checkpoint states.
* `checkpoint_states`: the post-state of every checkpoint. This could be different from the post-state of the block referenced by the checkpoint in the case where there are skipped slots; one would need to run the state transition function through the empty slots to get to the end-of-epoch state. Note particularly the extreme case where there is more than an entire epoch of skipped slots between a block and its child, so there are _multiple_ checkpoints referring to that block, with different epoch numbers and different states.
* `latest_messages`: the latest epoch and block voted for by each validator.

Note that in reality, instead of storing the post-states of all blocks and checkpoints that they know about, clients may simply store only the latest state, opting to reprocess blocks or process a saved journal of state changes if they want to process older blocks. This sacrifices computing efficiency in exceptional cases but saves greatly on storage.

#### `get_forkchoice_store`

The provided anchor-state will be regarded as a trusted state, to not roll back
beyond. This should be the genesis state for a full client.

*Note* With regards to fork choice, block headers are interchangeable with
blocks. The spec is likely to move to headers for reduced overhead in test
vectors and better encapsulation. Full implementations store blocks as part of
their database and will often use full blocks when dealing with production fork
choice.

```python
def get_forkchoice_store(anchor_state: BeaconState, anchor_block: BeaconBlock) -> Store:
    assert anchor_block.state_root == hash_tree_root(anchor_state)
    anchor_root = hash_tree_root(anchor_block)
    anchor_epoch = get_current_epoch(anchor_state)
    justified_checkpoint = Checkpoint(epoch=anchor_epoch, root=anchor_root)
    finalized_checkpoint = Checkpoint(epoch=anchor_epoch, root=anchor_root)
    proposer_boost_root = Root()
    return Store(
        time=uint64(anchor_state.genesis_time + SECONDS_PER_SLOT * anchor_state.slot),
        genesis_time=anchor_state.genesis_time,
        justified_checkpoint=justified_checkpoint,
        finalized_checkpoint=finalized_checkpoint,
        unrealized_justified_checkpoint=justified_checkpoint,
        unrealized_finalized_checkpoint=finalized_checkpoint,
        proposer_boost_root=proposer_boost_root,
        equivocating_indices=set(),
        blocks={anchor_root: copy(anchor_block)},
        block_states={anchor_root: copy(anchor_state)},
        checkpoint_states={justified_checkpoint: copy(anchor_state)},
        unrealized_justifications={anchor_root: justified_checkpoint},
    )
```

<!-- NOTES-BEGIN -->

This function initializes the `store` given a particular block that the fork choice would start from. This should be the most recent finalized block that the client knows about from extra-protocol sources; at the beginning, it would just be the genesis.

_The block for `anchor_root` is incorrectly initialized to the block header, rather than the full block. This does not affect functionality but will be cleaned up in subsequent releases._

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

#### `get_current_store_epoch`

```python
def get_current_store_epoch(store: Store) -> Epoch:
    return compute_epoch_at_slot(get_current_slot(store))
```

#### `compute_slots_since_epoch_start`

```python
def compute_slots_since_epoch_start(slot: Slot) -> int:
    return slot - compute_start_slot_at_epoch(compute_epoch_at_slot(slot))
```

<!-- NOTES-BEGIN -->

Compute which slot of the current epoch we are in (returns 0...31).

#### `get_ancestor`

```python
def get_ancestor(store: Store, root: Root, slot: Slot) -> Root:
    block = store.blocks[root]
    if block.slot > slot:
        return get_ancestor(store, block.parent_root, slot)
    return root
```

<!-- NOTES-BEGIN -->

Get the ancestor of block `root` (we refer to all blocks by their root in the fork choice spec) at the given `slot` (eg. if `root` was at slot 105 and `slot = 100`, and the chain has no skipped slots in between, it would return the block's fifth ancestor).

#### `calculate_committee_fraction`

```python
def calculate_committee_fraction(state: BeaconState, committee_percent: uint64) -> Gwei:
    committee_weight = get_total_active_balance(state) // SLOTS_PER_EPOCH
    return Gwei((committee_weight * committee_percent) // 100)
```

#### `get_checkpoint_block`

```python
def get_checkpoint_block(store: Store, root: Root, epoch: Epoch) -> Root:
    """
    Compute the checkpoint block for epoch ``epoch`` in the chain of block ``root``
    """
    epoch_first_slot = compute_start_slot_at_epoch(epoch)
    return get_ancestor(store, root, epoch_first_slot)
```

#### `get_proposer_score`

```python
def get_proposer_score(store: Store) -> Gwei:
    justified_checkpoint_state = store.checkpoint_states[store.justified_checkpoint]
    committee_weight = get_total_active_balance(justified_checkpoint_state) // SLOTS_PER_EPOCH
    return (committee_weight * PROPOSER_SCORE_BOOST) // 100
```

#### `get_weight`

```python
def get_weight(store: Store, root: Root) -> Gwei:
    state = store.checkpoint_states[store.justified_checkpoint]
    unslashed_and_active_indices = [
        i
        for i in get_active_validator_indices(state, get_current_epoch(state))
        if not state.validators[i].slashed
    ]
    attestation_score = Gwei(
        sum(
            state.validators[i].effective_balance
            for i in unslashed_and_active_indices
            if (
                i in store.latest_messages
                and i not in store.equivocating_indices
                and get_ancestor(store, store.latest_messages[i].root, store.blocks[root].slot)
                == root
            )
        )
    )
    if store.proposer_boost_root == Root():
        # Return only attestation score if ``proposer_boost_root`` is not set
        return attestation_score

    # Calculate proposer score if ``proposer_boost_root`` is set
    proposer_score = Gwei(0)
    # Boost is applied if ``root`` is an ancestor of ``proposer_boost_root``
    if get_ancestor(store, store.proposer_boost_root, store.blocks[root].slot) == root:
        proposer_score = get_proposer_score(store)
    return attestation_score + proposer_score
```

<!-- NOTES-BEGIN -->

Get the total ETH attesting to a given block or its descendants, considering only latest attestations and active validators. This is the main function that is used to choose between two children of a block in LMD GHOST. Recall the diagram from above:

![](https://vitalik.ca/files/posts_files/cbc-casper-files/Chain7.png)

In this diagram, we assume that each of the last five block proposals (the blue ones) carries one attestation, which specifies that block as the head, and we assume each block is created by a different validator, and all validators have the same deposit size. The number in each square represents the latest attesting balance of that block. In eth2, blocks and attestations are separate, and there will be hundreds of attestations supporting each block, but otherwise, the principle is the same.

#### `get_voting_source`

```python
def get_voting_source(store: Store, block_root: Root) -> Checkpoint:
    """
    Compute the voting source checkpoint in event that block with root ``block_root`` is the head block
    """
    block = store.blocks[block_root]
    current_epoch = get_current_store_epoch(store)
    block_epoch = compute_epoch_at_slot(block.slot)
    if current_epoch > block_epoch:
        # The block is from a prior epoch, the voting source will be pulled-up
        return store.unrealized_justifications[block_root]
    else:
        # The block is not from a prior epoch, therefore the voting source is not pulled up
        head_state = store.block_states[block_root]
        return head_state.current_justified_checkpoint
```

#### `filter_block_tree`

*Note*: External calls to `filter_block_tree` (i.e., any calls that are not made
by the recursive logic in this function) MUST set `block_root` to
`store.justified_checkpoint.root`.

```python
def filter_block_tree(store: Store, block_root: Root, blocks: Dict[Root, BeaconBlock]) -> bool:
    block = store.blocks[block_root]
    children = [
        root for root in store.blocks.keys() if store.blocks[root].parent_root == block_root
    ]

    # If any children branches contain expected finalized/justified checkpoints,
    # add to filtered block-tree and signal viability to parent.
    if any(children):
        filter_block_tree_result = [filter_block_tree(store, child, blocks) for child in children]
        if any(filter_block_tree_result):
            blocks[block_root] = block
            return True
        return False

    current_epoch = get_current_store_epoch(store)
    voting_source = get_voting_source(store, block_root)

    # The voting source should be either at the same height as the store's justified checkpoint or
    # not more than two epochs ago
    correct_justified = (
        store.justified_checkpoint.epoch == GENESIS_EPOCH
        or voting_source.epoch == store.justified_checkpoint.epoch
        or voting_source.epoch + 2 >= current_epoch
    )

    finalized_checkpoint_block = get_checkpoint_block(
        store,
        block_root,
        store.finalized_checkpoint.epoch,
    )

    correct_finalized = (
        store.finalized_checkpoint.epoch == GENESIS_EPOCH
        or store.finalized_checkpoint.root == finalized_checkpoint_block
    )

    # If expected finalized/justified, add to viable block-tree and signal viability to parent.
    if correct_justified and correct_finalized:
        blocks[block_root] = block
        return True

    # Otherwise, branch not viable
    return False
```

<!-- NOTES-BEGIN -->

Here, we implement an important but subtle deviation from the "LMD GHOST starting from the latest justified block" rule mentioned above. To motivate this deviation, consider the following attack:

* There exists a justified block B, with two descendants, C1 and C2
* B is justified, but the evidence of these justifications somehow only got included in the C1 chain, not the C2 chain
* The C1 chain starts off favored by the LMD GHOST fork choice. Suppose that 49% of validators attest to C1, using B as the latest justified block, as the C1 chain recognizes B as justified
* The fork choice switches to favoring C2 for some reason (eg. the other 51% of validators attested to C2 in that epoch). C2 does not recognize B as justified (and after two epochs can't recognize B as justified as it's too late to include evidence), so some earlier block A is used as the latest justified block instead.

Now, all validators see C2 as the canonical chain, and the system is stuck: for a new block to be finalized, 67% of validators must make an attestation `[A -> C2]` (or `[A -> child(C2)]`), but only 51% can do this freely; at least 16% are constrained because they already voted `[B -> C1]`, and `[A -> C2]` violates the no-double-vote rule and `[A -> child(C2)]` violates the no-surround rule. Hence, the system can only progress if 16% voluntarily slash themselves.

The fix is the following. We restrict the fork choice to only looking at descendants of B that actually recognize B as their latest justified block (or more precisely, leaves in the block tree where B is their latest justified block, as well as their ancestors). A client only accepts a block B locally as a latest justified block if there is an actual descendant block that recognizes it as such, so we know there must be at least one such chain. With this fix, C2 would not even be considered a viable candidate descendant of B until it (or one of its descendants) recognizes B as justified, so the above situation would resolve by simply favoring C1.

See [section 4.6 of the Gasper paper](https://arxiv.org/pdf/2003.03052.pdf) for more details.

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

<!-- NOTES-BEGIN -->

`filter_block_tree` above is an impure function; it takes as input a key/value dict, which it passes along to its recursive calls to fill in the dict. `get_filtered_block_tree` is a pure function that wraps around it. Additionally, instead of requiring the `root` to be passed as an explicit argument, it gets the justified checkpoint directly from the `store` (which contains, among other things, the full block tree).

#### `get_head`

```python
def get_head(store: Store) -> Root:
    # Get filtered block tree that only includes viable branches
    blocks = get_filtered_block_tree(store)
    # Execute the LMD-GHOST fork choice
    head = store.justified_checkpoint.root
    while True:
        children = [root for root in blocks.keys() if blocks[root].parent_root == head]
        if len(children) == 0:
            return head
        # Sort by latest attesting balance with ties broken lexicographically
        # Ties broken by favoring block with lexicographically higher root
        head = max(children, key=lambda root: (get_weight(store, root), root))
```

<!-- NOTES-BEGIN -->

The main fork choice rule function: gets the head of the chain.

This follows the following procedure:

1. Get the latest justified block hash, call it `B` (this is implicit in `get_filtered_block_tree`)
2. Get the subtree of blocks rooted in `B` (done by `get_filtered_block_tree`)
3. Filter that for blocks whose slot exceeds the slot of `B` (technically, this check is no longer necessary ever since (2) was introduced so may be removed)
4. Walk down the tree, at each step where a block has multiple children selecting the child with the strongest support (ie. higher `get_latest_attesting_balance`)

From here on below, we have the functions for _updating_ the `store`.

#### `update_checkpoints`

```python
def update_checkpoints(
    store: Store, justified_checkpoint: Checkpoint, finalized_checkpoint: Checkpoint
) -> None:
    """
    Update checkpoints in store if necessary
    """
    # Update justified checkpoint
    if justified_checkpoint.epoch > store.justified_checkpoint.epoch:
        store.justified_checkpoint = justified_checkpoint

    # Update finalized checkpoint
    if finalized_checkpoint.epoch > store.finalized_checkpoint.epoch:
        store.finalized_checkpoint = finalized_checkpoint
```

<!-- NOTES-BEGIN -->

In the phase0 version of fork-choice we only changed the last-justified-block within the first 1/3 of an epoch. This prevented "bouncing attacks" of the following form:

1. Start from a scenario wherein epoch N, 62% of validators support block A, and in epoch N+1, 62% of validators support block B. Suppose that the attacker has 5% of the total stake. This scenario requires very exceptional networking conditions to get into; the point of the attack, however, is that if we get into such a scenario the attacker could perpetuate it, permanently preventing finality.
2. Due to LMD GHOST, B is favored, and so validators are continuing to vote for B. However, the attacker suddenly publishes attestations worth 5% of the total stake tagged with epoch N for block A, causing A to get justified.
3. In epoch N+2, A is justified and so validators are attesting to A', a descendant of A. When A' gets to 62% support, the attacker publishes attestations worth 5% of total stake for B. Now B is justified and favored by the fork choice.
4. In epoch N+3, B is justified, and so validators are attesting to B', a descendant of B. When B' gets to 62% support, the attacker publishes attestations worth 5% of total stake for A'...

This could continue forever, bouncing permanently between the two chains preventing any new block from being finalized. This attack can happen because the combined use of LMD GHOST and Casper FFG creates a discontinuity, where a small shift in support for a block can outweigh a large amount of support for another block if that small shift pushes it past the 2/3 threshold needed for justification. We block the attack by only allowing the latest justified block to change near the beginning of an epoch; this way, there is a full 2/3 of an epoch during which honest validators agree on the head and have the opportunity to justify a block and thereby further cement it, at the same time causing the LMD GHOST rule to strongly favor that head. This sets up that block to most likely be finalized in the next epoch.
 
See [Ryuya Nakamura's ethresear.ch post](https://ethresear.ch/t/prevention-of-bouncing-attack-on-ffg/6114) for more discussion.

#### `update_unrealized_checkpoints`

```python
def update_unrealized_checkpoints(
    store: Store,
    unrealized_justified_checkpoint: Checkpoint,
    unrealized_finalized_checkpoint: Checkpoint,
) -> None:
    """
    Update unrealized checkpoints in store if necessary
    """
    # Update unrealized justified checkpoint
    if unrealized_justified_checkpoint.epoch > store.unrealized_justified_checkpoint.epoch:
        store.unrealized_justified_checkpoint = unrealized_justified_checkpoint

    # Update unrealized finalized checkpoint
    if unrealized_finalized_checkpoint.epoch > store.unrealized_finalized_checkpoint.epoch:
        store.unrealized_finalized_checkpoint = unrealized_finalized_checkpoint
```

#### `seconds_to_milliseconds`

```python
def seconds_to_milliseconds(seconds: uint64) -> uint64:
    """
    Convert seconds to milliseconds with overflow protection.
    Returns ``UINT64_MAX`` if the result would overflow.
    """
    if seconds > UINT64_MAX // 1000:
        return UINT64_MAX
    return seconds * 1000
```

#### `get_slot_component_duration_ms`

```python
def get_slot_component_duration_ms(basis_points: uint64) -> uint64:
    """
    Calculate the duration of a slot component in milliseconds.
    """
    return basis_points * SLOT_DURATION_MS // BASIS_POINTS
```

#### `get_attestation_due_ms`

```python
def get_attestation_due_ms(epoch: Epoch) -> uint64:
    return get_slot_component_duration_ms(ATTESTATION_DUE_BPS)
```

#### `get_proposer_reorg_cutoff_ms`

```python
def get_proposer_reorg_cutoff_ms(epoch: Epoch) -> uint64:
    return get_slot_component_duration_ms(PROPOSER_REORG_CUTOFF_BPS)
```

#### `get_aggregate_due_ms`

```python
def get_aggregate_due_ms(epoch: Epoch) -> uint64:
    return get_slot_component_duration_ms(AGGREGATE_DUE_BPS)
```

#### Proposer head and reorg helpers

_Implementing these helpers is optional_.

##### `is_head_late`

```python
def is_head_late(store: Store, head_root: Root) -> bool:
    return not store.block_timeliness[head_root]
```

##### `is_shuffling_stable`

```python
def is_shuffling_stable(slot: Slot) -> bool:
    return slot % SLOTS_PER_EPOCH != 0
```

##### `is_ffg_competitive`

```python
def is_ffg_competitive(store: Store, head_root: Root, parent_root: Root) -> bool:
    return (
        store.unrealized_justifications[head_root] == store.unrealized_justifications[parent_root]
    )
```

##### `is_finalization_ok`

```python
def is_finalization_ok(store: Store, slot: Slot) -> bool:
    epochs_since_finalization = compute_epoch_at_slot(slot) - store.finalized_checkpoint.epoch
    return epochs_since_finalization <= REORG_MAX_EPOCHS_SINCE_FINALIZATION
```

##### `is_proposing_on_time`

```python
def is_proposing_on_time(store: Store) -> bool:
    seconds_since_genesis = store.time - store.genesis_time
    time_into_slot_ms = seconds_to_milliseconds(seconds_since_genesis) % SLOT_DURATION_MS
    epoch = get_current_store_epoch(store)
    proposer_reorg_cutoff_ms = get_proposer_reorg_cutoff_ms(epoch)
    return time_into_slot_ms <= proposer_reorg_cutoff_ms
```

##### `is_head_weak`

```python
def is_head_weak(store: Store, head_root: Root) -> bool:
    justified_state = store.checkpoint_states[store.justified_checkpoint]
    reorg_threshold = calculate_committee_fraction(justified_state, REORG_HEAD_WEIGHT_THRESHOLD)
    head_weight = get_weight(store, head_root)
    return head_weight < reorg_threshold
```

##### `is_parent_strong`

```python
def is_parent_strong(store: Store, parent_root: Root) -> bool:
    justified_state = store.checkpoint_states[store.justified_checkpoint]
    parent_threshold = calculate_committee_fraction(justified_state, REORG_PARENT_WEIGHT_THRESHOLD)
    parent_weight = get_weight(store, parent_root)
    return parent_weight > parent_threshold
```

##### `get_proposer_head`

```python
def get_proposer_head(store: Store, head_root: Root, slot: Slot) -> Root:
    head_block = store.blocks[head_root]
    parent_root = head_block.parent_root
    parent_block = store.blocks[parent_root]

    # Only re-org the head block if it arrived later than the attestation deadline.
    head_late = is_head_late(store, head_root)

    # Do not re-org on an epoch boundary where the proposer shuffling could change.
    shuffling_stable = is_shuffling_stable(slot)

    # Ensure that the FFG information of the new head will be competitive with the current head.
    ffg_competitive = is_ffg_competitive(store, head_root, parent_root)

    # Do not re-org if the chain is not finalizing with acceptable frequency.
    finalization_ok = is_finalization_ok(store, slot)

    # Only re-org if we are proposing on-time.
    proposing_on_time = is_proposing_on_time(store)

    # Only re-org a single slot at most.
    parent_slot_ok = parent_block.slot + 1 == head_block.slot
    current_time_ok = head_block.slot + 1 == slot
    single_slot_reorg = parent_slot_ok and current_time_ok

    # Check that the head has few enough votes to be overpowered by our proposer boost.
    assert store.proposer_boost_root != head_root  # ensure boost has worn off
    head_weak = is_head_weak(store, head_root)

    # Check that the missing votes are assigned to the parent and not being hoarded.
    parent_strong = is_parent_strong(store, parent_root)

    if all(
        [
            head_late,
            shuffling_stable,
            ffg_competitive,
            finalization_ok,
            proposing_on_time,
            single_slot_reorg,
            head_weak,
            parent_strong,
        ]
    ):
        # We can re-org the current head by building upon its parent block.
        return parent_root
    else:
        return head_root
```

*Note*: The ordering of conditions is a suggestion only. Implementations are
free to optimize by re-ordering the conditions from least to most expensive and
by returning early if any of the early conditions are `False`.

#### Pull-up tip helpers

##### `compute_pulled_up_tip`

```python
def compute_pulled_up_tip(store: Store, block_root: Root) -> None:
    state = store.block_states[block_root].copy()
    # Pull up the post-state of the block to the next epoch boundary
    process_justification_and_finalization(state)

    store.unrealized_justifications[block_root] = state.current_justified_checkpoint
    update_unrealized_checkpoints(
        store, state.current_justified_checkpoint, state.finalized_checkpoint
    )

    # If the block is from a prior epoch, apply the realized values
    block_epoch = compute_epoch_at_slot(store.blocks[block_root].slot)
    current_epoch = get_current_store_epoch(store)
    if block_epoch < current_epoch:
        update_checkpoints(store, state.current_justified_checkpoint, state.finalized_checkpoint)
```

#### `on_tick` helpers

##### `on_tick_per_slot`

```python
def on_tick_per_slot(store: Store, time: uint64) -> None:
    previous_slot = get_current_slot(store)

    # Update store time
    store.time = time

    current_slot = get_current_slot(store)

    # If this is a new slot, reset store.proposer_boost_root
    if current_slot > previous_slot:
        store.proposer_boost_root = Root()

    # If a new epoch, pull-up justification and finalization from previous epoch
    if current_slot > previous_slot and compute_slots_since_epoch_start(current_slot) == 0:
        update_checkpoints(
            store, store.unrealized_justified_checkpoint, store.unrealized_finalized_checkpoint
        )
```

#### `on_attestation` helpers

##### `validate_target_epoch_against_current_time`

```python
def validate_target_epoch_against_current_time(store: Store, attestation: Attestation) -> None:
    target = attestation.data.target

    # Attestations must be from the current or previous epoch
    current_epoch = get_current_store_epoch(store)
    # Use GENESIS_EPOCH for previous when genesis to avoid underflow
    previous_epoch = current_epoch - 1 if current_epoch > GENESIS_EPOCH else GENESIS_EPOCH
    # If attestation target is from a future epoch, delay consideration until the epoch arrives
    assert target.epoch in [current_epoch, previous_epoch]
```

##### `validate_on_attestation`

```python
def validate_on_attestation(store: Store, attestation: Attestation, is_from_block: bool) -> None:
    target = attestation.data.target

    # If the given attestation is not from a beacon block message, we have to check the target epoch scope.
    if not is_from_block:
        validate_target_epoch_against_current_time(store, attestation)

    # Check that the epoch number and slot number are matching
    assert target.epoch == compute_epoch_at_slot(attestation.data.slot)

    # Attestation target must be for a known block. If target block is unknown, delay consideration until block is found
    assert target.root in store.blocks

    # Attestations must be for a known block. If block is unknown, delay consideration until the block is found
    assert attestation.data.beacon_block_root in store.blocks
    # Attestations must not be for blocks in the future. If not, the attestation should not be considered
    assert store.blocks[attestation.data.beacon_block_root].slot <= attestation.data.slot

    # LMD vote must be consistent with FFG vote target
    assert target.root == get_checkpoint_block(
        store, attestation.data.beacon_block_root, target.epoch
    )

    # Attestations can only affect the fork choice of subsequent slots.
    # Delay consideration in the fork choice until their slot is in the past.
    assert get_current_slot(store) >= attestation.data.slot + 1
```

<!-- NOTES-BEGIN -->

When a client receives an attestation (either from a block or directly on the wire), it should first perform some checks, and reject the attestation if it does not pass those checks.

We do the following checks:

1. Check that the attestation is from either the current or the previous epoch (we ignore attestations that come too late). This is done to prevent bounce attacks (see [above](#should_update_justified_checkpoint)) from "saving up" epochs and flipping back and forth between chains many times.
2. Check that the attestation is attesting to a block which the client has already received and verified (if it is not, the attestation may be saved for some time, in case that block is later found)
3. Check that the attestation is attesting to a block which is at or before the slot of the attestation (ie. can't attest to future blocks)
4. Check that the vote for the head block is consistent with the vote for the target
5. Check that the attestation's slot itself is not in the future

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

<!-- NOTES-BEGIN -->

Update the `checkpoint_states` dict, which is a convenience dict that stores the end-of-epoch states for each checkpoint. Most of the time, this is the same as the post-state of the last block in an epoch, but in the case where there are skipped slots, the state would need to process through the empty slots first. See the [Store definition](#Store) for more details.

##### `update_latest_messages`

```python
def update_latest_messages(
    store: Store, attesting_indices: Sequence[ValidatorIndex], attestation: Attestation
) -> None:
    target = attestation.data.target
    beacon_block_root = attestation.data.beacon_block_root
    non_equivocating_attesting_indices = [
        i for i in attesting_indices if i not in store.equivocating_indices
    ]
    for i in non_equivocating_attesting_indices:
        if i not in store.latest_messages or target.epoch > store.latest_messages[i].epoch:
            store.latest_messages[i] = LatestMessage(epoch=target.epoch, root=beacon_block_root)
```

<!-- NOTES-BEGIN -->

In the latest messages dict, update the latest message of each validator who participated in the given attestation.

### Handlers

#### `on_tick`

```python
def on_tick(store: Store, time: uint64) -> None:
    # If the ``store.time`` falls behind, while loop catches up slot by slot
    # to ensure that every previous slot is processed with ``on_tick_per_slot``
    tick_slot = (time - store.genesis_time) // SECONDS_PER_SLOT
    while get_current_slot(store) < tick_slot:
        previous_time = store.genesis_time + (get_current_slot(store) + 1) * SECONDS_PER_SLOT
        on_tick_per_slot(store, previous_time)
    on_tick_per_slot(store, time)
```

<!-- NOTES-BEGIN -->

This function runs on each tick (ie. per second). At the end of each epoch, update the justified checkpoint used in the fork choice.

#### `on_block`

```python
def on_block(store: Store, signed_block: SignedBeaconBlock) -> None:
    block = signed_block.message
    # Parent block must be known
    assert block.parent_root in store.block_states
    # Make a copy of the state to avoid mutability issues
    pre_state = copy(store.block_states[block.parent_root])
    # Blocks cannot be in the future. If they are, their consideration must be delayed until they are in the past.
    assert get_current_slot(store) >= block.slot

    # Check that block is later than the finalized epoch slot (optimization to reduce calls to get_ancestor)
    finalized_slot = compute_start_slot_at_epoch(store.finalized_checkpoint.epoch)
    assert block.slot > finalized_slot
    # Check block is a descendant of the finalized block at the checkpoint finalized slot
    finalized_checkpoint_block = get_checkpoint_block(
        store,
        block.parent_root,
        store.finalized_checkpoint.epoch,
    )
    assert store.finalized_checkpoint.root == finalized_checkpoint_block

    # Check the block is valid and compute the post-state
    state = pre_state.copy()
    block_root = hash_tree_root(block)
    state_transition(state, signed_block, True)
    # Add new block to the store
    store.blocks[block_root] = block
    # Add new state for this block to the store
    store.block_states[block_root] = state

    # Add block timeliness to the store
    seconds_since_genesis = store.time - store.genesis_time
    time_into_slot_ms = seconds_to_milliseconds(seconds_since_genesis) % SLOT_DURATION_MS
    epoch = get_current_store_epoch(store)
    attestation_threshold_ms = get_attestation_due_ms(epoch)
    is_before_attesting_interval = time_into_slot_ms < attestation_threshold_ms
    is_timely = get_current_slot(store) == block.slot and is_before_attesting_interval
    store.block_timeliness[hash_tree_root(block)] = is_timely

    # Add proposer score boost if the block is timely and not conflicting with an existing block
    is_first_block = store.proposer_boost_root == Root()
    if is_timely and is_first_block:
        store.proposer_boost_root = hash_tree_root(block)

    # Update checkpoints in store if necessary
    update_checkpoints(store, state.current_justified_checkpoint, state.finalized_checkpoint)

    # Eagerly compute unrealized justification and finality
    compute_pulled_up_tip(store, block_root)
```

<!-- NOTES-BEGIN -->

Upon receiving a block, first, do a few checks:

1. Check that we know about the block's parent (if we don't, we can temporarily save the block in case we find the parent later)
2. Check that the block is not from a slot that is still in the future (if it is, we can pretend to not hear about the block until time progresses to the point that the block is no longer from the future)
3. Check that the block slot is later than the last finalized block's slot and that the block is a descendant of the last finalized block (an optimization to reduce unnecessary work from blocks that can clearly no longer possibly become canonical)
4. Check that the block's post-state root is correct and the state transition passes

We then add the block to the DB. We also update the justified and finalized checkpoints. The idea is that if the justified checkpoint known by the received block has a higher epoch number than the justified checkpoint we know about, we accept that justified checkpoint. If we are [in the first 1/3](#should_update_justified_checkpoint) of an epoch, we accept it immediately, otherwise, we put it in `store.best_justified_checkpoint` so it can be updated into `store.justified_checkpoint` [at the end](#on_tick) of the epoch.

If the received block knows about a finalized checkpoint with a higher epoch number than what we know about, we accept it, and we also immediately update the justified checkpoint if either (i) the justified checkpoint provided in the block is more recent than the one we know about, or (ii) the one we know about is not compatible with the new finalized block. Note that there is a theoretical possibility that condition (ii) causes the justified checkpoint to go backward (change from a later epoch to an earlier epoch), but for this to happen, there would need to be a finalized block B with a justified child B', with a justified block A' on a conflicting chain pointing to some earlier finalized block A, which implies a slashable 1/3 attack due to the no-surround rule. In such a case, anyone who referenced A' as an LJB may not be able to build on top of B', so some validators who participated in the "wrong chain" may need to suffer some level of inactivity leak.

#### `on_attestation`

```python
def on_attestation(store: Store, attestation: Attestation, is_from_block: bool = False) -> None:
    """
    Run ``on_attestation`` upon receiving a new ``attestation`` from either within a block or directly on the wire.

    An ``attestation`` that is asserted as invalid may be valid at a later time,
    consider scheduling it for later processing in such case.
    """
    validate_on_attestation(store, attestation, is_from_block)

    store_target_checkpoint_state(store, attestation.data.target)

    # Get state at the `target` to fully validate attestation
    target_state = store.checkpoint_states[attestation.data.target]
    indexed_attestation = get_indexed_attestation(target_state, attestation)
    assert is_valid_indexed_attestation(target_state, indexed_attestation)

    # Update latest messages for attesting indices
    update_latest_messages(store, indexed_attestation.attesting_indices, attestation)
```

<!-- NOTES-BEGIN -->

Called upon receiving an attestation. This function simply combines together the helper functions above:

* Validate the attestation
* Compute the state of the target checkpoint that the attestation references
* Check that the attestation signature is valid (this requires the target state to compute the validator set)
* Update the `latest_messages` dict.
#### `on_attester_slashing`

*Note*: `on_attester_slashing` should be called while syncing and a client MUST
maintain the equivocation set of `AttesterSlashing`s from at least the latest
finalized checkpoint.

```python
def on_attester_slashing(store: Store, attester_slashing: AttesterSlashing) -> None:
    """
    Run ``on_attester_slashing`` immediately upon receiving a new ``AttesterSlashing``
    from either within a block or directly on the wire.
    """
    attestation_1 = attester_slashing.attestation_1
    attestation_2 = attester_slashing.attestation_2
    assert is_slashable_attestation_data(attestation_1.data, attestation_2.data)
    state = store.block_states[store.justified_checkpoint.root]
    assert is_valid_indexed_attestation(state, attestation_1)
    assert is_valid_indexed_attestation(state, attestation_2)

    indices = set(attestation_1.attesting_indices).intersection(attestation_2.attesting_indices)
    for index in indices:
        store.equivocating_indices.add(index)
```
