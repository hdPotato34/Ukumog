# Engine Workflow

This website now uses the engine as a vendored subtree under:

```text
vendor/ukumog-engine
```

There are still two real repositories:

* website repo: `hdPotato34/Ukumog`
* engine repo: `hdPotato34/ukumog-engine`

The subtree is a copy of the engine repo inside the website repo. It is not a live link.

## What This Means

Changes do not auto-sync between the two repos.

If you commit in `ukumog-engine`, nothing changes in `Ukumog` until you pull the subtree again.

If you edit files under `Ukumog/vendor/ukumog-engine`, those edits only exist in the website repo unless you also port them back to the engine repo yourself.

## Recommended Day-To-Day Rule

Use this default rule:

* engine logic, bridge logic, packaging, tests for the engine: edit in `ukumog-engine`
* website server, React UI, API wiring, review UX: edit in `Ukumog`

Try not to make the same feature half in one repo and half in the other without a clear order.

## Safe Update Flow

When engine work changes first:

1. Work in `ukumog-engine`
2. Commit there
3. In `Ukumog`, pull the updated subtree
4. Commit the subtree update in `Ukumog`

Command:

```powershell
git subtree pull --prefix vendor/ukumog-engine https://github.com/hdPotato34/ukumog-engine.git main --squash
```

## First-Time Add

The subtree was added with:

```powershell
git subtree add --prefix vendor/ukumog-engine https://github.com/hdPotato34/ukumog-engine.git main --squash
```

## When You Can Edit The Vendored Copy Directly

Direct edits inside `vendor/ukumog-engine` are acceptable for:

* emergency local fixes
* quick experiments
* one-off release stabilization

But if the change really belongs to the engine long-term, copy it back to the engine repo soon, or the two codebases will drift.

## Practical Advice

If a change affects both repos:

1. Make the engine-side change in `ukumog-engine` first
2. Commit it
3. Pull subtree into `Ukumog`
4. Make website-side integration changes in `Ukumog`
5. Commit website changes separately

That keeps ownership clear and makes later debugging much easier.

## Remote Notes

`Ukumog` is connected to:

```text
origin https://github.com/hdPotato34/Ukumog.git
```

`ukumog-engine` is connected to:

```text
origin https://github.com/hdPotato34/ukumog-engine.git
```

Those remote settings are per local clone. They are not shared automatically with other clones or machines.
