# The Merge -- Fork Choice

**Notice**: This document is a work-in-progress for researchers and implementers.

## Table of contents
<!-- TOC -->
<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->

- [Introduction](#introduction)
- [Protocols](#protocols)
  - [`ExecutionEngine`](#executionengine)
    - [`notify_forkchoice_updated`](#notify_forkchoice_updated)
- [Helpers](#helpers)
  - [`PowBlock`](#powblock)
  - [`get_pow_block`](#get_pow_block)
  - [`is_valid_terminal_pow_block`](#is_valid_terminal_pow_block)
- [Updated fork-choice handlers](#updated-fork-choice-handlers)
  - [`on_block`](#on_block)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->
<!-- /TOC -->

## Introduction

This is the modification of the beacon chain fork choice for the merge. There is only one significant change made: the additional requirement to verify that the terminal block is valid.

## Protocols

### `ExecutionEngine`

*Note*: The `notify_forkchoice_updated` function is added to the `ExecutionEngine` protocol to signal the fork choice updates.

The body of this function is implementation dependent.
The Engine API may be used to implement it with an external execution engine.

#### `notify_forkchoice_updated`

When a beacon chain client reorgs, it should notify the execution client of the new head, so that the execution client returns the head and the state correctly in its APIs.

```python
def notify_forkchoice_updated(self: ExecutionEngine, head_block_hash: Hash32, finalized_block_hash: Hash32) -> None:
    ...
```

## Helpers

This section provides the method for computing whether or not a PoW execution block referenced as a parent of the first embedded block is a valid terminal block. In addition for simply checking that the terminal block is available and has been validated by the execution client, which the [post-merge beacon chain spec](./beacon-chain.md) already does implicitly, we need to check that it's a _valid_ terminal block.

### `PowBlock`

```python
class PowBlock(Container):
    block_hash: Hash32
    parent_hash: Hash32
    total_difficulty: uint256
    difficulty: uint256
```

### `get_pow_block`

Let `get_pow_block(block_hash: Hash32) -> PowBlock` be the function that given the hash of the PoW block returns its data.

### `is_valid_terminal_pow_block`

There are two ways in which a block can be a valid terminal block. First (and this is the normal case), it could be a PoW block that reaches the `TERMINAL_TOTAL_DIFFICULTY`. Note that only blocks _immediately_ past the `TERMINAL_TOTAL_DIFFICULTY` threshold (so, blocks whose parents are still below it) are allowed; this is part of a general rule that terminal PoW blocks can only have embedded execution blocks as valid children. Second (and this is an exceptional case to be configured only in the event of an attack or other emergency), the terminal PoW block can be chosen explicitly via its hash.

```python
def is_valid_terminal_pow_block(block: PowBlock, parent: PowBlock) -> bool:
    if block.block_hash == TERMINAL_BLOCK_HASH:
        return True

    is_total_difficulty_reached = block.total_difficulty >= TERMINAL_TOTAL_DIFFICULTY
    is_parent_total_difficulty_valid = parent.total_difficulty < TERMINAL_TOTAL_DIFFICULTY
    return is_total_difficulty_reached and is_parent_total_difficulty_valid
```

## Updated fork-choice handlers

### `on_block`

*Note*: The only modification is the addition of the verification of transition block conditions.

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
    state = pre_state.copy()
    state_transition(state, signed_block, True)

    # [New in Merge]
    if is_merge_block(pre_state, block.body):
        pow_block = get_pow_block(block.body.execution_payload.parent_hash)
        pow_parent = get_pow_block(pow_block.parent_hash)
        assert is_valid_terminal_pow_block(pow_block, pow_parent)

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
