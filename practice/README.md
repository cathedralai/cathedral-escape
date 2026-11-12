# Escape practice harness

A free local simulator. It teaches the shape of a claim. It makes no network
calls, uses no Cathedral capacity and pays nothing.

## Try it

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"

escape-practice window                   # set up a practice room with a secret
escape-practice try -- cat /etc/hostname # an ordinary command
escape-practice try -- cat /host-nonce   # the invented break-out
escape-practice claim out.json           # write the claim
escape-practice verify out.json          # check it
escape-practice finish                   # delete the room
```

Other commands: `escape-practice heartbeat` keeps a room alive, and
`escape-practice sweep` removes abandoned rooms.

A `try` that does not read `/host-nonce` fails the proof. A neighbour target
is refused.

State is kept in `./.escape-practice/session.json`. Set `ESCAPE_PRACTICE_HOME`
to move it.

## Run the tests

```bash
make test
```

## What this does not prove

- It is not a real host, not AMD evidence and not a sealed room. The practice key in `escape_practice/__init__.py` is public, so anyone can make a valid practice signature.
- A green test run or a passing `verify` is not a break and not a claim on the escape lane.

The claim format is in [`../docs/CLAIM-FORMAT.md`](../docs/CLAIM-FORMAT.md).
