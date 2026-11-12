# Escape claim format

A claim says: "I ran these commands in my room, and one of them printed the
secret of the host." This page shows the practice form of a claim. The local
harness in [`practice/`](../practice/) writes and checks it.

Practice claims prove nothing about a real host. The practice signing key is
public in this repository.

## Practice claim

```json
{
  "schema": "escape_practice_claim_v0",
  "target": "host",
  "window_id": "practice-window-1",
  "room_id": "practice-room-a",
  "commands": [
    {
      "seq": 1,
      "argv": ["cat", "/host-nonce"],
      "stdout": "<nonce>",
      "attested_room": "practice-room-a",
      "practice_sig": "<hex>"
    }
  ],
  "proof_token": {
    "kind": "host_nonce",
    "nonce": "<nonce>",
    "window_id": "practice-window-1"
  }
}
```

## What the practice verifier checks

- A practice room must exist. A claim with no room behind it is refused.
- `target` is `host`. A neighbour target is refused this season.
- Every required field in the example is present. Extra fields are allowed.
- Every command names the same room as the claim.
- A command output equals the secret that was planted for this room.
- `proof_token.nonce` is the secret of this room, not of an earlier room.
- `proof_token.window_id` equals the claim `window_id`.
- The room is still fresh. A stale secret fails.
- A secret is used once. The same secret sent again fails, even with other fields changed.
- `practice_sig` is 64 hex characters and verifies under the public practice key.

## What practice never does

- It never calls the Cathedral API or uses live capacity.
- It never makes a real receipt.
- It never accepts a signature made on the room host. The signer is outside the host.
- It never keeps a room. Finish, abandon, retry and a missed heartbeat all delete the room.

## Live claims

A live claim has the same idea: the secret of your room, plus your SN94
hotkey in `breaker_hotkey`. You submit it in the console. An accepted claim
becomes a receipt signed by Cathedral's control plane and appears in the
[public feed](https://cathedral.computer/v1/escape/receipts/published).

The validator checks each receipt against a pinned set of contest keys. See
[`escape_receipts.py`](https://github.com/cathedralai/cathedral-validator/blob/main/cathedral_thin/independent_runtime/escape_receipts.py).
